"""Google Drive and Sheets storage backend."""

import io
import mimetypes
import os
import ssl
import threading
from dataclasses import dataclass
from datetime import date

import google.auth
from google.auth.exceptions import DefaultCredentialsError
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

from inventory import InventoryError, get_item, parse_inventory_rows
from transactions import (
    append_row_to_csv,
    parse_transactions_csv,
    replay_actions,
)

SCOPES = (
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets.readonly",
)

MAX_APPEND_RETRIES = 5
DRIVE_API_RETRIES = 3


class StorageError(Exception):
    """Raised when storage operations fail."""


class ConcurrentUpdateError(Exception):
    """Raised when a transaction file changed between read and write."""


def _normalize_drive_id(value: str) -> str:
    """Accept a bare folder ID or a full Drive folder URL."""
    value = value.strip()
    if "/folders/" in value:
        return value.split("/folders/", 1)[1].split("/")[0].split("?")[0]
    return value


@dataclass(frozen=True)
class _DriveFile:
    file_id: str | None
    name: str
    md5_checksum: str | None


class GoogleDriveStore:
    def __init__(
        self,
        *,
        transactions_folder_id: str,
        images_folder_id: str,
        sheet_id: str,
        sheet_range: str,
    ) -> None:
        self._transactions_folder_id = transactions_folder_id
        self._images_folder_id = images_folder_id
        self._sheet_id = sheet_id
        self._sheet_range = sheet_range

        self._credentials_obj = None
        self._drive = None
        self._sheets = None
        self._drive_api_lock = threading.Lock()
        self._item_locks: dict[str, threading.Lock] = {}
        self._item_locks_guard = threading.Lock()

    @classmethod
    def from_env(cls) -> GoogleDriveStore:
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
            transactions_folder_id=_normalize_drive_id(transactions_folder_id),
            images_folder_id=_normalize_drive_id(images_folder_id),
            sheet_id=sheet_id,
            sheet_range=sheet_range or "Inventory!A:I",
        )

    @staticmethod
    def _drive_error_message(exc: HttpError, context: str) -> str:
        detail = ""
        if exc.content:
            detail = exc.content.decode(errors="replace").strip()
        if "storageQuotaExceeded" in detail or (
            "do not have storage quota" in detail.lower()
        ):
            return (
                f"{context}: service accounts cannot create new files in a personal "
                "My Drive folder. Put GOOGLE_DRIVE_TRANSACTIONS_FOLDER_ID in a "
                "Shared drive and add the service account as Content manager (or "
                "Contributor). See README Google Cloud setup."
            )
        parts = [context, f"HTTP {exc.resp.status}"]
        if detail:
            parts.append(detail)
        return ": ".join(parts)

    def _credentials(self):
        if self._credentials_obj is None:
            try:
                credentials, _project = google.auth.default(scopes=SCOPES)
            except DefaultCredentialsError as exc:
                raise StorageError(
                    "Application Default Credentials not found. Run "
                    "'gcloud auth application-default login' locally, or "
                    "attach a service account to Cloud Run."
                ) from exc
            self._credentials_obj = credentials
        return self._credentials_obj

    def _drive_service(self):
        if self._drive is None:
            self._drive = build(
                "drive",
                "v3",
                credentials=self._credentials(),
                cache_discovery=False,
            )
        return self._drive

    def _sheets_service(self):
        if self._sheets is None:
            self._sheets = build(
                "sheets",
                "v4",
                credentials=self._credentials(),
                cache_discovery=False,
            )
        return self._sheets

    def _item_lock(self, item_id: str) -> threading.Lock:
        with self._item_locks_guard:
            lock = self._item_locks.get(item_id)
            if lock is None:
                lock = threading.Lock()
                self._item_locks[item_id] = lock
            return lock

    def _drive_execute(self, request):
        last_exc: Exception | None = None
        for attempt in range(DRIVE_API_RETRIES):
            try:
                with self._drive_api_lock:
                    return request.execute()
            except HttpError:
                raise
            except (ssl.SSLError, OSError) as exc:
                last_exc = exc
                if attempt + 1 >= DRIVE_API_RETRIES:
                    raise StorageError(f"Drive request failed: {exc}") from exc
        raise StorageError(f"Drive request failed: {last_exc}")

    def _escape_query_value(self, value: str) -> str:
        return value.replace("\\", "\\\\").replace("'", "\\'")

    def _find_files(self, parent_id: str, name: str) -> list[dict]:
        query = (
            f"name='{self._escape_query_value(name)}' "
            f"and '{parent_id}' in parents and trashed=false"
        )
        try:
            request = (
                self._drive_service()
                .files()
                .list(
                    q=query,
                    fields="files(id,name,mimeType)",
                    pageSize=10,
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                    corpora="allDrives",
                )
            )
            response = self._drive_execute(request)
        except HttpError as exc:
            raise StorageError(
                self._drive_error_message(
                    exc,
                    f"Drive list failed for {name!r} under folder {parent_id!r}",
                )
            ) from exc
        return response.get("files", [])

    def _download_bytes(self, file_id: str) -> bytes:
        last_exc: Exception | None = None
        for attempt in range(DRIVE_API_RETRIES):
            try:
                with self._drive_api_lock:
                    request = self._drive_service().files().get_media(
                        fileId=file_id,
                        supportsAllDrives=True,
                    )
                    buffer = io.BytesIO()
                    downloader = MediaIoBaseDownload(buffer, request)
                    done = False
                    while not done:
                        _, done = downloader.next_chunk()
                    return buffer.getvalue()
            except HttpError:
                raise
            except (ssl.SSLError, OSError) as exc:
                last_exc = exc
                if attempt + 1 >= DRIVE_API_RETRIES:
                    raise StorageError(f"Drive download failed: {exc}") from exc
        raise StorageError(f"Drive download failed: {last_exc}")

    def _file_md5_checksum(self, file_id: str) -> str | None:
        request = self._drive_service().files().get(
            fileId=file_id,
            fields="md5Checksum",
            supportsAllDrives=True,
        )
        result = self._drive_execute(request)
        return result.get("md5Checksum")

    def _download_transaction_csv(
        self, item_id: str, *, for_update: bool = False
    ) -> tuple[_DriveFile, str | None]:
        filename = f"{item_id}.csv"
        files = self._find_files(self._transactions_folder_id, filename)
        if not files:
            return _DriveFile(file_id=None, name=filename, md5_checksum=None), None
        file_id = files[0]["id"]
        md5_checksum = self._file_md5_checksum(file_id) if for_update else None
        content = self._download_bytes(file_id).decode("utf-8")
        return _DriveFile(file_id, filename, md5_checksum), content

    def _create_file(self, parent_id: str, name: str, content: str) -> None:
        media = MediaIoBaseUpload(
            io.BytesIO(content.encode("utf-8")),
            mimetype="text/csv",
            resumable=False,
        )
        body = {"name": name, "parents": [parent_id]}
        try:
            request = self._drive_service().files().create(
                body=body,
                media_body=media,
                fields="id",
                supportsAllDrives=True,
            )
            self._drive_execute(request)
        except HttpError as exc:
            raise StorageError(
                self._drive_error_message(
                    exc,
                    f"Drive create failed for {name!r}",
                )
            ) from exc

    def _update_file(
        self, file_id: str, expected_md5: str | None, content: str
    ) -> None:
        if expected_md5 is not None:
            current_md5 = self._file_md5_checksum(file_id)
            if current_md5 != expected_md5:
                raise ConcurrentUpdateError()

        media = MediaIoBaseUpload(
            io.BytesIO(content.encode("utf-8")),
            mimetype="text/csv",
            resumable=False,
        )
        request = self._drive_service().files().update(
            fileId=file_id,
            media_body=media,
            fields="id",
            supportsAllDrives=True,
        )
        try:
            self._drive_execute(request)
        except HttpError as exc:
            raise StorageError(
                self._drive_error_message(
                    exc,
                    f"Drive update failed for file {file_id}",
                )
            ) from exc

    def load_inventory(self) -> list[dict]:
        try:
            response = (
                self._sheets_service()
                .spreadsheets()
                .values()
                .get(
                    spreadsheetId=self._sheet_id,
                    range=self._sheet_range,
                )
                .execute()
            )
        except HttpError as exc:
            if exc.resp.status == 403 and "ACCESS_TOKEN_SCOPE_INSUFFICIENT" in (
                exc.content.decode() if exc.content else ""
            ):
                raise StorageError(
                    "Google Sheets access denied: ADC token lacks required scopes. "
                    "Re-run gcloud auth application-default login with "
                    "--scopes=https://www.googleapis.com/auth/drive,"
                    "https://www.googleapis.com/auth/spreadsheets.readonly"
                ) from exc
            raise StorageError("Failed to load inventory from Google Sheet") from exc

        values = response.get("values", [])
        try:
            return parse_inventory_rows(values)
        except InventoryError:
            raise

    def get_item(self, item_id: str) -> dict | None:
        return get_item(self.load_inventory(), item_id)

    def load_transactions(self, item_id: str) -> list[dict[str, str]]:
        _, content = self._download_transaction_csv(item_id)
        if content is None:
            return []
        return parse_transactions_csv(content)

    def load_item_state(self, item_id: str, on_date: date):
        return replay_actions(self.load_transactions(item_id), on_date)

    def append_transaction(self, item_id: str, row: dict[str, str]) -> None:
        with self._item_lock(item_id):
            for _ in range(MAX_APPEND_RETRIES):
                file_meta, content = self._download_transaction_csv(
                    item_id, for_update=True
                )
                try:
                    new_content = append_row_to_csv(content, row)
                except Exception as exc:
                    raise StorageError(
                        f"Invalid transaction row for {item_id}"
                    ) from exc

                if file_meta.file_id is None:
                    self._create_file(
                        self._transactions_folder_id,
                        file_meta.name,
                        new_content,
                    )
                    return

                try:
                    self._update_file(
                        file_meta.file_id, file_meta.md5_checksum, new_content
                    )
                    return
                except ConcurrentUpdateError:
                    continue

            raise StorageError(
                f"Concurrent update conflict while appending transaction for {item_id}"
            )

    def get_image_bytes(self, filename: str) -> tuple[bytes, str]:
        files = self._find_files(self._images_folder_id, filename)
        if not files:
            raise StorageError(f"Image not found in Drive: {filename}")

        file_id = files[0]["id"]
        data = self._download_bytes(file_id)
        mime_type, _ = mimetypes.guess_type(filename)
        return data, mime_type or "application/octet-stream"
