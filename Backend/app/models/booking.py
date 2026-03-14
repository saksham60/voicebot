from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel


class BookingStatus(str, Enum):
    IN_PROGRESS = "in_progress"
    NEEDS_CONFIRMATION = "needs_confirmation"
    CONFIRMED = "confirmed"
    HANDOFF_REQUESTED = "handoff_requested"
    NOT_COMPLETED = "not_completed"


class BookingUpdate(BaseModel):
    guest_name: str | None = None
    check_in_date: str | None = None
    nights: int | None = None
    guests: int | None = None
    room_type: str | None = None
    phone_number_if_provided: str | None = None
    special_requests: str | None = None


class BookingData(BookingUpdate):
    def apply_update(self, update: BookingUpdate) -> list[str]:
        changed_fields: list[str] = []
        for field_name in self.__class__.model_fields:
            value = getattr(update, field_name)
            if value is None:
                continue
            if isinstance(value, str):
                value = value.strip()
                if not value:
                    continue
            if getattr(self, field_name) == value:
                continue
            setattr(self, field_name, value)
            changed_fields.append(field_name)
        return changed_fields

    def missing_fields(self) -> list[str]:
        required = {
            "check_in_date": self.check_in_date,
            "nights": self.nights,
            "guests": self.guests,
            "room_type": self.room_type,
        }
        return [field_name for field_name, value in required.items() if value in (None, "")]

    def has_core_details(self) -> bool:
        return not self.missing_fields()

    def to_public_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
