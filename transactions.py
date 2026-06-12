"""Per-item transaction logs and derived loan/condition state."""

import csv
import io
import secrets
from dataclasses import dataclass, field
from datetime import date, datetime

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


ACTION_LABELS = {
    "checkout": "Check out",
    "checkin": "Check in",
    "change_condition": "Change condition",
    "reserve": "Reserve",
    "cancel_reservation": "Cancel reservation",
}


def is_past_due(state: ItemState, on_date: date) -> bool:
    if state.custody != "checked_out" or state.projected_return_date is None:
        return False
    return state.projected_return_date < on_date


def custody_label(state: ItemState, on_date: date) -> str:
    if state.custody == "checked_out":
        if state.name:
            label = f"Checked out — {state.name}"
        else:
            label = "Checked out"
        if is_past_due(state, on_date):
            label += " — past due"
        return label
    return "Available"


def item_state_dict(state: ItemState, on_date: date) -> dict:
    reservations = sorted(state.reservations.values(), key=lambda r: r.reserve_start)
    past_due = is_past_due(state, on_date)
    return {
        "custody": state.custody,
        "custody_label": custody_label(state, on_date),
        "is_past_due": past_due,
        "condition": state.condition,
        "condition_label": condition_label(state.condition),
        "condition_description": state.condition_description,
        "borrower_name": state.name,
        "borrower_kerberos": state.kerberos,
        "projected_return_date": (
            state.projected_return_date.isoformat()
            if state.projected_return_date
            else None
        ),
        "reservations": [
            {
                "reservation_id": r.reservation_id,
                "reserve_start": r.reserve_start.isoformat(),
                "reserve_end": r.reserve_end.isoformat(),
                "name": r.name,
                "kerberos": r.kerberos,
            }
            for r in reservations
        ],
        "has_reservation": bool(reservations),
    }


def transaction_detail(row: dict[str, str]) -> str:
    action = row["action"]
    if action == "checkout":
        return (
            f"{row['name']} ({row['kerberos']}), "
            f"return by {row['projected_return_date']}"
        )
    if action in ("checkin", "change_condition"):
        text = f"{row['name']} ({row['kerberos']}), {condition_label(row['condition'])}"
        if row["condition"] != "ok" and row["condition_description"]:
            text += f" — {row['condition_description']}"
        return text
    if action == "reserve":
        return (
            f"{row['name']} ({row['kerberos']}), "
            f"{row['reserve_start']} to {row['reserve_end']}, id {row['reservation_id']}"
        )
    if action == "cancel_reservation":
        return f"Reservation {row['reservation_id']}"
    return ""


def history_for_display(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        {
            "timestamp": row["timestamp"],
            "action": row["action"],
            "action_label": ACTION_LABELS.get(row["action"], row["action"]),
            "detail": transaction_detail(row),
        }
        for row in rows
    ]


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


def _normalize_row(row: dict[str, str]) -> dict[str, str]:
    return {column: (row.get(column) or "").strip() for column in TRANSACTION_COLUMNS}


def parse_transactions_csv(text: str) -> list[dict[str, str]]:
    if not text.strip():
        return []

    rows: list[dict[str, str]] = []
    reader = csv.DictReader(io.StringIO(text))
    _validate_header(reader.fieldnames)

    for line_number, row in enumerate(reader, start=2):
        _validate_row(row, line_number)
        rows.append(_normalize_row(row))

    return rows


def serialize_transactions_csv(rows: list[dict[str, str]]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=TRANSACTION_COLUMNS)
    writer.writeheader()
    for row in rows:
        writer.writerow(_normalize_row(row))
    return buffer.getvalue()


def append_row_to_csv(existing: str | None, row: dict[str, str]) -> str:
    normalized = _normalize_row(row)
    _validate_row(normalized)

    if not existing or not existing.strip():
        return serialize_transactions_csv([normalized])

    rows = parse_transactions_csv(existing)
    rows.append(normalized)
    return serialize_transactions_csv(rows)


def _drop_past_reservations(state: ItemState, on_date: date) -> None:
    state.reservations = {
        reservation_id: reservation
        for reservation_id, reservation in state.reservations.items()
        if reservation.reserve_end >= on_date
    }


def replay_actions(rows: list[dict[str, str]], on_date: date) -> ItemState:
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

    _drop_past_reservations(state, on_date)
    return state


def load_item_state(transactions: list[dict[str, str]], on_date: date) -> ItemState:
    return replay_actions(transactions, on_date)


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


def _kerberos_matches(stored: str, provided: str) -> bool:
    return stored.strip().lower() == provided.strip().lower()


def validate_checkout(
    state: ItemState,
    projected_return: date,
    on_date: date,
    kerberos: str,
) -> None:
    if state.custody == "checked_out":
        raise TransactionError("Item is already checked out.")

    if projected_return < on_date:
        raise TransactionError("Projected return date must be on or after today.")

    for reservation in state.reservations.values():
        if not dates_overlap(
            on_date,
            projected_return,
            reservation.reserve_start,
            reservation.reserve_end,
        ):
            continue
        if _kerberos_matches(reservation.kerberos, kerberos):
            continue
        raise TransactionError(
            "Cannot check out: checkout dates overlap a reservation held by "
            f"{reservation.name} ({reservation.kerberos}), "
            f"{reservation.reserve_start.isoformat()} through "
            f"{reservation.reserve_end.isoformat()}."
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


def empty_transaction_row() -> dict[str, str]:
    return {column: "" for column in TRANSACTION_COLUMNS}


def item_capabilities(state: ItemState, on_date: date) -> dict[str, bool]:
    return {
        "can_checkout": state.custody != "checked_out",
        "reserved_today": reservation_on_date(state.reservations, on_date)
        is not None,
        "can_checkin": state.custody == "checked_out",
        "can_change_condition": True,
        "can_reserve": True,
        "can_cancel_reservation": bool(state.reservations),
    }
