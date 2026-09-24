# Google Drive Material Index MVP

FastAPI single-app MVP for a Google Drive backed product material library.

## Quick Start

Enable Google Drive API for the Google Cloud project first:
`https://console.developers.google.com/apis/api/drive.googleapis.com/overview`

Install and run:

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
$env:DRIVE_ROOT_FOLDER_ID="your-google-drive-folder-id"
$env:GOOGLE_OAUTH_TOKEN_FILE="C:\path\google-token.json"
$env:APP_SECRET="change-me"
$env:ADMIN_EMAIL="admin@example.com"
$env:ADMIN_PASSWORD="change-me-now"
# Optional, when Google is only reachable through a local VPN proxy:
$env:GOOGLE_PROXY="http://127.0.0.1:58319"
uvicorn app.main:app --reload
```

The FastAPI process on `http://127.0.0.1:8000` is the API backend only.
Run the React client separately and open its development URL.

For the current local Drive test, run:

```powershell
.\run-local.ps1
```

Then open the React client at `http://127.0.0.1:4173`.

## Live Inventory

The product API can read the latest local-warehouse inventory from the inventory workbench database. Values are grouped by SKU across the latest successful checkpoint for every warehouse and cached in the application for 60 seconds. Alongside total available inventory, the catalog exposes the signed-in salesperson's warehouse inventory and 181–365/366+ day age buckets, plus total pending quality-control and pending-arrival quantities. The salesperson warehouse matches the account name exactly or with `仓库` appended, and cache entries are isolated by account. The catalog keeps an imported Excel inventory value only when the live source is not configured or temporarily unavailable.

Use a MySQL account with read-only access to `stocking_inventory_warehouse_sync_checkpoints` and `stocking_lingxing_inventory_details`:

```powershell
$env:INVENTORY_DB_HOST="127.0.0.1"
$env:INVENTORY_DB_PORT="3306"
$env:INVENTORY_DB_NAME="inventory_database"
$env:INVENTORY_DB_USER="inventory_reader"
$env:INVENTORY_DB_PASSWORD="set-in-the-server-secret-store"
$env:INVENTORY_DB_CACHE_SECONDS="60"
```

For an existing env-format credential file, set `INVENTORY_DB_ENV_FILE` to its path. Explicit `INVENTORY_DB_*` values override the file. Use `INVENTORY_DB_SSL=1` when the database requires TLS.

## Thumbnail Cache

Original assets remain in Google Drive. The application stores generated WebP previews on disk under
`data/zip_cache/thumbs` and keeps only Drive index metadata in SQLite.

- `small`: 126 x 110, WebP quality 68, for the detail filmstrip.
- `drawer`: 560 x 416, WebP quality 75, shared by catalogue cards and the detail preview.
- Cache identity includes file ID, Drive modified time, variant, and encoder version.
- Startup and every Drive sync backfill all previewable files into the local cache. One Google
  thumbnail download generates both WebP variants; catalogue and detail browsing never
  schedules a Google download.
- Versioned responses use `Cache-Control: private, max-age=31536000, immutable`.
- A background cleanup removes stale orphaned cache files after a seven-day grace period.

Optional environment settings:

```powershell
$env:THUMB_CACHE_DIR="D:\cache\material-index\thumbs"
$env:THUMBNAIL_WORKERS="4"
$env:THUMBNAIL_QUEUE_SIZE="512"
$env:THUMBNAIL_CACHE_CLEANUP_SECONDS="21600"
$env:THUMBNAIL_CACHE_GRACE_SECONDS="604800"
```

## Google Auth Without Service Account Keys

If your organization blocks service account keys with `iam.disableServiceAccountKeyCreation`, use OAuth:

1. Google Cloud Console -> APIs & Services -> Credentials.
2. Create an OAuth client ID. Choose `Desktop app` for local token generation.
3. Download the OAuth client JSON.
4. Run:

```powershell
.\.venv\Scripts\python.exe scripts\create_oauth_token.py --client C:\path\oauth-client.json --out C:\path\google-token.json
```

Sign in with a Google account that can access the target Drive folder. The app then uses:

```powershell
$env:GOOGLE_OAUTH_TOKEN_FILE="C:\path\google-token.json"
```

For moving approved files out of the Drive inbox, generate a token with Drive write access:

```powershell
.\.venv\Scripts\python.exe scripts\create_oauth_token.py --client C:\path\oauth-client.json --out C:\path\google-token.json --write
```

Service account JSON is still supported only when your organization allows keys:

```powershell
$env:GOOGLE_SERVICE_ACCOUNT_FILE="C:\path\service-account.json"
```

## NAS to Drive Approval

The NAS syncs new files into the `临时` folder under `DRIVE_ROOT_FOLDER_ID`. The app scans only that Drive folder and adds its images to the admin approval queue.

```powershell
$env:DRIVE_ROOT_FOLDER_ID="0ACmeRj4wNpNYUk9PVA"
$env:GOOGLE_OAUTH_TOKEN_FILE="C:\path\google-token.json"
# Optional, only needed for AI text suggestions:
$env:OPENAI_API_KEY="sk-..."
$env:OPENAI_MODEL="your-openai-model"
$env:AI_PROVIDER="deepseek"
$env:DEEPSEEK_API_KEY="sk-..."
$env:DEEPSEEK_MODEL="deepseek-v4-flash"
```

To replace AI naming and manual review with the DingTalk product catalogue, install the official `dws` CLI, log in once with the user who can read the table, and configure:

```powershell
$env:DINGTALK_AITABLE_SYNC_ENABLED="1"
$env:DINGTALK_AITABLE_DWS_BIN="C:\path\to\dws.exe"
$env:DWS_CONFIG_DIR="C:\path\to\private-dws-config"
$env:DINGTALK_AITABLE_BASE_ID="lyQod3RxJKEYYQAkh4dlg59dWkb4Mw9r"
$env:DINGTALK_AITABLE_TABLE_ID="8bpp2K8"
```

In this mode the staging product folder only needs one SKU. On every staging scan the app queries that SKU in `产品目录_总表`, copies its English name, brand, product type, and Set number, calculates the canonical Drive directory, and moves the media automatically. It never asks an AI to invent an English name. Before moving each Drive file, the app checks that the source still belongs to the staging inbox and compares its live Drive content checksum with files already in the target product folder. Already-used or byte-identical media is recorded as processed without being moved again; name collisions with different content receive a unique sequence. A missing SKU, duplicate A-table SKU, incomplete row, unsupported value, or non-`A_产品目录` row stays in the pending queue and is not moved.

Open `http://127.0.0.1:4173/#admin`, then use the pending-material panel:

1. Click `扫描临时目录`.
2. Click `生成建议` if OpenAI env vars are configured.
3. Review or edit SKU, English name, Drive folder, Drive filename, and asset type.
4. Click `确认入库`.

Approval moves and renames the existing Drive file into its final folder without uploading a duplicate. Rejected files remain in `临时` but stay out of the pending list. The OAuth token therefore needs Drive write access.

## CSV Mapping

Upload a UTF-8 CSV from the admin page with:

```csv
sku,english_name,owner,notes
ABC-001,Blade Putter Cover,Amy,Spring batch
```

## Drive Rules

- The shared-drive root scan includes the two product roots (`04 Product Images` and `04 Product Images (No Brand)`) plus the independent customer-facing `Other` roots: `Product Catalogs`, `Brand Assets`, `Packaging Assets`, `Show & Exhibitions`, `Event & Sponsorships`, `Influencer Assets`, and `Collection Assets`. Numeric folder prefixes are ignored when matching these names.
- Approved NAS destinations must include one of those top-level collection names in the Drive folder path.
- Brand/category/SKU are inferred from the Drive path under `DRIVE_ROOT_FOLDER_ID`.
- `Other` assets are inferred from their root folder and do not inherit Product Category or Theme.
- Paths containing `_internal`, `内部`, or `源文件` are hidden from external users.
- Asset type is inferred from folder keywords first, then MIME type.

## Fixed Product Taxonomy

Product categories are independent from Google Drive folder names. The application uses
`app/category_kit/config/taxonomy.json` as the fixed dictionary and
`app/category_kit/data/sku_registry.csv` as the reviewed SKU inheritance source.

- Existing reviewed SKUs inherit their category automatically.
- New product SKUs receive a deterministic suggestion and must be confirmed by an administrator before approval.
- Plush/animal and supported putter models are additive feature tags, not competing primary categories.
- Administrator corrections are stored in the append-only `category_correction_events` audit table.
- Customer-facing category labels use the English taxonomy label; Drive paths remain unchanged.

## Load Test

Install the isolated load-test dependency:

```powershell
.\.venv\Scripts\pip.exe install -r requirements-load.txt
```

Run a short local baseline with 20 concurrent users:

```powershell
$env:LOAD_EMAIL="admin@example.com"
$env:LOAD_PASSWORD="set-in-env"
$env:LOAD_SKUS="6012159"
.\.venv\Scripts\locust.exe -f load_tests\locustfile.py --headless --host http://127.0.0.1:8001 -u 20 -r 2 -t 2m --csv load-test
```

The default release gate is at most 1% failed requests and an overall P95 response time at most 2000 ms. Override with `LOAD_MAX_FAIL_RATIO` and `LOAD_MAX_P95_MS`. Set `LOAD_INCLUDE_ADMIN=1` only when the load-test account is an admin. The default scenario does not scan NAS, call AI, approve imports, download media, or create ZIP files.

