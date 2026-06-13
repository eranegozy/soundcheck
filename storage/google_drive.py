"""Google Drive and Sheets API client."""

import io
import ssl
import threading
from collections.abc import Callable
from dataclasses import dataclass

import google.auth
from google.auth.exceptions import DefaultCredentialsError
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

SCOPES = (
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets.readonly",
)

MAX_WRITE_RETRIES = 5
DRIVE_API_RETRIES = 3


class StorageError(Exception):
    """Raised when Google API operations fail."""


class ConcurrentUpdateError(Exception):
    """Raised when a file changed between read and write."""


@dataclass(frozen=True)
class _DriveFile:
    file_id: str | None
    name: str
    md5_checksum: str | None


class GoogleStorage:
    def __init__(self) -> None:
        self._credentials_obj = None
        self._drive = None
        self._sheets = None
        self._drive_api_lock = threading.Lock()
        self._write_locks: dict[str, threading.Lock] = {}
        self._write_locks_guard = threading.Lock()

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
                "My Drive folder. Use a Shared drive folder and add the service "
                "account as Content manager (or Contributor)."
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

    def _write_lock(self, key: str) -> threading.Lock:
        with self._write_locks_guard:
            lock = self._write_locks.get(key)
            if lock is None:
                lock = threading.Lock()
                self._write_locks[key] = lock
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

    def _read_file_meta(
        self, folder_id: str, filename: str, *, for_update: bool = False
    ) -> tuple[_DriveFile, str | None]:
        files = self._find_files(folder_id, filename)
        if not files:
            return _DriveFile(file_id=None, name=filename, md5_checksum=None), None
        file_id = files[0]["id"]
        md5_checksum = self._file_md5_checksum(file_id) if for_update else None
        content = self._download_bytes(file_id).decode("utf-8")
        return _DriveFile(file_id, filename, md5_checksum), content

    def _create_file(
        self, parent_id: str, name: str, content: str, *, mimetype: str
    ) -> None:
        media = MediaIoBaseUpload(
            io.BytesIO(content.encode("utf-8")),
            mimetype=mimetype,
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
        self,
        file_id: str,
        expected_md5: str | None,
        content: str,
        *,
        mimetype: str,
    ) -> None:
        if expected_md5 is not None:
            current_md5 = self._file_md5_checksum(file_id)
            if current_md5 != expected_md5:
                raise ConcurrentUpdateError()

        media = MediaIoBaseUpload(
            io.BytesIO(content.encode("utf-8")),
            mimetype=mimetype,
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

    def read_sheet_values(self, spreadsheet_id: str, range_name: str) -> list[list[str]]:
        try:
            request = (
                self._sheets_service()
                .spreadsheets()
                .values()
                .get(
                    spreadsheetId=spreadsheet_id,
                    range=range_name,
                )
            )
            response = self._drive_execute(request)
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
            raise StorageError(
                self._drive_error_message(
                    exc,
                    f"Sheets read failed for spreadsheet {spreadsheet_id!r}",
                )
            ) from exc
        return response.get("values", [])

    def read_text_file(self, folder_id: str, filename: str) -> str | None:
        _, content = self._read_file_meta(folder_id, filename)
        return content

    def read_bytes_file(self, folder_id: str, filename: str) -> bytes:
        files = self._find_files(folder_id, filename)
        if not files:
            raise StorageError(f"File not found in Drive: {filename!r}")
        return self._download_bytes(files[0]["id"])

    def write_text_file(
        self,
        folder_id: str,
        filename: str,
        transform: Callable[[str | None], str],
        *,
        lock_key: str | None = None,
        mimetype: str = "text/plain",
    ) -> None:
        key = lock_key or f"{folder_id}/{filename}"
        with self._write_lock(key):
            for _ in range(MAX_WRITE_RETRIES):
                file_meta, content = self._read_file_meta(
                    folder_id, filename, for_update=True
                )
                new_content = transform(content)
                if file_meta.file_id is None:
                    self._create_file(
                        folder_id,
                        filename,
                        new_content,
                        mimetype=mimetype,
                    )
                    return
                try:
                    self._update_file(
                        file_meta.file_id,
                        file_meta.md5_checksum,
                        new_content,
                        mimetype=mimetype,
                    )
                    return
                except ConcurrentUpdateError:
                    continue
            raise StorageError(
                f"Concurrent update conflict while writing {filename!r}"
            )
