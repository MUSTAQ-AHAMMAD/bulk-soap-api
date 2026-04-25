# Bulk SOAP Runner — Oracle Fusion Miscellaneous Receipt Processor

A beautiful, full-stack web application for running bulk Oracle Fusion SOAP API calls (`createMiscellaneousReceipt`) from a CSV file, with real-time progress tracking and a live log console — all controlled from the browser.

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
├── requirements.txt         # Python dependencies
├── sample_receipts.csv      # 5 sample Oracle rows
├── README.md
└── templates/
    └── index.html           # Full frontend (Tailwind CDN + Vanilla JS)
```

---

## 🚀 Quick Start

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
- **Dates:** Must be `YYYY-MM-DD`
- **OrgId:** Must match your Business Unit exactly
- **SSL:** `verify=True` (production safe)

---

## 📦 Dependencies

```
fastapi
uvicorn
requests
python-multipart
websockets
```
