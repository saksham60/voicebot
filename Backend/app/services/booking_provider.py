from __future__ import annotations

from typing import Any

from app.models.call import CallSessionState


class BookingProviderClient:
    def __init__(self, provider_name: str) -> None:
        self.provider_name = provider_name

    async def submit_reservation_request(
        self, session: CallSessionState
    ) -> dict[str, Any]:
        return {
            "provider": self.provider_name,
            "status": "queued_for_manual_review",
            "message": (
                "This MVP does not check live inventory. Hotel staff must review and confirm "
                "availability manually."
            ),
            "call_sid": session.call_sid,
        }
