# Bulk SOAP Runner — Oracle Fusion Miscellaneous Receipt Processor

A beautiful, full-stack web application for running bulk Oracle Fusion SOAP API calls (`createMiscellaneousReceipt`) from a CSV file, with real-time progress tracking and a live log console — all controlled from the browser.

## 🎯 NEW in Version 2.0: Enhanced Validation & Error Handling

This version includes comprehensive validation and error handling to fix Oracle ADF validation errors (JBO-27024, JBO-27027):

✅ **Pre-validation of mandatory fields** before sending SOAP requests
✅ **Enhanced SOAP fault parsing** to extract full JBO error details
✅ **Detailed logging** for missing/null fields to file and console
✅ **Retry logic** with exponential backoff for transient errors
✅ **Standalone validator script** for command-line batch processing
✅ **Comprehensive error reporting** per row with validation details

📖 **See [VALIDATION_GUIDE.md](VALIDATION_GUIDE.md) for complete documentation on the new features.**

---

## ✨ Features

- 🎨 **Beautiful dark UI** — Tailwind CSS, deep-navy theme, Oracle-red accents
- 📂 **Drag & drop CSV upload** with inline preview (first 5 rows)
- ⚡ **Sequential or Concurrent** processing (ThreadPoolExecutor)
- 📡 **Real-time WebSocket logs** — color-coded, auto-scrolling terminal
- 📊 **Animated progress bar** with speed (rec/s) and ETA
- ⏹ **Stop button** — gracefully halts mid-processing
- 💾 **Download Results CSV** — original columns + `Status`, `HttpCode`, `Error`
- 📥 **Download Logs** — saves the full console log as `.txt`
- 🔄 **Reset** — clears all state for a fresh run
- 🔁 **Auto-reconnect** WebSocket (survives page refresh)

---

## 🗂️ File Structure

```
bulk-soap-api/
├── main.py                  # FastAPI backend + WebSocket + SOAP logic
├── soap_validator.py        # Standalone CLI validator with retry logic (NEW)
├── demo_validator.py        # Interactive demo of validation features (NEW)
├── requirements.txt         # Python dependencies
├── sample_receipts.csv      # 5 sample Oracle rows
├── README.md                # This file
├── VALIDATION_GUIDE.md      # Complete validation & error handling guide (NEW)
└── templates/
    └── index.html           # Full frontend (Tailwind CDN + Vanilla JS)
```

---

## 🚀 Quick Start

### Option 1: Web Application (Recommended)

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Start the server

```bash
python main.py
```

Or with uvicorn directly:

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### 3. Open the browser

```
http://localhost:8000
```

### Option 2: Command-Line Validator

For batch processing from the command line:

```bash
python soap_validator.py sample_receipts.csv \
  https://your-instance.oraclecloud.com/.../createMiscellaneousReceipt \
  your_username your_password
```

**Features:**
- Pre-validates all fields before API calls
- Detailed error logging to `soap_validation.log`
- Results exported to `results.csv` with validation details
- Automatic retry with exponential backoff

### Option 3: See Demo of Features

Run the interactive demo to see validation features in action:

```bash
python demo_validator.py
```

This demonstrates:
- Field validation with various test cases
- SOAP fault parsing examples
- Missing field detection
- Error message extraction

---

## 📋 CSV Format

The CSV must include the following columns (header row required):

| Column | Example | Description |
|---|---|---|
| `Amount` | `-11.41` | Receipt amount (negative for charges) |
| `CurrencyCode` | `SAR` | ISO currency code |
| `ReceiptNumber` | `Mada-BLKU-0005039-MISC` | Unique receipt identifier |
| `ReceiptDate` | `2026-03-05` | Date of receipt (YYYY-MM-DD) |
| `DepositDate` | `2026-03-05` | Deposit date (YYYY-MM-DD) |
| `GlDate` | `2026-03-05` | GL accounting date (YYYY-MM-DD) |
| `ReceiptMethodName` | `Mada` | Payment method name |
| `ReceivableActivityName` | `Bank Charge` | Activity name |
| `BankAccountNumber` | `157-95017321-ABHATIMSQR` | Bank account |
| `OrgId` | `300000001421038` | Business Unit Org ID |

A sample file (`sample_receipts.csv`) with 5 rows is included.

⚠️ **Important:** All fields marked as "mandatory" in the table above MUST be present and non-empty, or the request will fail validation. See [VALIDATION_GUIDE.md](VALIDATION_GUIDE.md) for details.

---

## ⚙️ Configuration

| Field | Description | Default |
|---|---|---|
| **Endpoint URL** | Oracle Fusion SOAP endpoint | Pre-filled |
| **Username** | Oracle Fusion username | — |
| **Password** | Oracle Fusion password | — |
| **Delay (sec)** | Pause between API calls | `0.3` |
| **Max Workers** | Threads for concurrent mode | `5` |
| **Mode** | `sequential` or `concurrent` | `sequential` |
| **Max Retries** | Retry attempts for failed requests (NEW) | `3` |
| **Retry Delay** | Initial delay between retries in seconds (NEW) | `1.0` |

---

## 🔌 API Reference

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | Serves the frontend UI |
| `POST` | `/upload` | Upload CSV, returns rows + preview |
| `POST` | `/start` | Start bulk processing job |
| `POST` | `/stop` | Gracefully stop running job |
| `GET` | `/status` | Current job status & stats |
| `GET` | `/download-results` | Download results as CSV |
| `WS` | `/ws/logs` | Real-time log stream (JSON) |

---

## 📡 WebSocket Message Format

```json
{
  "type": "log",
  "row": 5,
  "receipt": "Mada-BLKU-0005039-MISC",
  "status": "SUCCESS",
  "message": "[01:04:00] [Row 5] ✅ SUCCESS | Mada-BLKU-0005039-MISC",
  "processed": 5,
  "total": 100,
  "success": 4,
  "failed": 1,
  "speed": 2.1,
  "remaining": 45,
  "timestamp": "2026-04-25T01:04:00"
}
```

Message types: `log` | `progress` | `complete` | `stopped` | `error` | `state`

---

## 🔐 Oracle Fusion Notes

- **Auth:** HTTP Basic Auth
- **SOAPAction:** `createMiscellaneousReceipt`
- **SOAP Faults:** Oracle returns HTTP 200 even on errors — the backend always checks the response body for `<Fault>`
- **Dates:** Must be `YYYY-MM-DD` or `YYYY/MM/DD` (automatically normalized)
- **OrgId:** Must match your Business Unit exactly
- **SSL:** `verify=True` (production safe)
- **Error Handling:** Now includes full JBO error extraction and detailed validation (NEW)
- **Retry Logic:** Automatic retry for transient errors with exponential backoff (NEW)

---

## 🐛 Troubleshooting

### Common JBO Errors

**JBO-27024: Failed to validate a row**
- Indicates row-level validation failure in Oracle Entity Object
- Check the accompanying JBO-27027 message for specific missing fields
- Review the ValidationErrors column in results.csv

**JBO-27027: Missing [attribute/association]**
- Specific field is null or missing
- The missing field name is shown in brackets (e.g., "Missing [CustomerAccountId]")
- Add the field to your CSV or SOAP payload

### Viewing Detailed Logs

All operations are logged to `soap_processing.log` with:
- Validation errors before API calls
- Full SOAP fault details
- Missing field information
- Retry attempts and timing

```bash
# View validation errors
grep "VALIDATION_ERROR" soap_processing.log

# View SOAP faults
grep "SOAP_FAULT" soap_processing.log

# View missing fields
grep "Missing field info" soap_processing.log
```

### Testing Individual Receipts

Use the standalone validator with a single-row CSV:

```bash
python soap_validator.py test_receipt.csv endpoint user pass 1 0
```

See [VALIDATION_GUIDE.md](VALIDATION_GUIDE.md) for complete troubleshooting guide.

---

## 📦 Dependencies

```
fastapi
uvicorn
requests
python-multipart
websockets
```
