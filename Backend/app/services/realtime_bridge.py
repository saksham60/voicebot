from __future__ import annotations

import asyncio
import base64
import json
import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

import aiohttp
from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from app.config import Settings
from app.models.call import CallSessionState, TranscriptSpeaker
from app.prompts.receptionist import build_receptionist_prompt
from app.services.booking_provider import BookingProviderClient
from app.services.call_transfer import CallTransferService
from app.services.crm import CrmPmsClient
from app.services.tool_executor import RealtimeToolExecutor
from app.storage.sqlite_store import SQLiteStore
from app.utils.logging import log_event


@dataclass(slots=True)
class PendingAudioMark:
    item_id: str | None
    duration_ms: int


class RealtimeCallBridge:
    def __init__(
        self,
        settings: Settings,
        store: SQLiteStore,
        booking_provider: BookingProviderClient,
        crm_client: CrmPmsClient,
        transfer_service: CallTransferService,
        logger: logging.Logger,
    ) -> None:
        self.settings = settings
        self.store = store
        self.logger = logger
        self.session: CallSessionState | None = None
        self.stream_sid: str | None = None
        self._openai_socket: aiohttp.ClientWebSocketResponse | None = None
        self.openai_ready = asyncio.Event()
        self.twilio_started = asyncio.Event()
        self.session_bootstrapped = False
        self.close_after_assistant_reply = False
        self.pending_marks: dict[str, PendingAudioMark] = {}
        self.cleared_marks: set[str] = set()
        self.played_audio_ms: dict[str, int] = defaultdict(int)
        self.current_assistant_item_id: str | None = None
        self.last_assistant_item_id: str | None = None
        self.mark_counter = 0
        self.tool_executor = RealtimeToolExecutor(
            store=store,
            booking_provider=booking_provider,
            crm_client=crm_client,
            transfer_service=transfer_service,
            logger=logger,
        )

    @property
    def call_sid(self) -> str | None:
        return self.session.call_sid if self.session is not None else None

    async def handle(self, twilio_socket: WebSocket) -> None:
        await twilio_socket.accept()

        openai_url = (
            f"wss://api.openai.com/v1/realtime?model={self.settings.openai_realtime_model}"
        )
        headers = {
            "Authorization": f"Bearer {self.settings.openai_api_key}",
            "OpenAI-Beta": "realtime=v1",
        }
        timeout = aiohttp.ClientTimeout(
            total=None,
            connect=self.settings.openai_connect_timeout_seconds,
        )

        try:
            async with aiohttp.ClientSession(timeout=timeout) as client:
                async with client.ws_connect(
                    openai_url,
                    headers=headers,
                    heartbeat=self.settings.openai_heartbeat_seconds,
                    autoping=True,
                ) as openai_socket:
                    self._openai_socket = openai_socket
                    twilio_task = asyncio.create_task(
                        self._receive_twilio_messages(twilio_socket)
                    )
                    openai_task = asyncio.create_task(
                        self._receive_openai_messages(twilio_socket, openai_socket)
                    )
                    done, pending = await asyncio.wait(
                        {twilio_task, openai_task},
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    for task in pending:
                        task.cancel()
                    await asyncio.gather(*pending, return_exceptions=True)
                    for task in done:
                        exc = task.exception()
                        if exc is not None:
                            raise exc
        except WebSocketDisconnect:
            log_event(self.logger, "call.twilio_disconnected", call_sid=self.call_sid)
        except aiohttp.ClientError as exc:
            log_event(
                self.logger,
                "call.openai_connection_failed",
                call_sid=self.call_sid,
                error=str(exc),
            )
            if self.session is not None:
                self.session.end_reason = "OpenAI Realtime connection failed"
        except Exception as exc:
            log_event(
                self.logger,
                "call.bridge_error",
                call_sid=self.call_sid,
                error=str(exc),
            )
            if self.session is not None and not self.session.end_reason:
                self.session.end_reason = str(exc)
        finally:
            await self._finalize_session()
            await self._safe_close_twilio_socket(twilio_socket)

    async def _receive_twilio_messages(self, twilio_socket: WebSocket) -> None:
        while True:
            raw_message = await twilio_socket.receive_text()
            message = json.loads(raw_message)
            event_type = message.get("event")

            if event_type == "start":
                await self._handle_twilio_start(message)
                continue

            if event_type == "media":
                payload = message.get("media", {}).get("payload")
                if payload:
                    await self._send_openai_json(
                        {"type": "input_audio_buffer.append", "audio": payload}
                    )
                continue

            if event_type == "mark":
                await self._handle_twilio_mark(message, twilio_socket)
                continue

            if event_type == "stop":
                if self.session is not None:
                    self.session.call_status = "stopped"
                log_event(
                    self.logger,
                    "call.twilio_stream_stopped",
                    call_sid=self.call_sid,
                    stream_sid=self.stream_sid,
                )
                return

    async def _receive_openai_messages(
        self, twilio_socket: WebSocket, openai_socket: aiohttp.ClientWebSocketResponse
    ) -> None:
        async for raw_message in openai_socket:
            if raw_message.type == aiohttp.WSMsgType.TEXT:
                event = json.loads(raw_message.data)
                await self._handle_openai_event(event, twilio_socket)
                continue
            if raw_message.type == aiohttp.WSMsgType.ERROR:
                raise RuntimeError("OpenAI Realtime websocket returned an error frame")
            if raw_message.type in {aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED}:
                return

    async def _handle_twilio_start(self, message: dict[str, Any]) -> None:
        start = message.get("start", {})
        self.stream_sid = start.get("streamSid")
        call_sid = str(start.get("callSid") or "").strip()
        existing = await self.store.get_call(call_sid)

        if self.session is None:
            self.session = CallSessionState(
                call_sid=call_sid,
                hotel_name=self.settings.hotel_name,
                stream_sid=self.stream_sid,
                from_number=existing.get("from_number") if existing else None,
                to_number=existing.get("to_number") if existing else None,
                call_status="streaming",
            )
        else:
            self.session.stream_sid = self.stream_sid
            self.session.call_status = "streaming"
            if existing and not self.session.from_number:
                self.session.from_number = existing.get("from_number")
            if existing and not self.session.to_number:
                self.session.to_number = existing.get("to_number")

        await self.store.upsert_call(self.session)
        self.twilio_started.set()
        log_event(
            self.logger,
            "call.twilio_stream_started",
            call_sid=call_sid,
            stream_sid=self.stream_sid,
        )
        await self._maybe_bootstrap_openai()

    async def _handle_openai_event(
        self, event: dict[str, Any], twilio_socket: WebSocket
    ) -> None:
        event_type = event.get("type", "")

        if event_type == "session.created":
            self.openai_ready.set()
            log_event(self.logger, "openai.session_created", call_sid=self.call_sid)
            await self._maybe_bootstrap_openai()
            return

        if event_type == "session.updated":
            log_event(self.logger, "openai.session_updated", call_sid=self.call_sid)
            return

        if event_type in {"response.output_item.added", "response.output_item.created"}:
            item = event.get("item", {})
            item_id = item.get("id")
            if item.get("type") == "message" and item_id:
                self.current_assistant_item_id = str(item_id)
                self.last_assistant_item_id = str(item_id)
            return

        if event_type == "response.output_audio.delta":
            await self._forward_openai_audio_to_twilio(event, twilio_socket)
            return

        if event_type == "response.output_audio_transcript.done":
            transcript = str(event.get("transcript", "")).strip()
            if transcript and self.session is not None:
                self.session.add_transcript(TranscriptSpeaker.ASSISTANT, transcript)
                await self.store.upsert_call(self.session)
                log_event(
                    self.logger,
                    "transcript.assistant",
                    call_sid=self.call_sid,
                    text=transcript,
                )
            return

        if event_type == "conversation.item.input_audio_transcription.completed":
            transcript = str(event.get("transcript", "")).strip()
            if transcript and self.session is not None:
                self.session.add_transcript(TranscriptSpeaker.CALLER, transcript)
                await self.store.upsert_call(self.session)
                log_event(
                    self.logger,
                    "transcript.caller",
                    call_sid=self.call_sid,
                    text=transcript,
                )
            return

        if event_type == "input_audio_buffer.speech_started":
            await self._handle_barge_in(twilio_socket)
            return

        if event_type == "response.done":
            await self._handle_response_done(event, twilio_socket)
            return

        if event_type == "error":
            log_event(
                self.logger,
                "openai.error",
                call_sid=self.call_sid,
                payload=event,
            )
            if self.session is not None and not self.session.end_reason:
                self.session.end_reason = "OpenAI Realtime error"

    async def _maybe_bootstrap_openai(self) -> None:
        if not self.openai_ready.is_set() or not self.twilio_started.is_set():
            return
        if self.session_bootstrapped:
            return
        self.session_bootstrapped = True
        await self._send_openai_json(self._build_session_update_event())
        await self._send_openai_json(self._build_initial_greeting_event())

    def _build_session_update_event(self) -> dict[str, Any]:
        return {
            "type": "session.update",
            "session": {
                "instructions": build_receptionist_prompt(self.settings),
                "output_modalities": ["audio"],
                "audio": {
                    "input": {
                        "format": {"type": "audio/pcmu"},
                        "turn_detection": {"type": "server_vad"},
                        "transcription": {
                            "model": self.settings.openai_transcription_model
                        },
                    },
                    "output": {
                        "format": {"type": "audio/pcmu"},
                        "voice": self.settings.openai_realtime_voice,
                    },
                },
                "tools": self.tool_executor.tool_definitions,
                "tool_choice": "auto",
            },
        }

    def _build_initial_greeting_event(self) -> dict[str, Any]:
        return {
            "type": "response.create",
            "response": {
                "output_modalities": ["audio"],
                "instructions": (
                    "Begin the call now for Hotel Oman only. Do not ask for city, branch, property, area, or location. Greet the caller professionally, confirm this is for Hotel Oman, and ask for the check-in date."
                ),
            },
        }

    async def _forward_openai_audio_to_twilio(
        self, event: dict[str, Any], twilio_socket: WebSocket
    ) -> None:
        if not self.stream_sid:
            return
        payload = event.get("delta")
        if not payload:
            return
        item_id = event.get("item_id") or self.current_assistant_item_id
        if item_id:
            self.last_assistant_item_id = str(item_id)

        mark_name = f"ai-audio-{self.mark_counter}"
        self.mark_counter += 1
        self.pending_marks[mark_name] = PendingAudioMark(
            item_id=str(item_id) if item_id else None,
            duration_ms=self._audio_duration_ms(payload),
        )

        await self._send_twilio_json(
            twilio_socket,
            {
                "event": "media",
                "streamSid": self.stream_sid,
                "media": {"payload": payload},
            },
        )
        await self._send_twilio_json(
            twilio_socket,
            {
                "event": "mark",
                "streamSid": self.stream_sid,
                "mark": {"name": mark_name},
            },
        )

    async def _handle_response_done(
        self, event: dict[str, Any], twilio_socket: WebSocket
    ) -> None:
        response = event.get("response", {})
        output_items = response.get("output", [])
        function_calls = [
            item for item in output_items if item.get("type") == "function_call"
        ]

        if function_calls and self.session is not None:
            close_after_response = False
            for tool_call in function_calls:
                result = await self.tool_executor.execute(self.session, tool_call)
                close_after_response = close_after_response or result.close_after_response
                self.session.add_transcript(
                    TranscriptSpeaker.TOOL,
                    f"{tool_call.get('name')}: {json.dumps(result.output)}",
                )
                await self._send_openai_json(
                    {
                        "type": "conversation.item.create",
                        "item": {
                            "type": "function_call_output",
                            "call_id": result.call_id,
                            "output": json.dumps(result.output),
                        },
                    }
                )
            await self.store.upsert_call(self.session)
            await self._send_openai_json(
                {
                    "type": "response.create",
                    "response": {"output_modalities": ["audio"]},
                }
            )
            if close_after_response:
                self.close_after_assistant_reply = True
            return

        if self.close_after_assistant_reply and not self.pending_marks:
            await self._safe_close_twilio_socket(twilio_socket)

    async def _handle_barge_in(self, twilio_socket: WebSocket) -> None:
        if not self.stream_sid:
            return
        if self.pending_marks:
            self.cleared_marks.update(self.pending_marks.keys())
        await self._send_twilio_json(
            twilio_socket,
            {"event": "clear", "streamSid": self.stream_sid},
        )

        if self.last_assistant_item_id:
            played_ms = self.played_audio_ms.get(self.last_assistant_item_id, 0)
            if played_ms > 0:
                await self._send_openai_json(
                    {
                        "type": "conversation.item.truncate",
                        "item_id": self.last_assistant_item_id,
                        "content_index": 0,
                        "audio_end_ms": played_ms,
                    }
                )

    async def _handle_twilio_mark(
        self, message: dict[str, Any], twilio_socket: WebSocket
    ) -> None:
        name = message.get("mark", {}).get("name")
        if not name:
            return
        mark = self.pending_marks.pop(name, None)
        if mark is None:
            return
        if name in self.cleared_marks:
            self.cleared_marks.discard(name)
        elif mark.item_id:
            self.played_audio_ms[mark.item_id] += mark.duration_ms
        if self.close_after_assistant_reply and not self.pending_marks:
            await self._safe_close_twilio_socket(twilio_socket)

    def _audio_duration_ms(self, payload: str) -> int:
        try:
            audio_bytes = base64.b64decode(payload)
        except Exception:
            return 0
        return int(len(audio_bytes) / 8000 * 1000)

    async def _send_openai_json(self, payload: dict[str, Any]) -> None:
        if self._openai_socket is None:
            return
        await self._openai_socket.send_json(payload)

    async def _send_twilio_json(
        self, twilio_socket: WebSocket, payload: dict[str, Any]
    ) -> None:
        if twilio_socket.client_state == WebSocketState.DISCONNECTED:
            return
        await twilio_socket.send_text(json.dumps(payload))

    async def _safe_close_twilio_socket(self, twilio_socket: WebSocket) -> None:
        if twilio_socket.client_state != WebSocketState.DISCONNECTED:
            await twilio_socket.close()

    async def _finalize_session(self) -> None:
        if self.session is None:
            return
        self.session.finalize(self.session.end_reason)
        await self.store.upsert_call(self.session)
        log_event(
            self.logger,
            "call.completed",
            call_sid=self.session.call_sid,
            booking_status=self.session.booking_status.value,
            booking=self.session.booking.to_public_dict(),
            handoff_requested=self.session.handoff_requested,
            end_reason=self.session.end_reason,
        )

