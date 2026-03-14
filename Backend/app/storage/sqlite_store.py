from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import aiosqlite

from app.models.booking import BookingStatus
from app.models.call import CallSessionState, TranscriptTurn


class SQLiteStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        async with self._lock:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    """
                    CREATE TABLE IF NOT EXISTS calls (
                        call_sid TEXT PRIMARY KEY,
                        stream_sid TEXT,
                        from_number TEXT,
                        to_number TEXT,
                        call_status TEXT NOT NULL,
                        booking_status TEXT NOT NULL,
                        guest_name TEXT,
                        check_in_date TEXT,
                        nights INTEGER,
                        guests INTEGER,
                        room_type TEXT,
                        phone_number_if_provided TEXT,
                        special_requests TEXT,
                        handoff_requested INTEGER NOT NULL DEFAULT 0,
                        handoff_reason TEXT,
                        end_reason TEXT,
                        started_at TEXT NOT NULL,
                        ended_at TEXT,
                        transcripts_json TEXT NOT NULL DEFAULT '[]',
                        metadata_json TEXT NOT NULL DEFAULT '{}',
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                await db.commit()

    async def upsert_call(self, session: CallSessionState) -> None:
        async with self._lock:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    """
                    INSERT INTO calls (
                        call_sid,
                        stream_sid,
                        from_number,
                        to_number,
                        call_status,
                        booking_status,
                        guest_name,
                        check_in_date,
                        nights,
                        guests,
                        room_type,
                        phone_number_if_provided,
                        special_requests,
                        handoff_requested,
                        handoff_reason,
                        end_reason,
                        started_at,
                        ended_at,
                        transcripts_json,
                        metadata_json,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(call_sid) DO UPDATE SET
                        stream_sid = excluded.stream_sid,
                        from_number = excluded.from_number,
                        to_number = excluded.to_number,
                        call_status = excluded.call_status,
                        booking_status = excluded.booking_status,
                        guest_name = excluded.guest_name,
                        check_in_date = excluded.check_in_date,
                        nights = excluded.nights,
                        guests = excluded.guests,
                        room_type = excluded.room_type,
                        phone_number_if_provided = excluded.phone_number_if_provided,
                        special_requests = excluded.special_requests,
                        handoff_requested = excluded.handoff_requested,
                        handoff_reason = excluded.handoff_reason,
                        end_reason = excluded.end_reason,
                        started_at = excluded.started_at,
                        ended_at = excluded.ended_at,
                        transcripts_json = excluded.transcripts_json,
                        metadata_json = excluded.metadata_json,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (
                        session.call_sid,
                        session.stream_sid,
                        session.from_number,
                        session.to_number,
                        session.call_status,
                        session.booking_status.value,
                        session.booking.guest_name,
                        session.booking.check_in_date,
                        session.booking.nights,
                        session.booking.guests,
                        session.booking.room_type,
                        session.booking.phone_number_if_provided,
                        session.booking.special_requests,
                        1 if session.handoff_requested else 0,
                        session.handoff_reason,
                        session.end_reason,
                        session.started_at,
                        session.ended_at,
                        json.dumps(
                            [turn.model_dump(mode="json") for turn in session.transcripts]
                        ),
                        json.dumps(session.metadata),
                    ),
                )
                await db.commit()

    def _deserialize_row(self, row: aiosqlite.Row) -> dict[str, Any]:
        result = dict(row)
        result["transcripts"] = json.loads(result.pop("transcripts_json", "[]"))
        result["metadata"] = json.loads(result.pop("metadata_json", "{}"))
        result["handoff_requested"] = bool(result.get("handoff_requested"))
        return result

    async def get_call(self, call_sid: str) -> dict[str, Any] | None:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM calls WHERE call_sid = ?", (call_sid,))
            row = await cursor.fetchone()
            if row is None:
                return None
            return self._deserialize_row(row)

    async def load_call_session(
        self, call_sid: str, hotel_name: str
    ) -> CallSessionState | None:
        data = await self.get_call(call_sid)
        if data is None:
            return None

        session = CallSessionState(
            call_sid=call_sid,
            hotel_name=hotel_name,
            stream_sid=data.get("stream_sid"),
            from_number=data.get("from_number"),
            to_number=data.get("to_number"),
            call_status=data.get("call_status", "initiated"),
            booking_status=BookingStatus(data.get("booking_status", "in_progress")),
            handoff_requested=data.get("handoff_requested", False),
            handoff_reason=data.get("handoff_reason"),
            end_reason=data.get("end_reason"),
            started_at=data.get("started_at"),
            ended_at=data.get("ended_at"),
            metadata=data.get("metadata", {}),
        )
        session.booking.guest_name = data.get("guest_name")
        session.booking.check_in_date = data.get("check_in_date")
        session.booking.nights = data.get("nights")
        session.booking.guests = data.get("guests")
        session.booking.room_type = data.get("room_type")
        session.booking.phone_number_if_provided = data.get("phone_number_if_provided")
        session.booking.special_requests = data.get("special_requests")

        for transcript in data.get("transcripts", []):
            try:
                session.transcripts.append(TranscriptTurn.model_validate(transcript))
            except Exception:
                continue

        return session

    async def list_calls(self) -> list[dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM calls ORDER BY updated_at DESC, started_at DESC"
            )
            rows = await cursor.fetchall()
            return [self._deserialize_row(row) for row in rows]
