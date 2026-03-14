from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from app.models.booking import BookingData, BookingStatus, BookingUpdate


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class TranscriptSpeaker(str, Enum):
    CALLER = "caller"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


class TranscriptTurn(BaseModel):
    speaker: TranscriptSpeaker
    text: str
    timestamp: str = Field(default_factory=utc_now_iso)


class CallSessionState(BaseModel):
    call_sid: str
    hotel_name: str
    stream_sid: str | None = None
    from_number: str | None = None
    to_number: str | None = None
    call_status: str = "initiated"
    booking_status: BookingStatus = BookingStatus.IN_PROGRESS
    booking: BookingData = Field(default_factory=BookingData)
    handoff_requested: bool = False
    handoff_reason: str | None = None
    end_reason: str | None = None
    started_at: str = Field(default_factory=utc_now_iso)
    ended_at: str | None = None
    transcripts: list[TranscriptTurn] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def add_transcript(self, speaker: TranscriptSpeaker | str, text: str) -> None:
        clean_text = text.strip()
        if not clean_text:
            return
        self.transcripts.append(TranscriptTurn(speaker=speaker, text=clean_text))

    def apply_booking_update(self, update: BookingUpdate) -> list[str]:
        changed_fields = self.booking.apply_update(update)
        if self.booking_status not in {
            BookingStatus.CONFIRMED,
            BookingStatus.HANDOFF_REQUESTED,
            BookingStatus.NOT_COMPLETED,
        }:
            self.booking_status = (
                BookingStatus.NEEDS_CONFIRMATION
                if self.booking.has_core_details()
                else BookingStatus.IN_PROGRESS
            )
        return changed_fields

    def finalize(self, reason: str | None = None) -> None:
        self.ended_at = utc_now_iso()
        if reason and not self.end_reason:
            self.end_reason = reason
        if self.booking_status in {
            BookingStatus.IN_PROGRESS,
            BookingStatus.NEEDS_CONFIRMATION,
        }:
            self.booking_status = BookingStatus.NOT_COMPLETED
            self.end_reason = self.end_reason or "call ended before confirmation"
        self.call_status = "completed"
