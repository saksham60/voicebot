from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from app.models.booking import BookingStatus, BookingUpdate
from app.models.call import CallSessionState
from app.services.booking_provider import BookingProviderClient
from app.services.call_transfer import CallTransferService
from app.services.crm import CrmPmsClient
from app.storage.sqlite_store import SQLiteStore
from app.utils.logging import log_event


@dataclass(slots=True)
class ToolExecutionResult:
    call_id: str
    output: dict[str, Any]
    close_after_response: bool = False


class RealtimeToolExecutor:
    def __init__(
        self,
        store: SQLiteStore,
        booking_provider: BookingProviderClient,
        crm_client: CrmPmsClient,
        transfer_service: CallTransferService,
        logger: logging.Logger,
    ) -> None:
        self.store = store
        self.booking_provider = booking_provider
        self.crm_client = crm_client
        self.transfer_service = transfer_service
        self.logger = logger

    @property
    def tool_definitions(self) -> list[dict[str, Any]]:
        booking_properties = {
            "guest_name": {"type": "string"},
            "check_in_date": {"type": "string"},
            "nights": {"type": "integer"},
            "guests": {"type": "integer"},
            "room_type": {"type": "string"},
            "phone_number_if_provided": {"type": "string"},
            "special_requests": {"type": "string"},
        }
        return [
            {
                "type": "function",
                "name": "update_booking_request",
                "description": (
                    "Capture and persist any reservation details the caller explicitly provides or corrects. Use it immediately every time you learn any new field, even if the booking is incomplete."
                ),
                "parameters": {
                    "type": "object",
                    "properties": booking_properties,
                    "additionalProperties": False,
                },
            },
            {
                "type": "function",
                "name": "confirm_reservation_request",
                "description": (
                    "Use only after the caller explicitly confirms the final booking summary."
                ),
                "parameters": {
                    "type": "object",
                    "properties": booking_properties,
                    "additionalProperties": False,
                },
            },
            {
                "type": "function",
                "name": "request_human_handoff",
                "description": (
                    "Use if the caller asks for a human or the conversation cannot continue safely."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "reason": {"type": "string"},
                    },
                    "required": ["reason"],
                    "additionalProperties": False,
                },
            },
            {
                "type": "function",
                "name": "mark_booking_not_completed",
                "description": (
                    "Use if the caller decides not to continue or the booking request was not confirmed."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "reason": {"type": "string"},
                    },
                    "required": ["reason"],
                    "additionalProperties": False,
                },
            },
        ]

    async def execute(
        self, session: CallSessionState, tool_call: dict[str, Any]
    ) -> ToolExecutionResult:
        name = tool_call.get("name", "")
        call_id = str(tool_call.get("call_id") or tool_call.get("id") or "")
        raw_arguments = tool_call.get("arguments") or "{}"

        try:
            arguments = json.loads(raw_arguments)
        except json.JSONDecodeError:
            arguments = {}

        if name == "update_booking_request":
            return await self._update_booking_request(session, call_id, arguments)
        if name == "confirm_reservation_request":
            return await self._confirm_reservation_request(session, call_id, arguments)
        if name == "request_human_handoff":
            return await self._request_human_handoff(session, call_id, arguments)
        if name == "mark_booking_not_completed":
            return await self._mark_booking_not_completed(session, call_id, arguments)

        log_event(
            self.logger,
            "tool.unknown",
            call_sid=session.call_sid,
            tool_name=name,
            arguments=arguments,
        )
        return ToolExecutionResult(
            call_id=call_id,
            output={"status": "error", "message": f"Unknown tool: {name}"},
        )

    async def _update_booking_request(
        self, session: CallSessionState, call_id: str, arguments: dict[str, Any]
    ) -> ToolExecutionResult:
        try:
            update = BookingUpdate.model_validate(arguments)
        except ValidationError as exc:
            return ToolExecutionResult(
                call_id=call_id,
                output={"status": "error", "message": str(exc)},
            )

        changed_fields = session.apply_booking_update(update)
        await self.store.upsert_call(session)
        log_event(
            self.logger,
            "booking.updated",
            call_sid=session.call_sid,
            changed_fields=changed_fields,
            booking_status=session.booking_status.value,
            booking=session.booking.to_public_dict(),
        )
        return ToolExecutionResult(
            call_id=call_id,
            output={
                "status": "ok",
                "changed_fields": changed_fields,
                "missing_fields": session.booking.missing_fields(),
                "booking_status": session.booking_status.value,
            },
        )

    async def _confirm_reservation_request(
        self, session: CallSessionState, call_id: str, arguments: dict[str, Any]
    ) -> ToolExecutionResult:
        try:
            update = BookingUpdate.model_validate(arguments)
        except ValidationError as exc:
            return ToolExecutionResult(
                call_id=call_id,
                output={"status": "error", "message": str(exc)},
            )

        session.apply_booking_update(update)
        session.booking_status = BookingStatus.CONFIRMED
        provider_result = await self.booking_provider.submit_reservation_request(session)
        crm_result = await self.crm_client.sync_reservation_request(session)
        await self.store.upsert_call(session)
        log_event(
            self.logger,
            "booking.confirmed",
            call_sid=session.call_sid,
            booking=session.booking.to_public_dict(),
            provider_result=provider_result,
            crm_result=crm_result,
        )
        return ToolExecutionResult(
            call_id=call_id,
            output={
                "status": "ok",
                "booking_status": session.booking_status.value,
                "provider_result": provider_result,
                "crm_result": crm_result,
            },
        )

    async def _request_human_handoff(
        self, session: CallSessionState, call_id: str, arguments: dict[str, Any]
    ) -> ToolExecutionResult:
        reason = str(arguments.get("reason", "")).strip() or "caller requested human assistance"
        session.handoff_requested = True
        session.handoff_reason = reason
        session.booking_status = BookingStatus.HANDOFF_REQUESTED
        crm_result = await self.crm_client.sync_reservation_request(session)
        await self.store.upsert_call(session)
        log_event(
            self.logger,
            "call.handoff_requested",
            call_sid=session.call_sid,
            reason=reason,
            transfer_available=self.transfer_service.enabled,
            crm_result=crm_result,
        )
        return ToolExecutionResult(
            call_id=call_id,
            output={
                "status": "ok",
                "booking_status": session.booking_status.value,
                "reason": reason,
                "transfer_available": self.transfer_service.enabled,
                "transfer_target": self.transfer_service.transfer_target(),
            },
            close_after_response=True,
        )

    async def _mark_booking_not_completed(
        self, session: CallSessionState, call_id: str, arguments: dict[str, Any]
    ) -> ToolExecutionResult:
        reason = str(arguments.get("reason", "")).strip() or "booking not completed"
        session.booking_status = BookingStatus.NOT_COMPLETED
        session.end_reason = reason
        await self.store.upsert_call(session)
        log_event(
            self.logger,
            "booking.not_completed",
            call_sid=session.call_sid,
            reason=reason,
            booking=session.booking.to_public_dict(),
        )
        return ToolExecutionResult(
            call_id=call_id,
            output={
                "status": "ok",
                "booking_status": session.booking_status.value,
                "reason": reason,
            },
            close_after_response=True,
        )

