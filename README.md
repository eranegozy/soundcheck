# Soundcheck Inventory

Equipment inventory and loans backed by Google Sheets (inventory and transactions) and Google Drive (images).

## Setup (conda)

```bash
conda create -n soundcheck python=3.14
conda activate soundcheck
pip install -r requirements.txt
```

## Google Cloud setup

1. Create a GCP project (or use an existing one).
2. Enable **Google Drive API** and **Google Sheets API**.
3. Create a **service account** for the app.
4. Create a separate Drive folder for **images**.
5. Share the images folder with the service account as **Viewer** or Editor.
6. Create a Google Sheet with two tabs:
   - **Inventory** — same columns as [`data.example/inventory.csv`](data.example/inventory.csv)
   - **Transactions** — header row with columns listed below (can start empty except for the header)
7. Share the spreadsheet with the service account as **Editor** (required for appending transactions).
8. Upload images from [`data.example/images/`](data.example/images/) into the images folder.

### Authentication (Application Default Credentials)

The app uses [Application Default Credentials](https://cloud.google.com/docs/authentication/application-default-credentials) — not service account JSON keys.

**Local development:** impersonate the service account. You must request Drive and Sheets scopes explicitly — the default ADC login does not include them:

```bash
gcloud auth application-default login \
  --impersonate-service-account=your-sa@your-project.iam.gserviceaccount.com \
  --scopes=https://www.googleapis.com/auth/drive,https://www.googleapis.com/auth/spreadsheets
```

You need permission to impersonate the service account (typically `roles/iam.serviceAccountTokenCreator` on that service account). Drive and Sheet access still comes from sharing those resources with the **service account email**, not your user email.

**Cloud Run:** assign the service account to the Cloud Run service. The runtime provides ADC automatically; no keys or extra auth commands.

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GOOGLE_DRIVE_IMAGES_FOLDER_ID` | yes | Folder containing image files (My Drive OK; SA needs Viewer) |
| `GOOGLE_SHEET_ID` | yes | Spreadsheet ID for inventory and transactions |
| `GOOGLE_SHEET_RANGE` | no | Inventory tab range (default `Inventory!A:J`) |
| `GOOGLE_TRANSACTIONS_RANGE` | no | Transactions tab range (default `Transactions!A:K`) |
| `PUBLIC_BASE_URL` | no | Public URL for QR codes (see below) |
| `SECRET_KEY` | no | Flask session secret (set in production) |

Local example:

```bash
gcloud auth application-default login \
  --impersonate-service-account=your-sa@your-project.iam.gserviceaccount.com \
  --scopes=https://www.googleapis.com/auth/drive,https://www.googleapis.com/auth/spreadsheets

export GOOGLE_DRIVE_IMAGES_FOLDER_ID=your-images-folder-id
export GOOGLE_SHEET_ID=your-spreadsheet-id
export GOOGLE_SHEET_RANGE='Inventory!A:J'
export GOOGLE_TRANSACTIONS_RANGE='Transactions!A:K'
export PUBLIC_BASE_URL=https://your-host.example.edu
```

### Cloud Run

Assign the service account to the Cloud Run service and set `GOOGLE_DRIVE_IMAGES_FOLDER_ID`, `GOOGLE_SHEET_ID`, and optional `GOOGLE_SHEET_RANGE` / `GOOGLE_TRANSACTIONS_RANGE` as environment variables. No credential files or secrets are required for Google API auth.

Deploy:

```bash
gcloud run deploy soundcheck --source .
```

## Run locally

```bash
conda activate soundcheck
flask --app app run --debug
```

Open http://127.0.0.1:5000/

The listing page filters and sorts inventory in the browser (search, category, location). Inventory, transactions, and images are cached in memory after the first load (one Sheets `batchGet` for both tabs).

After editing the Google Sheet externally, use **Admin → Refresh inventory** on the inventory page to reload both tabs and clear cached images.

## Data layout

```
Google Sheet
  Inventory tab                  # inventory rows
  Transactions tab               # append-only log for all items
Google Drive images folder/
  {filename}                     # image files referenced by inventory

data.example/                    # committed template for column layout
  inventory.csv
  images/
```

## Inventory columns

Every column must be present in the header. All columns require a non-empty value on every row.

| Column | Description |
|--------|-------------|
| `item_id` | Unique key (must be unique across all rows) |
| `brand` | Manufacturer (e.g. Shure) |
| `model` | Model name (e.g. SM-58) |
| `number` | Copy number when multiple units share brand/model (use `1` for a single unit). The combination of brand, model, and number must be unique. |
| `serial` | Manufacturer serial on the item (use `n/a` if unknown) |
| `category` | Type (e.g. microphone) |
| `location` | Storage location (e.g. maker space) |
| `shelf` | Shelf within that location (e.g. `2A`) |
| `components` | Semicolon-separated list (e.g. `microphone; XLR cable`) |
| `image` | Filename in the Drive images folder (e.g. `sm58.png`) |

**Display name** (shown in the UI, not stored in the sheet):

```
{brand} {model} #{number}
```

**Location label** (shown on item pages and QR stickers, not stored in the sheet):

```
{location} / {shelf}
```

## Transactions tab

All items share one append-only log on the **Transactions** tab. Rows are appended at the bottom in chronological order; per-item history is shown oldest first on the item page.

Timestamps use local wall time: `YYYY-MM-DD HH:MM:SS`. Dates use `YYYY-MM-DD`.

| Column | Description |
|--------|-------------|
| `item_id` | Item this row belongs to |
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

**Derived state** (replay rows in sheet order, once per item):

- **Custody:** `checkout` checks out; `checkin` returns to available.
- **Condition:** Updated on `checkin` and `change_condition` (allowed while checked out).
- **Reservations:** `reserve` adds; `cancel_reservation` removes. Only reservations with `reserve_end` on or after today are active (past reservations are ignored). Checkout is allowed during your own reservation (matching kerberos), but the checkout period (today through projected return) cannot overlap any other active reservation.

Each transaction append writes **one row** via the Sheets API (`values.append`); the app does not rewrite the whole tab. Concurrent appends use per-item locks in the app (single-server).

## Item operations

Open an item from the inventory list. Use the forms on the item page to check out, check in, change condition, reserve, or cancel a reservation. Each action appends a row to the Transactions tab.

## Admin

On the inventory page, open **Admin** for:

- **Refresh inventory** — reload both sheet tabs and clear cached images (use after external sheet or image changes)
- **Print QR codes** — print 1.5″ × 1.5″ stickers for selected items

Each sticker shows the item name, location, components, and a QR code linking to that item's detail page. Items are listed newest-first (reverse of sheet row order).

Set `PUBLIC_BASE_URL` when deploying so QR codes point at your real host (e.g. `https://soundcheck.mit.edu`). If unset, the app uses the current request URL (fine for local dev).

## Adding items

Add a row to the inventory tab, then choose **Admin → Refresh inventory** on the inventory page.
