# Soundcheck Inventory

Equipment inventory and loans backed by Google Sheets (inventory) and Google Drive (transaction logs and images).

## Setup (conda)

```bash
conda create -n soundcheck python=3.14
conda activate soundcheck
pip install -r requirements.txt
```

## Google Cloud setup

1. Create a GCP project (or use an existing one).
2. Enable **Google Drive API** and **Google Sheets API**.
3. Create a **service account** for the app (no JSON key required).
4. Create a **Shared drive** folder for transaction CSVs (required — see below). Create a separate folder for **images** (My Drive is fine for images; the app only reads them).
5. Add the service account email to the Shared drive as **Content manager** (or Contributor). Share the images folder with the service account as **Viewer** or Editor.
6. Create a Google Sheet for inventory with the same columns as [`data.example/inventory.csv`](data.example/inventory.csv). Share the sheet with the service account as **Editor** (Viewer is enough for read-only inventory).
7. Upload images from [`data.example/images/`](data.example/images/) into the images folder.
8. Optionally seed transaction CSVs in the transactions folder (one `{item_id}.csv` per item). The app creates a CSV on first checkout/checkin for an item.

### Transactions folder must be on a Shared drive

Service accounts have **no Google Drive storage quota**. They can read files shared from My Drive, but **creating** new files in My Drive fails with `storageQuotaExceeded`.

Put `GOOGLE_DRIVE_TRANSACTIONS_FOLDER_ID` in a [Shared drive](https://developers.google.com/workspace/drive/api/guides/about-shareddrives) (Google Workspace):

1. In Google Drive, open **Shared drives** → create or pick a shared drive.
2. Create a `transactions` folder inside it (or use the shared drive root).
3. **Manage members** on the shared drive → add `your-sa@project.iam.gserviceaccount.com` as **Content manager**.
4. Set `GOOGLE_DRIVE_TRANSACTIONS_FOLDER_ID` to that folder’s ID (from the URL).

The images folder can stay in My Drive if you upload images yourself; the app only downloads them.

### Authentication (Application Default Credentials)

The app uses [Application Default Credentials](https://cloud.google.com/docs/authentication/application-default-credentials) — not service account JSON keys.

**Local development:** impersonate the service account (recommended when org policy blocks key creation). You must request Drive and Sheets scopes explicitly — the default ADC login does not include them:

```bash
gcloud auth application-default login \
  --impersonate-service-account=your-sa@your-project.iam.gserviceaccount.com \
  --scopes=https://www.googleapis.com/auth/drive,https://www.googleapis.com/auth/spreadsheets.readonly
```

If you previously logged in without `--scopes`, run the command again to replace the cached credentials. A `403` with `ACCESS_TOKEN_SCOPE_INSUFFICIENT` means the token needs to be refreshed this way.

You need permission to impersonate the service account (typically `roles/iam.serviceAccountTokenCreator` on that service account). Drive and Sheet access still comes from sharing those resources with the **service account email**, not your user email.

**Cloud Run:** assign the service account to the Cloud Run service. The runtime provides ADC automatically; no keys or extra auth commands.

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GOOGLE_DRIVE_TRANSACTIONS_FOLDER_ID` | yes | Folder on a **Shared drive** for `{item_id}.csv` files (SA must be Content manager on the shared drive) |
| `GOOGLE_DRIVE_IMAGES_FOLDER_ID` | yes | Folder containing image files (My Drive OK; SA needs Viewer) |
| `GOOGLE_SHEET_ID` | yes | Spreadsheet ID for inventory |
| `GOOGLE_SHEET_RANGE` | no | Sheet range (default `Inventory!A:I`) |
| `PUBLIC_BASE_URL` | no | Public URL for QR codes (see below) |
| `SECRET_KEY` | no | Flask session secret (set in production) |

Local example:

```bash
gcloud auth application-default login \
  --impersonate-service-account=your-sa@your-project.iam.gserviceaccount.com \
  --scopes=https://www.googleapis.com/auth/drive,https://www.googleapis.com/auth/spreadsheets.readonly

export GOOGLE_DRIVE_TRANSACTIONS_FOLDER_ID=your-transactions-folder-id
export GOOGLE_DRIVE_IMAGES_FOLDER_ID=your-images-folder-id
export GOOGLE_SHEET_ID=your-spreadsheet-id
export GOOGLE_SHEET_RANGE='Inventory!A:I'
export PUBLIC_BASE_URL=https://your-host.example.edu
```

### Cloud Run

Assign the service account to the Cloud Run service and set `GOOGLE_DRIVE_TRANSACTIONS_FOLDER_ID`, `GOOGLE_DRIVE_IMAGES_FOLDER_ID`, `GOOGLE_SHEET_ID`, and optional `GOOGLE_SHEET_RANGE` as environment variables. No credential files or secrets are required for Google API auth.

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

The listing page filters and sorts inventory in the browser (search, category, location). Inventory, transaction history, and images are cached in memory after the first load to reduce Google API calls.

After editing the inventory Google Sheet externally, use **Admin → Refresh inventory** on the inventory page to reload the sheet and clear cached images.

## Data layout

```
Google Sheet                     # inventory rows
Google Drive transactions folder/
  {item_id}.csv                  # append-only history per item
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
| `location` | Storage location |
| `components` | Semicolon-separated list (e.g. `microphone; XLR cable`) |
| `image` | Filename in the Drive images folder (e.g. `sm58.png`) |

**Display name** (shown in the UI, not stored in the sheet):

```
{brand} {model} {number}
```

## Transaction files

One CSV per item (`{item_id}.csv`) in the transactions Drive folder. Rows are appended at the bottom; history is shown oldest first.

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
- **Reservations:** `reserve` adds; `cancel_reservation` removes. Only reservations with `reserve_end` on or after today are active (past reservations are ignored). Checkout is allowed during your own reservation (matching kerberos), but the checkout period (today through projected return) cannot overlap any other active reservation.

Concurrent appends update the in-memory transaction cache and write the full CSV to Drive (single-server; per-item locks).

## Item operations

Open an item from the inventory list. Use the forms on the item page to check out, check in, change condition, reserve, or cancel a reservation. Each action appends a row to that item's transaction file on Drive.

## Admin

On the inventory page, open **Admin** for:

- **Refresh inventory** — reload the Google Sheet and clear cached images (use after external sheet or image changes)
- **Print QR codes** — print 1.5″ × 1.5″ stickers for selected items

Each sticker shows the item name, location, components, and a QR code linking to that item's detail page. Items are listed newest-first (reverse of sheet row order).

Set `PUBLIC_BASE_URL` when deploying so QR codes point at your real host (e.g. `https://soundcheck.mit.edu`). If unset, the app uses the current request URL (fine for local dev).

## Adding items

Add a row to the inventory Google Sheet, then choose **Admin → Refresh inventory** on the inventory page.

## Migration from local files

If you have an existing `data/` directory:

1. Import `data/inventory.csv` into your Google Sheet.
2. Upload `data/images/*` to the images Drive folder.
3. Upload `data/transactions/*.csv` to the transactions Drive folder.
4. Set environment variables and deploy.
