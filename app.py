from pathlib import Path

from flask import Flask, abort, render_template, send_from_directory

from inventory import InventoryError, load_inventory

app = Flask(__name__)
DATA_DIR = Path(__file__).resolve().parent / "data"
IMAGES_DIR = DATA_DIR / "images"


@app.route("/")
def index():
    try:
        items = load_inventory(DATA_DIR)
    except InventoryError as e:
        return render_template("index.html", items=[], error=str(e)), 200

    return render_template("index.html", items=items, error=None)


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
