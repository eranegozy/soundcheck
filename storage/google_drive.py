"""Google Drive and Sheets API client."""

import io
import ssl
import threading

import google.auth
from google.auth.exceptions import DefaultCredentialsError
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload

SCOPES = (
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
)

DRIVE_API_RETRIES = 3


class StorageError(Exception):
    """Raised when Google API operations fail."""


class GoogleStorage:
    def __init__(self) -> None:
        self._credentials_obj = None
        self._drive = None
        self._sheets = None
        self._drive_api_lock = threading.Lock()

    @staticmethod
    def _http_error_message(exc: HttpError, context: str) -> str:
        detail = exc.content.decode(errors="replace").strip() if exc.content else ""
        if detail:
            return f"{context}: HTTP {exc.resp.status}: {detail}"
        return f"{context}: HTTP {exc.resp.status}"

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
                self._http_error_message(
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
            raise StorageError(
                self._http_error_message(
                    exc,
                    f"Sheets read failed for spreadsheet {spreadsheet_id!r}",
                )
            ) from exc
        return response.get("values", [])

    def batch_get_sheet_values(
        self, spreadsheet_id: str, ranges: list[str]
    ) -> list[list[list[str]]]:
        try:
            request = (
                self._sheets_service()
                .spreadsheets()
                .values()
                .batchGet(
                    spreadsheetId=spreadsheet_id,
                    ranges=ranges,
                )
            )
            response = self._drive_execute(request)
        except HttpError as exc:
            raise StorageError(
                self._http_error_message(
                    exc,
                    f"Sheets batch read failed for spreadsheet {spreadsheet_id!r}",
                )
            ) from exc

        value_ranges = response.get("valueRanges", [])
        return [value_range.get("values", []) for value_range in value_ranges]

    def append_sheet_row(
        self, spreadsheet_id: str, range_name: str, row: list[str]
    ) -> None:
        try:
            request = (
                self._sheets_service()
                .spreadsheets()
                .values()
                .append(
                    spreadsheetId=spreadsheet_id,
                    range=range_name,
                    valueInputOption="RAW",
                    insertDataOption="INSERT_ROWS",
                    body={"values": [row]},
                )
            )
            self._drive_execute(request)
        except HttpError as exc:
            raise StorageError(
                self._http_error_message(
                    exc,
                    f"Sheets append failed for range {range_name!r}",
                )
            ) from exc

    def read_bytes_file(self, folder_id: str, filename: str) -> bytes:
        files = self._find_files(folder_id, filename)
        if not files:
            raise StorageError(f"File not found in Drive: {filename!r}")
        return self._download_bytes(files[0]["id"])
