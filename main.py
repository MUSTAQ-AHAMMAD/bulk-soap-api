import asyncio
import csv
import io
import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests
from fastapi import FastAPI, File, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from requests.auth import HTTPBasicAuth

app = FastAPI(title="Bulk SOAP Runner")

_TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")

# ─── Global state ─────────────────────────────────────────────────────────────
_job_state: Dict[str, Any] = {
    "status": "idle",          # idle | running | stopped | completed
    "total": 0,
    "processed": 0,
    "success": 0,
    "failed": 0,
    "results": [],
    "csv_rows": [],
}
_stop_event = threading.Event()
_connected_clients: List[WebSocket] = []
_clients_lock = asyncio.Lock()
_main_loop: Optional[asyncio.AbstractEventLoop] = None

# ─── WebSocket helpers ────────────────────────────────────────────────────────

async def _broadcast(message: dict):
    """Send JSON message to all connected WebSocket clients."""
    async with _clients_lock:
        dead = []
        for ws in _connected_clients:
            try:
                await ws.send_text(json.dumps(message))
            except Exception:
                dead.append(ws)
        for ws in dead:
            _connected_clients.remove(ws)


def _broadcast_sync(message: dict):
    """Thread-safe broadcast from non-async threads."""
    global _main_loop
    if _main_loop is not None:
        try:
            asyncio.run_coroutine_threadsafe(_broadcast(message), _main_loop)
        except Exception:
            pass


# ─── SOAP logic ───────────────────────────────────────────────────────────────

def build_soap_payload(row: dict) -> str:
    """Build Oracle Fusion createMiscellaneousReceipt SOAP XML from a CSV row."""
    # Normalize date format from YYYY/MM/DD to YYYY-MM-DD if needed
    def normalize_date(date_str: str) -> str:
        return date_str.replace("/", "-") if date_str else ""

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope
    xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
    xmlns:types="http://xmlns.oracle.com/apps/financials/receivables/receipts/shared/miscellaneousReceiptService/commonService/types/"
    xmlns:misc="http://xmlns.oracle.com/apps/financials/receivables/receipts/miscellaneousReceipts/">
  <soapenv:Header/>
  <soapenv:Body>
    <types:createMiscellaneousReceipt>
      <types:miscellaneousReceipt>
        <misc:Amount>{row.get("Amount", "")}</misc:Amount>
        <misc:CurrencyCode>{row.get("CurrencyCode", "")}</misc:CurrencyCode>
        <misc:ReceiptNumber>{row.get("ReceiptNumber", "")}</misc:ReceiptNumber>
        <misc:ReceiptDate>{normalize_date(row.get("ReceiptDate", ""))}</misc:ReceiptDate>
        <misc:DepositDate>{normalize_date(row.get("DepositDate", ""))}</misc:DepositDate>
        <misc:GlDate>{normalize_date(row.get("GlDate", ""))}</misc:GlDate>
        <misc:ReceiptMethodName>{row.get("ReceiptMethodName", "")}</misc:ReceiptMethodName>
        <misc:ReceivableActivityName>{row.get("ReceivableActivityName", "")}</misc:ReceivableActivityName>
        <misc:BankAccountNumber>{row.get("BankAccountNumber", "")}</misc:BankAccountNumber>
        <misc:OrgId>{row.get("OrgId", "")}</misc:OrgId>
      </types:miscellaneousReceipt>
    </types:createMiscellaneousReceipt>
  </soapenv:Body>
</soapenv:Envelope>"""


def extract_fault(xml_text: str) -> str:
    """Extract faultstring from a SOAP Fault response."""
    match = re.search(r"<faultstring[^>]*>(.*?)</faultstring>", xml_text, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    match = re.search(r"<detail[^>]*>(.*?)</detail>", xml_text, re.DOTALL | re.IGNORECASE)
    if match:
        text = re.sub(r"<[^>]+>", " ", match.group(1)).strip()
        return " ".join(text.split())[:300]
    return "Unknown SOAP error"


def extract_receipt_number(xml_text: str) -> str:
    """Try to pull ReceiptNumber from the success response."""
    match = re.search(r"<[^>]*ReceiptNumber[^>]*>(.*?)</[^>]*ReceiptNumber[^>]*>", xml_text, re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else ""


def call_soap_api(row: dict, row_num: int, config: dict):
    """
    Send a single SOAP request.
    Returns (status, http_code, error_msg, receipt_number).
    """
    payload = build_soap_payload(row)
    headers = {
        "Content-Type": "text/xml; charset=utf-8",
        "SOAPAction": "http://xmlns.oracle.com/apps/financials/receivables/receipts/shared/miscellaneousReceiptService/commonService/createMiscellaneousReceipt",
    }
    try:
        resp = requests.post(
            config["endpoint"],
            data=payload.encode("utf-8"),
            headers=headers,
            auth=HTTPBasicAuth(config["username"], config["password"]),
            timeout=60,
            verify=True,
        )
        http_code = resp.status_code
        if http_code == 200 and "<Fault" not in resp.text and "<fault" not in resp.text.lower():
            receipt = extract_receipt_number(resp.text) or row.get("ReceiptNumber", "")
            return "SUCCESS", http_code, "", receipt
        else:
            fault = extract_fault(resp.text)
            return "SOAP_FAULT", http_code, fault, row.get("ReceiptNumber", "")
    except requests.exceptions.RequestException as exc:
        return "HTTP_ERROR", 0, str(exc), row.get("ReceiptNumber", "")


def process_bulk(rows: list, config: dict):
    """
    Main processing function — runs in a background thread.
    Supports sequential and concurrent modes.
    Broadcasts progress via WebSocket.
    """
    global _job_state
    _job_state["status"] = "running"
    _job_state["total"] = len(rows)
    _job_state["processed"] = 0
    _job_state["success"] = 0
    _job_state["failed"] = 0
    _job_state["results"] = []
    _stop_event.clear()

    start_time = time.time()
    delay = float(config.get("delay", 0.3))
    max_workers = int(config.get("max_workers", 5))
    mode = config.get("mode", "sequential")

    def _handle_result(row: dict, row_num: int, status: str, http_code: int, error: str, receipt: str):
        _job_state["processed"] += 1
        if status == "SUCCESS":
            _job_state["success"] += 1
            icon = "✅"
            log_status = "SUCCESS"
        else:
            _job_state["failed"] += 1
            icon = "❌"
            log_status = status

        _job_state["results"].append({
            **row,
            "Status": status,
            "HttpCode": http_code,
            "Error": error,
        })

        elapsed = time.time() - start_time
        processed = _job_state["processed"]
        total = _job_state["total"]
        speed = processed / elapsed if elapsed > 0 else 0
        remaining = int((total - processed) / speed) if speed > 0 else 0

        ts = datetime.now().strftime("%H:%M:%S")
        if status == "SUCCESS":
            msg_text = f"[{ts}] [Row {row_num}] {icon} SUCCESS | {receipt}"
        else:
            msg_text = f"[{ts}] [Row {row_num}] {icon} {log_status} | {error[:120]}"

        message = {
            "type": "log",
            "row": row_num,
            "receipt": receipt,
            "status": status,
            "message": msg_text,
            "processed": processed,
            "total": total,
            "success": _job_state["success"],
            "failed": _job_state["failed"],
            "speed": round(speed, 2),
            "remaining": remaining,
            "timestamp": datetime.now().isoformat(),
        }
        _broadcast_sync(message)

    if mode == "concurrent":
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_map = {
                executor.submit(call_soap_api, row, row_num, config): (row, row_num)
                for row_num, row in enumerate(rows, start=1)
            }
            for future in as_completed(future_map):
                if _stop_event.is_set():
                    executor.shutdown(wait=False, cancel_futures=True)
                    break
                row, row_num = future_map[future]
                try:
                    status, http_code, error, receipt = future.result()
                except Exception as exc:
                    status, http_code, error, receipt = "HTTP_ERROR", 0, str(exc), row.get("ReceiptNumber", "")
                _handle_result(row, row_num, status, http_code, error, receipt)
                time.sleep(delay)
    else:
        for row_num, row in enumerate(rows, start=1):
            if _stop_event.is_set():
                break
            status, http_code, error, receipt = call_soap_api(row, row_num, config)
            _handle_result(row, row_num, status, http_code, error, receipt)
            time.sleep(delay)

    if _stop_event.is_set():
        _job_state["status"] = "stopped"
        final_type = "stopped"
    else:
        _job_state["status"] = "completed"
        final_type = "complete"

    elapsed = time.time() - start_time
    _broadcast_sync({
        "type": final_type,
        "processed": _job_state["processed"],
        "total": _job_state["total"],
        "success": _job_state["success"],
        "failed": _job_state["failed"],
        "elapsed": round(elapsed, 1),
        "message": f"Processing {final_type}. {_job_state['success']} succeeded, {_job_state['failed']} failed.",
        "timestamp": datetime.now().isoformat(),
    })


# ─── REST Endpoints ───────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index():
    path = os.path.join(_TEMPLATES_DIR, "index.html")
    with open(path, encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


@app.post("/upload")
async def upload_csv(file: UploadFile = File(...)):
    content = await file.read()
    text = content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    rows = [row for row in reader]
    if not rows:
        return {"error": "Empty or invalid CSV file."}
    columns = list(rows[0].keys())
    preview = rows[:5]
    _job_state["csv_rows"] = rows
    return {"total": len(rows), "columns": columns, "preview": preview}


@app.post("/start")
async def start_job(payload: dict):
    if _job_state["status"] == "running":
        return {"error": "A job is already running."}
    rows = _job_state.get("csv_rows", [])
    if not rows:
        return {"error": "No CSV data loaded. Please upload a CSV file first."}
    config = {
        "endpoint": payload.get("endpoint", ""),
        "username": payload.get("username", ""),
        "password": payload.get("password", ""),
        "delay": payload.get("delay", 0.3),
        "max_workers": payload.get("max_workers", 5),
        "mode": payload.get("mode", "sequential"),
    }
    thread = threading.Thread(target=process_bulk, args=(rows, config), daemon=True)
    thread.start()
    return {"status": "started", "total": len(rows)}


@app.post("/stop")
async def stop_job():
    _stop_event.set()
    return {"status": "stop_requested"}


@app.get("/status")
async def get_status():
    return {
        "status": _job_state["status"],
        "total": _job_state["total"],
        "processed": _job_state["processed"],
        "success": _job_state["success"],
        "failed": _job_state["failed"],
    }


@app.get("/download-results")
async def download_results():
    results = _job_state.get("results", [])
    if not results:
        return {"error": "No results available."}

    output = io.StringIO()
    fieldnames = list(results[0].keys())
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(results)

    output.seek(0)
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode("utf-8")),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=results.csv"},
    )


# ─── WebSocket ────────────────────────────────────────────────────────────────

@app.websocket("/ws/logs")
async def websocket_logs(websocket: WebSocket):
    global _main_loop
    # Capture the event loop on first WebSocket connection
    if _main_loop is None:
        _main_loop = asyncio.get_running_loop()

    await websocket.accept()
    async with _clients_lock:
        _connected_clients.append(websocket)
    try:
        # Send current state immediately on connect
        await websocket.send_text(json.dumps({
            "type": "state",
            "status": _job_state["status"],
            "total": _job_state["total"],
            "processed": _job_state["processed"],
            "success": _job_state["success"],
            "failed": _job_state["failed"],
        }))
        while True:
            # Keep connection alive — client can send pings
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        async with _clients_lock:
            if websocket in _connected_clients:
                _connected_clients.remove(websocket)


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
