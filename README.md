# Soundcheck Inventory

File-based inventory and equipment loans. Inventory is static CSV; loan history is per-item transaction files.

## Setup (conda)

```bash
conda create -n soundcheck python=3.14
conda activate soundcheck
pip install -r requirements.txt
cp -r data.example data
```

The `data/` directory is gitignored. Copy `data.example/` to `data/` before the first run (and after clone).

## Run

```bash
conda activate soundcheck
flask --app app run --debug
```

Open http://127.0.0.1:5000/

The listing page filters and sorts inventory in the browser (search, category, location). All items are loaded once from the server.

## Data layout

```
data/                          # gitignored — your local data
  inventory.csv                # one row per item
  images/                      # image files for the image column
  transactions/
    {item_id}.csv              # append-only history per item

data.example/                  # committed template — copy to data/
```

## inventory.csv columns

Every column must be present in the header. All columns except `image` require a non-empty value on every row.

| Column | Description |
|--------|-------------|
| `item_id` | Unique key (must be unique across all rows) |
| `brand` | Manufacturer (e.g. Shure) |
| `model` | Model name (e.g. SM-58) |
| `number` | Copy number when multiple units share brand/model (use `1` for a single unit). The combination of brand, model, and number must be unique. |
| `serial` | Manufacturer serial on the item (use `n/a` if unknown) |
| `category` | Type (e.g. microphone) |
| `location` | Storage location |
| `components` | Semicolon-separated list (e.g. `microphone; XLR cable`) |
| `image` | Filename under `data/images/` (leave blank to use `placeholder.png`) |

**Display name** (shown in the UI, not stored in CSV):

```
{brand} {model} {number}
```

## Transaction files

One CSV per item at `data/transactions/{item_id}.csv`. Rows are appended at the bottom; history is shown oldest first.

Timestamps use local wall time: `YYYY-MM-DD HH:MM:SS`. Dates use `YYYY-MM-DD`.

| Column | Description |
|--------|-------------|
| `timestamp` | Required on every row |
| `action` | `checkout`, `checkin`, `change_condition`, `reserve`, `cancel_reservation` |
| `name` | Person (borrower, actor, or reserver) when applicable |
| `kerberos` | Kerberos ID when `name` is set |
| `projected_return_date` | Checkout only |
| `condition` | `ok`, `component_missing`, or `broken` (checkin, change_condition) |
| `condition_description` | Required when `condition` is not `ok` |
| `reservation_id` | Set by the app on `reserve`; referenced on `cancel_reservation` |
| `reserve_start` | Reservation start date |
| `reserve_end` | Reservation end date |

**Derived state** (replay rows in order):

- **Custody:** `checkout` checks out; `checkin` returns to available.
- **Condition:** Updated on `checkin` and `change_condition` (allowed while checked out).
- **Reservations:** `reserve` adds; `cancel_reservation` removes. Only reservations with `reserve_end` on or after today are active (past reservations are ignored). Checkout is blocked if today overlaps an active reservation.

## Item operations

Open an item from the inventory list. Use the forms on the item page to check out, check in, change condition, reserve, or cancel a reservation. Each action appends a row to that item's transaction file.

## Adding items

Edit `data/inventory.csv`, add a row, restart the Flask server (or reload in debug mode), and refresh the page.
