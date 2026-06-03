# Soundcheck Inventory

File-based inventory listing for equipment loans. Phase 1 is read-only: CSV inventory and a web listing.

## Setup (conda)

```bash
conda create -n soundcheck python=3.14
conda activate soundcheck
pip install -r requirements.txt
```

## Run

```bash
conda activate soundcheck
flask --app app run --debug
```

Open http://127.0.0.1:5000/

## Data layout

```
data/
  inventory.csv      # one row per item
  images/            # image files referenced by the image column
```

## inventory.csv columns

Every column is required on every row (non-empty values).

| Column | Description |
|--------|-------------|
| `item_id` | Unique key |
| `brand` | Manufacturer (e.g. Shure) |
| `model` | Model name (e.g. SM-58) |
| `number` | Copy number when multiple units share brand/model (use `1` for a single unit) |
| `serial` | Manufacturer serial on the item (use `n/a` if unknown) |
| `category` | Type (e.g. microphone) |
| `location` | Storage location |
| `components` | Semicolon-separated list (e.g. `microphone; XLR cable`) |
| `image` | Filename under `data/images/` |

**Display name** (shown in the UI, not stored in CSV):

```
{brand} {model} {number}
```

Example: `Shure SM-58 2`.

## Images

Place image files in `data/images/`. The `image` column must match the filename exactly.

If an image file is missing, the browser shows a broken image for that row. Sample data uses `placeholder.png`.

## Adding items

Edit `data/inventory.csv`, add a row, restart the Flask server (or reload in debug mode), and refresh the page.
