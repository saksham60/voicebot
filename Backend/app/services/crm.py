from __future__ import annotations

from typing import Any

from app.models.call import CallSessionState


class CrmPmsClient:
    async def sync_reservation_request(self, session: CallSessionState) -> dict[str, Any]:
        return {
            "provider": "local",
            "status": "captured_locally",
            "call_sid": session.call_sid,
            "booking_status": session.booking_status.value,
        }
