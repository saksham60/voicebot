from __future__ import annotations


class CallTransferService:
    def __init__(self, transfer_number: str) -> None:
        self.transfer_number = transfer_number.strip()

    @property
    def enabled(self) -> bool:
        return bool(self.transfer_number)

    def transfer_target(self) -> str | None:
        return self.transfer_number or None
