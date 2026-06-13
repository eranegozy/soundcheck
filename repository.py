"""Soundcheck data access: domain logic over Google storage."""

import mimetypes
import os
import threading
from datetime import date

from inventory import parse_inventory_rows
from storage import GoogleStorage, StorageError
from transactions import (
    TransactionError,
    append_row_to_csv,
    parse_transactions_csv,
    replay_actions,
    serialize_transactions_csv,
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

        self._lock = threading.Lock()
        self._inventory: list[dict] | None = None
        self._items_by_id: dict[str, dict] = {}
        self._transactions: dict[str, list[dict[str, str]]] = {}
        self._images: dict[str, tuple[bytes, str]] = {}
        self._transaction_locks: dict[str, threading.Lock] = {}
        self._transaction_locks_guard = threading.Lock()

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

    def _fetch_inventory(self) -> list[dict]:
        values = self._google.read_sheet_values(self._sheet_id, self._sheet_range)
        items = parse_inventory_rows(values)
        self._inventory = items
        self._items_by_id = {item["item_id"]: item for item in items}
        return items

    def load_inventory(self) -> list[dict]:
        with self._lock:
            if self._inventory is not None:
                return self._inventory
            return self._fetch_inventory()

    def refresh_inventory(self) -> list[dict]:
        with self._lock:
            self._inventory = None
            self._items_by_id = {}
            self._images = {}
            return self._fetch_inventory()

    def _transaction_lock(self, item_id: str) -> threading.Lock:
        with self._transaction_locks_guard:
            lock = self._transaction_locks.get(item_id)
            if lock is None:
                lock = threading.Lock()
                self._transaction_locks[item_id] = lock
            return lock

    def get_item(self, item_id: str) -> dict | None:
        with self._lock:
            if self._inventory is None:
                self._fetch_inventory()
            return self._items_by_id.get(item_id)

    def load_transactions(self, item_id: str) -> list[dict[str, str]]:
        with self._lock:
            if item_id in self._transactions:
                return self._transactions[item_id]

        content = self._google.read_text_file(
            self._transactions_folder_id,
            f"{item_id}.csv",
        )
        rows = parse_transactions_csv(content) if content else []

        with self._lock:
            self._transactions[item_id] = rows
            return rows

    def load_item_state(self, item_id: str, on_date: date):
        return replay_actions(self.load_transactions(item_id), on_date)

    def append_transaction(self, item_id: str, row: dict[str, str]) -> None:
        with self._transaction_lock(item_id):
            rows = self.load_transactions(item_id)
            existing_csv = serialize_transactions_csv(rows) if rows else None
            try:
                new_csv = append_row_to_csv(existing_csv, row)
            except TransactionError as exc:
                raise StorageError(f"Invalid transaction row for {item_id}") from exc

            new_rows = parse_transactions_csv(new_csv)
            filename = f"{item_id}.csv"

            self._google.put_text_file(
                self._transactions_folder_id,
                filename,
                new_csv,
                lock_key=item_id,
                mimetype="text/csv",
            )

            with self._lock:
                self._transactions[item_id] = new_rows

    def get_image_bytes(self, filename: str) -> tuple[bytes, str]:
        with self._lock:
            cached = self._images.get(filename)
            if cached is not None:
                return cached

        data = self._google.read_bytes_file(self._images_folder_id, filename)
        mime_type, _ = mimetypes.guess_type(filename)
        result = (data, mime_type or "application/octet-stream")

        with self._lock:
            self._images[filename] = result
            return result


def get_repository() -> SoundcheckRepository:
    global _repository
    if _repository is None:
        _repository = SoundcheckRepository.from_env()
    return _repository
