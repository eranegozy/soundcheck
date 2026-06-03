from pathlib import Path

from flask import Flask, abort, render_template, send_from_directory, url_for

from inventory import InventoryError, get_item, load_inventory
from transactions import (
    TransactionError,
    history_for_display,
    item_state_dict,
    load_item_state,
    load_transactions,
)

app = Flask(__name__)
DATA_DIR = Path(__file__).resolve().parent / "data"
IMAGES_DIR = DATA_DIR / "images"


def enrich_item(item: dict) -> dict:
    state = load_item_state(DATA_DIR, item["item_id"])
    return {
        **item,
        **item_state_dict(state),
        "item_url": url_for("item_detail", item_id=item["item_id"]),
    }


@app.route("/")
def index():
    try:
        items = [enrich_item(item) for item in load_inventory(DATA_DIR)]
    except (InventoryError, TransactionError) as e:
        return render_template("index.html", items=[], error=str(e)), 200

    return render_template("index.html", items=items, error=None)


@app.route("/items/<item_id>")
def item_detail(item_id: str):
    try:
        item = get_item(DATA_DIR, item_id)
        if item is None:
            abort(404)
        state = load_item_state(DATA_DIR, item_id)
        transactions = load_transactions(DATA_DIR, item_id)
    except InventoryError as e:
        return render_template("item.html", item=None, error=str(e)), 200
    except TransactionError as e:
        return render_template(
            "item.html",
            item=item,
            error=str(e),
            status=None,
            history=[],
        ), 200

    return render_template(
        "item.html",
        item=item,
        error=None,
        status=item_state_dict(state),
        history=history_for_display(transactions),
    )


@app.route("/images/<path:filename>")
def serve_image(filename: str):
    if ".." in filename or filename.startswith("/"):
        abort(404)

    safe_path = (IMAGES_DIR / filename).resolve()
    if not safe_path.is_file() or IMAGES_DIR.resolve() not in safe_path.parents:
        abort(404)

    return send_from_directory(IMAGES_DIR, filename)


if __name__ == "__main__":
    app.run(debug=True)
