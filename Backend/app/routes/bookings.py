from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(prefix="/bookings", tags=["bookings"])


@router.get("")
async def list_bookings(request: Request) -> list[dict[str, object]]:
    rows = await request.app.state.store.list_calls()
    results: list[dict[str, object]] = []
    for row in rows:
        metadata = row.get("metadata", {})
        results.append(
            {
                "call_sid": row.get("call_sid"),
                "source": metadata.get("channel", "twilio"),
                "transport": metadata.get("transport"),
                "call_status": row.get("call_status"),
                "booking_status": row.get("booking_status"),
                "guest_name": row.get("guest_name"),
                "check_in_date": row.get("check_in_date"),
                "nights": row.get("nights"),
                "guests": row.get("guests"),
                "room_type": row.get("room_type"),
                "phone_number_if_provided": row.get("phone_number_if_provided"),
                "special_requests": row.get("special_requests"),
                "handoff_requested": row.get("handoff_requested"),
                "started_at": row.get("started_at"),
                "ended_at": row.get("ended_at"),
                "updated_at": row.get("updated_at"),
                "transcript_turns": len(row.get("transcripts", [])),
            }
        )
    return results
