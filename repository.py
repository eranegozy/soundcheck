"""Soundcheck data access: domain logic over Google storage."""

import mimetypes
import os
from datetime import date

from inventory import InventoryError, get_item, parse_inventory_rows
from storage import GoogleStorage, StorageError
from transactions import (
    TransactionError,
    append_row_to_csv,
    parse_transactions_csv,
    replay_actions,
)

_repository: "SoundcheckRepository | None" = None


def _normalize_drive_id(value: str) -> str:
    value = value.strip()
    if "/folders/" in value:
        return value.split("/folders/", 1)[1].split("/")[0].split("?")[0]
    return value


class SoundcheckRepository:
    def __init__(
        self,
        google: GoogleStorage,
        *,
        transactions_folder_id: str,
        images_folder_id: str,
        sheet_id: str,
        sheet_range: str,
    ) -> None:
        self._google = google
        self._transactions_folder_id = transactions_folder_id
        self._images_folder_id = images_folder_id
        self._sheet_id = sheet_id
        self._sheet_range = sheet_range

    @classmethod
    def from_env(cls, google: GoogleStorage | None = None) -> "SoundcheckRepository":
        transactions_folder_id = os.environ.get(
            "GOOGLE_DRIVE_TRANSACTIONS_FOLDER_ID", ""
        ).strip()
        images_folder_id = os.environ.get("GOOGLE_DRIVE_IMAGES_FOLDER_ID", "").strip()
        sheet_id = os.environ.get("GOOGLE_SHEET_ID", "").strip()
        sheet_range = os.environ.get("GOOGLE_SHEET_RANGE", "Inventory!A:I").strip()

        missing = [
            name
            for name, value in (
                ("GOOGLE_DRIVE_TRANSACTIONS_FOLDER_ID", transactions_folder_id),
                ("GOOGLE_DRIVE_IMAGES_FOLDER_ID", images_folder_id),
                ("GOOGLE_SHEET_ID", sheet_id),
            )
            if not value
        ]
        if missing:
            raise StorageError(
                "Missing required environment variables: " + ", ".join(missing)
            )

        return cls(
            google=google or GoogleStorage(),
            transactions_folder_id=_normalize_drive_id(transactions_folder_id),
            images_folder_id=_normalize_drive_id(images_folder_id),
            sheet_id=sheet_id,
            sheet_range=sheet_range or "Inventory!A:I",
        )

    def load_inventory(self) -> list[dict]:
        values = self._google.read_sheet_values(self._sheet_id, self._sheet_range)
        return parse_inventory_rows(values)

    def get_item(self, item_id: str) -> dict | None:
        return get_item(self.load_inventory(), item_id)

    def load_transactions(self, item_id: str) -> list[dict[str, str]]:
        content = self._google.read_text_file(
            self._transactions_folder_id,
            f"{item_id}.csv",
        )
        if content is None:
            return []
        return parse_transactions_csv(content)

    def load_item_state(self, item_id: str, on_date: date):
        return replay_actions(self.load_transactions(item_id), on_date)

    def append_transaction(self, item_id: str, row: dict[str, str]) -> None:
        filename = f"{item_id}.csv"

        def transform(existing: str | None) -> str:
            try:
                return append_row_to_csv(existing, row)
            except TransactionError as exc:
                raise StorageError(
                    f"Invalid transaction row for {item_id}"
                ) from exc

        self._google.write_text_file(
            self._transactions_folder_id,
            filename,
            transform,
            lock_key=item_id,
            mimetype="text/csv",
        )

    def get_image_bytes(self, filename: str) -> tuple[bytes, str]:
        data = self._google.read_bytes_file(self._images_folder_id, filename)
        mime_type, _ = mimetypes.guess_type(filename)
        return data, mime_type or "application/octet-stream"


def get_repository() -> SoundcheckRepository:
    global _repository
    if _repository is None:
        _repository = SoundcheckRepository.from_env()
    return _repository
