"""Persistent storage backends."""

from storage.google_drive import GoogleDriveStore, StorageError

_store: GoogleDriveStore | None = None


def get_store() -> GoogleDriveStore:
    global _store
    if _store is None:
        _store = GoogleDriveStore.from_env()
    return _store


__all__ = ["GoogleDriveStore", "StorageError", "get_store"]
