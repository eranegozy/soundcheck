"""Soundcheck data access: domain logic over Google storage."""

import mimetypes
import os
import threading
from datetime import date

from inventory import parse_inventory_rows
from storage import GoogleStorage, StorageError
from transactions import (
    ItemState,
    TransactionError,
    apply_action_to_state,
    parse_transaction_rows,
    replay_all_items,
    replay_actions,
    row_to_sheet_values,
    validate_and_normalize_row,
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
        images_folder_id: str,
        sheet_id: str,
        sheet_range: str,
        transactions_range: str,
    ) -> None:
        self._google = google
        self._images_folder_id = images_folder_id
        self._sheet_id = sheet_id
        self._sheet_range = sheet_range
        self._transactions_range = transactions_range

        self._lock = threading.Lock()
        self._inventory: list[dict] | None = None
        self._items_by_id: dict[str, dict] = {}
        self._transaction_rows: list[dict[str, str]] | None = None
        self._transactions_by_item: dict[str, list[dict[str, str]]] = {}
        self._item_states: dict[str, ItemState] | None = None
        self._item_states_date: date | None = None
        self._images: dict[str, tuple[bytes, str]] = {}
        self._transaction_locks: dict[str, threading.Lock] = {}
        self._transaction_locks_guard = threading.Lock()

    @classmethod
    def from_env(cls, google: GoogleStorage | None = None) -> "SoundcheckRepository":
        images_folder_id = os.environ.get("GOOGLE_DRIVE_IMAGES_FOLDER_ID", "").strip()
        sheet_id = os.environ.get("GOOGLE_SHEET_ID", "").strip()
        sheet_range = os.environ.get("GOOGLE_SHEET_RANGE", "Inventory!A:I").strip()
        transactions_range = os.environ.get(
            "GOOGLE_TRANSACTIONS_RANGE", "Transactions!A:K"
        ).strip()

        missing = [
            name
            for name, value in (
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
            images_folder_id=_normalize_drive_id(images_folder_id),
            sheet_id=sheet_id,
            sheet_range=sheet_range or "Inventory!A:I",
            transactions_range=transactions_range or "Transactions!A:K",
        )

    def _fetch_all(self) -> list[dict]:
        inventory_values, transaction_values = self._google.batch_get_sheet_values(
            self._sheet_id,
            [self._sheet_range, self._transactions_range],
        )

        items = parse_inventory_rows(inventory_values)
        transaction_rows, by_item = parse_transaction_rows(transaction_values)

        self._inventory = items
        self._items_by_id = {item["item_id"]: item for item in items}
        self._transaction_rows = transaction_rows
        self._transactions_by_item = by_item
        self._item_states = None
        self._item_states_date = None
        return items

    def _ensure_loaded(self) -> None:
        if self._inventory is None or self._transaction_rows is None:
            self._fetch_all()

    def load_inventory(self) -> list[dict]:
        with self._lock:
            if self._inventory is not None:
                return self._inventory
            return self._fetch_all()

    def refresh_inventory(self) -> list[dict]:
        with self._lock:
            self._inventory = None
            self._items_by_id = {}
            self._transaction_rows = None
            self._transactions_by_item = {}
            self._item_states = None
            self._item_states_date = None
            self._images = {}
            return self._fetch_all()

    def _transaction_lock(self, item_id: str) -> threading.Lock:
        with self._transaction_locks_guard:
            lock = self._transaction_locks.get(item_id)
            if lock is None:
                lock = threading.Lock()
                self._transaction_locks[item_id] = lock
            return lock

    def get_item(self, item_id: str) -> dict | None:
        with self._lock:
            self._ensure_loaded()
            return self._items_by_id.get(item_id)

    def load_transactions(self, item_id: str) -> list[dict[str, str]]:
        with self._lock:
            self._ensure_loaded()
            return list(self._transactions_by_item.get(item_id, []))

    def load_all_item_states(self, on_date: date) -> dict[str, ItemState]:
        with self._lock:
            self._ensure_loaded()
            if (
                self._item_states is not None
                and self._item_states_date == on_date
            ):
                return self._item_states

            assert self._transaction_rows is not None
            states = replay_all_items(self._transaction_rows, on_date)
            self._item_states = states
            self._item_states_date = on_date
            return states

    def load_item_state(self, item_id: str, on_date: date) -> ItemState:
        states = self.load_all_item_states(on_date)
        return states.get(item_id, ItemState())

    def append_transaction(self, item_id: str, row: dict[str, str]) -> None:
        with self._transaction_lock(item_id):
            with self._lock:
                self._ensure_loaded()
                existing = list(self._transactions_by_item.get(item_id, []))

            sheet_row = {**row, "item_id": item_id}
            try:
                normalized = validate_and_normalize_row(sheet_row)
                replay_actions(existing + [normalized], date.today())
            except TransactionError as exc:
                raise StorageError(f"Invalid transaction row for {item_id}") from exc

            self._google.append_sheet_row(
                self._sheet_id,
                self._transactions_range,
                row_to_sheet_values(normalized),
            )

            with self._lock:
                assert self._transaction_rows is not None
                self._transaction_rows.append(normalized)
                self._transactions_by_item.setdefault(item_id, []).append(normalized)

                if self._item_states is not None and self._item_states_date is not None:
                    state = self._item_states.get(item_id, ItemState())
                    apply_action_to_state(state, normalized, self._item_states_date)
                    self._item_states[item_id] = state

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
