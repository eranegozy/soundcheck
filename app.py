import os
from datetime import date

from flask import (
    Flask,
    Response,
    abort,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)

from inventory import InventoryError
from repository import get_repository
from stickers import sticker_payload
from storage import StorageError
from transactions import (
    TransactionError,
    empty_transaction_row,
    generate_reservation_id,
    history_for_display,
    item_capabilities,
    item_state_dict,
    local_timestamp,
    parse_date,
    validate_cancel_reservation,
    validate_checkin,
    validate_checkout,
    validate_reserve,
    CONDITIONS,
    condition_label,
)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key")

repo = get_repository()

CONDITION_CHOICES = [
    ("ok", condition_label("ok")),
    ("component_missing", condition_label("component_missing")),
    ("broken", condition_label("broken")),
]


def enrich_item(item: dict, on_date: date) -> dict:
    state = repo.load_item_state(item["item_id"], on_date)
    return {
        **item,
        **item_state_dict(state, on_date),
        "item_url": url_for("item_detail", item_id=item["item_id"]),
    }


def _public_base_url() -> str:
    return os.environ.get("PUBLIC_BASE_URL", request.url_root).rstrip("/")


def _public_item_url(item_id: str) -> str:
    return f"{_public_base_url()}{url_for('item_detail', item_id=item_id)}"


def _require_item(item_id: str) -> dict:
    item = repo.get_item(item_id)
    if item is None:
        abort(404)
    return item


def _render_item_page(item_id: str, on_date: date):
    item = repo.get_item(item_id)
    if item is None:
        abort(404)
    state = repo.load_item_state(item_id, on_date)
    transactions = repo.load_transactions(item_id)
    return render_template(
        "item.html",
        item=item,
        error=None,
        status=item_state_dict(state, on_date),
        capabilities=item_capabilities(state, on_date),
        history=history_for_display(transactions),
        condition_choices=CONDITION_CHOICES,
    )


@app.route("/")
def index():
    try:
        on_date = date.today()
        items = [enrich_item(item, on_date) for item in repo.load_inventory()]
    except (InventoryError, TransactionError, StorageError) as e:
        return render_template("index.html", items=[], error=str(e)), 200

    return render_template("index.html", items=items, error=None)


@app.route("/items/<item_id>")
def item_detail(item_id: str):
    try:
        return _render_item_page(item_id, date.today())
    except InventoryError as e:
        return render_template("item.html", item=None, error=str(e)), 200
    except (TransactionError, StorageError) as e:
        item = repo.get_item(item_id)
        return render_template(
            "item.html",
            item=item,
            error=str(e),
            status=None,
            capabilities=None,
            history=[],
            condition_choices=CONDITION_CHOICES,
        ), 200


@app.post("/items/<item_id>/checkout")
def checkout(item_id: str):
    _require_item(item_id)
    name = request.form.get("name", "").strip()
    kerberos = request.form.get("kerberos", "").strip()
    return_date_raw = request.form.get("projected_return_date", "").strip()

    try:
        if not name or not kerberos or not return_date_raw:
            raise TransactionError("Name, kerberos, and projected return date are required.")
        projected_return = parse_date(return_date_raw, "projected_return_date")
        on_date = date.today()
        state = repo.load_item_state(item_id, on_date)
        validate_checkout(state, projected_return, on_date, kerberos)

        row = empty_transaction_row()
        row.update(
            {
                "timestamp": local_timestamp(),
                "action": "checkout",
                "name": name,
                "kerberos": kerberos,
                "projected_return_date": projected_return.isoformat(),
            }
        )
        repo.append_transaction(item_id, row)
        flash("Item checked out.", "success")
    except (InventoryError, TransactionError, StorageError) as e:
        flash(str(e), "error")

    return redirect(url_for("item_detail", item_id=item_id))


@app.post("/items/<item_id>/checkin")
def checkin(item_id: str):
    _require_item(item_id)
    name = request.form.get("name", "").strip()
    kerberos = request.form.get("kerberos", "").strip()
    condition = request.form.get("condition", "").strip()
    description = request.form.get("condition_description", "").strip()
    if condition == "ok":
        description = ""

    try:
        if not name or not kerberos or not condition:
            raise TransactionError("Name, kerberos, and condition are required.")
        if condition not in CONDITIONS:
            raise TransactionError(f"Invalid condition: {condition!r}")
        if condition != "ok" and not description:
            raise TransactionError(
                "Condition notes are required when condition is not OK."
            )

        state = repo.load_item_state(item_id, date.today())
        validate_checkin(state)

        row = empty_transaction_row()
        row.update(
            {
                "timestamp": local_timestamp(),
                "action": "checkin",
                "name": name,
                "kerberos": kerberos,
                "condition": condition,
                "condition_description": description,
            }
        )
        repo.append_transaction(item_id, row)
        flash("Item checked in.", "success")
    except (InventoryError, TransactionError, StorageError) as e:
        flash(str(e), "error")

    return redirect(url_for("item_detail", item_id=item_id))


@app.post("/items/<item_id>/change-condition")
def change_condition(item_id: str):
    _require_item(item_id)
    name = request.form.get("name", "").strip()
    kerberos = request.form.get("kerberos", "").strip()
    condition = request.form.get("condition", "").strip()
    description = request.form.get("condition_description", "").strip()
    if condition == "ok":
        description = ""

    try:
        if not name or not kerberos or not condition:
            raise TransactionError("Name, kerberos, and condition are required.")
        if condition not in CONDITIONS:
            raise TransactionError(f"Invalid condition: {condition!r}")
        if condition != "ok" and not description:
            raise TransactionError(
                "Condition notes are required when condition is not OK."
            )

        row = empty_transaction_row()
        row.update(
            {
                "timestamp": local_timestamp(),
                "action": "change_condition",
                "name": name,
                "kerberos": kerberos,
                "condition": condition,
                "condition_description": description,
            }
        )
        repo.append_transaction(item_id, row)
        flash("Condition updated.", "success")
    except (InventoryError, TransactionError, StorageError) as e:
        flash(str(e), "error")

    return redirect(url_for("item_detail", item_id=item_id))


@app.post("/items/<item_id>/reserve")
def reserve(item_id: str):
    _require_item(item_id)
    name = request.form.get("name", "").strip()
    kerberos = request.form.get("kerberos", "").strip()
    start_raw = request.form.get("reserve_start", "").strip()
    end_raw = request.form.get("reserve_end", "").strip()

    try:
        if not name or not kerberos or not start_raw or not end_raw:
            raise TransactionError(
                "Name, kerberos, and reservation dates are required."
            )
        reserve_start = parse_date(start_raw, "reserve_start")
        reserve_end = parse_date(end_raw, "reserve_end")
        if reserve_start > reserve_end:
            raise TransactionError("Reserve start must be on or before reserve end.")

        state = repo.load_item_state(item_id, date.today())
        validate_reserve(state, reserve_start, reserve_end)

        reservation_id = generate_reservation_id()
        row = empty_transaction_row()
        row.update(
            {
                "timestamp": local_timestamp(),
                "action": "reserve",
                "name": name,
                "kerberos": kerberos,
                "reservation_id": reservation_id,
                "reserve_start": reserve_start.isoformat(),
                "reserve_end": reserve_end.isoformat(),
            }
        )
        repo.append_transaction(item_id, row)
        flash(f"Reservation created ({reservation_id}).", "success")
    except (InventoryError, TransactionError, StorageError) as e:
        flash(str(e), "error")

    return redirect(url_for("item_detail", item_id=item_id))


@app.post("/items/<item_id>/cancel-reservation")
def cancel_reservation(item_id: str):
    _require_item(item_id)
    reservation_id = request.form.get("reservation_id", "").strip()

    try:
        if not reservation_id:
            raise TransactionError("Reservation id is required.")
        state = repo.load_item_state(item_id, date.today())
        validate_cancel_reservation(state, reservation_id)

        row = empty_transaction_row()
        row.update(
            {
                "timestamp": local_timestamp(),
                "action": "cancel_reservation",
                "reservation_id": reservation_id,
            }
        )
        repo.append_transaction(item_id, row)
        flash("Reservation cancelled.", "success")
    except (InventoryError, TransactionError, StorageError) as e:
        flash(str(e), "error")

    return redirect(url_for("item_detail", item_id=item_id))


@app.route("/admin/print-qr")
def admin_print_qr():
    try:
        items = list(reversed(repo.load_inventory()))
    except (InventoryError, StorageError) as e:
        return render_template(
            "admin_print_qr.html",
            stickers=[],
            error=str(e),
            public_base_url=_public_base_url(),
        ), 200

    stickers = [
        sticker_payload(item, _public_item_url(item["item_id"])) for item in items
    ]
    return render_template(
        "admin_print_qr.html",
        stickers=stickers,
        error=None,
        public_base_url=_public_base_url(),
    )


@app.route("/images/<path:filename>")
def serve_image(filename: str):
    if ".." in filename or filename.startswith("/"):
        abort(404)

    try:
        data, mime_type = repo.get_image_bytes(filename)
    except StorageError:
        abort(404)

    return Response(data, mimetype=mime_type)


if __name__ == "__main__":
    # Google Cloud Run requires the app to listen on the $PORT environment variable
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=True, port=port)
