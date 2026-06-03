"""Per-item transaction logs and derived loan/condition state."""

import csv
import secrets
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"
DATE_FORMAT = "%Y-%m-%d"

ACTIONS = frozenset(
    {
        "checkout",
        "checkin",
        "change_condition",
        "reserve",
        "cancel_reservation",
    }
)

CONDITIONS = frozenset({"ok", "component_missing", "broken"})

TRANSACTION_COLUMNS = (
    "timestamp",
    "action",
    "name",
    "kerberos",
    "projected_return_date",
    "condition",
    "condition_description",
    "reservation_id",
    "reserve_start",
    "reserve_end",
)


class TransactionError(Exception):
    """Raised when transaction data or operations are invalid."""


@dataclass
class Reservation:
    reservation_id: str
    reserve_start: date
    reserve_end: date
    name: str
    kerberos: str


@dataclass
class ItemState:
    custody: str = "available"
    name: str | None = None
    kerberos: str | None = None
    projected_return_date: date | None = None
    condition: str = "ok"
    condition_description: str | None = None
    reservations: dict[str, Reservation] = field(default_factory=dict)


def transactions_dir(data_dir: Path) -> Path:
    return data_dir / "transactions"


def transaction_path(data_dir: Path, item_id: str) -> Path:
    return transactions_dir(data_dir) / f"{item_id}.csv"


def local_timestamp(when: datetime | None = None) -> str:
    moment = when or datetime.now()
    return moment.strftime(TIMESTAMP_FORMAT)


def parse_timestamp(value: str) -> datetime:
    return datetime.strptime(value.strip(), TIMESTAMP_FORMAT)


def parse_date(value: str, field_name: str) -> date:
    try:
        return datetime.strptime(value.strip(), DATE_FORMAT).date()
    except ValueError as exc:
        raise TransactionError(f"Invalid date for {field_name}: {value!r}") from exc


def condition_label(condition: str) -> str:
    return {
        "ok": "OK",
        "component_missing": "Component missing",
        "broken": "Broken",
    }.get(condition, condition)


def generate_reservation_id(when: datetime | None = None) -> str:
    moment = when or datetime.now()
    suffix = secrets.token_hex(3)
    return f"res-{moment.strftime('%Y%m%d')}-{suffix}"


def _validate_header(fieldnames: list[str] | None) -> None:
    if not fieldnames:
        raise TransactionError("transaction file is empty or missing a header row")
    missing = set(TRANSACTION_COLUMNS) - set(fieldnames)
    if missing:
        raise TransactionError(
            "transaction file missing columns: " + ", ".join(sorted(missing))
        )


def _line_ref(line_number: int | None) -> str:
    if line_number is None:
        return "new transaction"
    return f"transaction file line {line_number}"


def _validate_row(row: dict[str, str], line_number: int | None = None) -> None:
    where = _line_ref(line_number)
    action = (row.get("action") or "").strip()
    if action not in ACTIONS:
        raise TransactionError(f"{where}: unknown action {action!r}")

    timestamp = (row.get("timestamp") or "").strip()
    if not timestamp:
        raise TransactionError(f"{where}: missing timestamp")
    try:
        parse_timestamp(timestamp)
    except ValueError as exc:
        raise TransactionError(f"{where}: invalid timestamp {timestamp!r}") from exc

    if action == "checkout":
        _require_fields(row, where, ("name", "kerberos", "projected_return_date"))
        parse_date(row["projected_return_date"], "projected_return_date")
    elif action == "checkin":
        _require_fields(row, where, ("name", "kerberos", "condition"))
        _validate_condition_row(row, where)
    elif action == "change_condition":
        _require_fields(row, where, ("name", "kerberos", "condition"))
        _validate_condition_row(row, where)
    elif action == "reserve":
        _require_fields(
            row,
            where,
            ("name", "kerberos", "reservation_id", "reserve_start", "reserve_end"),
        )
        start = parse_date(row["reserve_start"], "reserve_start")
        end = parse_date(row["reserve_end"], "reserve_end")
        if start > end:
            raise TransactionError(
                f"{where}: reserve_start must be on or before reserve_end"
            )
    elif action == "cancel_reservation":
        _require_fields(row, where, ("reservation_id",))


def _require_fields(row: dict[str, str], where: str, fields: tuple[str, ...]) -> None:
    for field_name in fields:
        if not (row.get(field_name) or "").strip():
            raise TransactionError(f"{where}: missing value for '{field_name}'")


def _validate_condition_row(row: dict[str, str], where: str) -> None:
    condition = row["condition"].strip()
    if condition not in CONDITIONS:
        raise TransactionError(f"{where}: invalid condition {condition!r}")
    description = (row.get("condition_description") or "").strip()
    if condition != "ok" and not description:
        raise TransactionError(
            f"{where}: condition_description is required when condition is not ok"
        )


def load_transactions(data_dir: Path, item_id: str) -> list[dict[str, str]]:
    path = transaction_path(data_dir, item_id)
    if not path.is_file():
        return []

    rows: list[dict[str, str]] = []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        _validate_header(reader.fieldnames)

        for line_number, row in enumerate(reader, start=2):
            _validate_row(row, line_number)
            rows.append({column: (row.get(column) or "").strip() for column in TRANSACTION_COLUMNS})

    return rows


def replay_state(rows: list[dict[str, str]]) -> ItemState:
    state = ItemState()

    for row in rows:
        action = row["action"]

        if action == "checkout":
            state.custody = "checked_out"
            state.name = row["name"]
            state.kerberos = row["kerberos"]
            state.projected_return_date = parse_date(
                row["projected_return_date"], "projected_return_date"
            )
        elif action == "checkin":
            state.custody = "available"
            state.name = None
            state.kerberos = None
            state.projected_return_date = None
            state.condition = row["condition"]
            state.condition_description = (
                row["condition_description"] or None
                if row["condition"] != "ok"
                else None
            )
        elif action == "change_condition":
            state.condition = row["condition"]
            state.condition_description = (
                row["condition_description"] or None
                if row["condition"] != "ok"
                else None
            )
        elif action == "reserve":
            state.reservations[row["reservation_id"]] = Reservation(
                reservation_id=row["reservation_id"],
                reserve_start=parse_date(row["reserve_start"], "reserve_start"),
                reserve_end=parse_date(row["reserve_end"], "reserve_end"),
                name=row["name"],
                kerberos=row["kerberos"],
            )
        elif action == "cancel_reservation":
            state.reservations.pop(row["reservation_id"], None)

    return state


def load_item_state(data_dir: Path, item_id: str) -> ItemState:
    return replay_state(load_transactions(data_dir, item_id))


def dates_overlap(start_a: date, end_a: date, start_b: date, end_b: date) -> bool:
    return start_a <= end_b and start_b <= end_a


def reservation_overlap(
    reservations: dict[str, Reservation], start: date, end: date
) -> Reservation | None:
    for reservation in reservations.values():
        if dates_overlap(start, end, reservation.reserve_start, reservation.reserve_end):
            return reservation
    return None


def reservation_on_date(
    reservations: dict[str, Reservation], when: date
) -> Reservation | None:
    return reservation_overlap(reservations, when, when)


def append_transaction(data_dir: Path, item_id: str, row: dict[str, str]) -> None:
    normalized = {column: row.get(column, "").strip() for column in TRANSACTION_COLUMNS}
    _validate_row(normalized)

    path = transaction_path(data_dir, item_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not path.exists() or path.stat().st_size == 0

    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=TRANSACTION_COLUMNS)
        if write_header:
            writer.writeheader()
        writer.writerow(normalized)


def validate_checkout(
    state: ItemState, projected_return: date, on_date: date | None = None
) -> None:
    if state.custody == "checked_out":
        raise TransactionError("Item is already checked out.")

    today = on_date or date.today()
    conflict = reservation_on_date(state.reservations, today)
    if conflict:
        raise TransactionError(
            "Cannot check out: item is reserved "
            f"{conflict.reserve_start.isoformat()} through "
            f"{conflict.reserve_end.isoformat()}."
        )


def validate_checkin(state: ItemState) -> None:
    if state.custody != "checked_out":
        raise TransactionError("Item is not checked out.")


def validate_reserve(state: ItemState, start: date, end: date) -> None:
    conflict = reservation_overlap(state.reservations, start, end)
    if conflict:
        raise TransactionError(
            f"Reservation overlaps existing reservation {conflict.reservation_id}."
        )


def validate_cancel_reservation(state: ItemState, reservation_id: str) -> None:
    if reservation_id not in state.reservations:
        raise TransactionError(f"Unknown reservation id: {reservation_id}.")
