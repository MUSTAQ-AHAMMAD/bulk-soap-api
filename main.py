import asyncio
import csv
import io
import json
import logging
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import requests
from fastapi import FastAPI, File, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from requests.auth import HTTPBasicAuth

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('soap_processing.log'),
        logging.StreamHandler()
    ]
)

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

# Define mandatory fields for Oracle Fusion MiscellaneousReceipt
MANDATORY_FIELDS = {
    "Amount": "Receipt amount is required",
    "CurrencyCode": "Currency code is required",
    "ReceiptNumber": "Receipt number is required",
    "ReceiptDate": "Receipt date is required",
    "ReceiptMethodName": "Receipt method name is required",
    "ReceivableActivityName": "Receivable activity name is required",
    "BankAccountNumber": "Bank account number is required",
    "OrgId": "Organization ID is required"
}


def validate_mandatory_fields(row: dict, row_num: int) -> Tuple[bool, List[str]]:
    """
    Validate that all mandatory fields are present and not empty.
    Returns (is_valid, list_of_missing_fields).
    """
    missing_fields = []

    for field_name, error_msg in MANDATORY_FIELDS.items():
        value = row.get(field_name, "")
        # Convert to string and strip to handle various input types
        value_str = str(value).strip() if value is not None else ""
        if not value_str:
            missing_fields.append(f"{field_name} ({error_msg})")
            logging.warning(f"Row {row_num}: Missing {field_name} - {error_msg}")

    # Validate date formats
    date_fields = ["ReceiptDate", "DepositDate", "GlDate"]
    for date_field in date_fields:
        value = row.get(date_field, "")
        value_str = str(value).strip() if value is not None else ""
        if value_str:
            # Check date format (YYYY-MM-DD or YYYY/MM/DD)
            if not re.match(r'^\d{4}[-/]\d{2}[-/]\d{2}$', value_str):
                missing_fields.append(f"{date_field} (Invalid date format, expected YYYY-MM-DD)")
                logging.warning(f"Row {row_num}: Invalid date format for {date_field}: {value_str}")

    # Validate Amount is numeric
    amount = row.get("Amount", "")
    amount_str = str(amount).strip() if amount is not None else ""
    if amount_str:
        try:
            float(amount_str)
        except ValueError:
            missing_fields.append("Amount (Must be a valid number)")
            logging.warning(f"Row {row_num}: Invalid Amount value: {amount_str}")

    is_valid = len(missing_fields) == 0
    return is_valid, missing_fields


def build_soap_payload(row: dict) -> str:
    """Build Oracle Fusion createMiscellaneousReceipt SOAP XML from a CSV row."""
    # Normalize date format from YYYY/MM/DD to YYYY-MM-DD if needed
    def normalize_date(date_str: str) -> str:
        return date_str.replace("/", "-") if date_str else ""

    # Safely get and normalize field values to ensure they're strings and stripped
    def get_field(field_name: str) -> str:
        value = row.get(field_name, "")
        # Convert to string and strip whitespace to match validation logic
        return str(value).strip() if value is not None else ""

    # Build XML element only if value is not empty
    # Oracle Fusion rejects empty XML tags for required fields, so we omit them entirely
    def xml_element(tag_name: str, field_name: str, is_date: bool = False) -> str:
        value = get_field(field_name)
        if is_date:
            value = normalize_date(value)
        # Only include the XML element if there's a non-empty value
        if value:
            return f"\n        <misc:{tag_name}>{value}</misc:{tag_name}>"
        return ""

    # Build the payload with conditional elements
    payload = f"""<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope
    xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
    xmlns:types="http://xmlns.oracle.com/apps/financials/receivables/receipts/shared/miscellaneousReceiptService/commonService/types/"
    xmlns:misc="http://xmlns.oracle.com/apps/financials/receivables/receipts/miscellaneousReceipts/">
  <soapenv:Header/>
  <soapenv:Body>
    <types:createMiscellaneousReceipt>
      <types:miscellaneousReceipt>{xml_element("Amount", "Amount")}{xml_element("CurrencyCode", "CurrencyCode")}{xml_element("ReceiptNumber", "ReceiptNumber")}{xml_element("ReceiptDate", "ReceiptDate", is_date=True)}{xml_element("DepositDate", "DepositDate", is_date=True)}{xml_element("GlDate", "GlDate", is_date=True)}{xml_element("ReceiptMethodName", "ReceiptMethodName")}{xml_element("ReceivableActivityName", "ReceivableActivityName")}{xml_element("BankAccountNumber", "BankAccountNumber")}{xml_element("OrgId", "OrgId")}
      </types:miscellaneousReceipt>
    </types:createMiscellaneousReceipt>
  </soapenv:Body>
</soapenv:Envelope>"""

    return payload


def extract_fault(xml_text: str) -> str:
    """
    Extract comprehensive fault details from a SOAP Fault response.
    Parses Oracle JBO errors and extracts full error messages.
    """
    # Try to extract faultstring first
    match = re.search(r"<faultstring[^>]*>(.*?)</faultstring>", xml_text, re.DOTALL | re.IGNORECASE)
    if match:
        fault_string = match.group(1).strip()
        logging.error(f"SOAP Fault - faultstring: {fault_string}")
    else:
        fault_string = ""

    # Try to extract detail section for full error info
    detail_match = re.search(r"<detail[^>]*>(.*?)</detail>", xml_text, re.DOTALL | re.IGNORECASE)
    detail_text = ""
    if detail_match:
        detail_content = detail_match.group(1)

        # Extract JBO error codes and messages
        jbo_errors = re.findall(
            r"(JBO-\d+):?\s*(.*?)(?=JBO-\d+|$)",
            detail_content,
            re.DOTALL | re.IGNORECASE
        )

        if jbo_errors:
            error_messages = []
            for error_code, error_msg in jbo_errors:
                cleaned_msg = re.sub(r"<[^>]+>", " ", error_msg).strip()
                cleaned_msg = " ".join(cleaned_msg.split())
                if cleaned_msg:
                    full_error = f"{error_code}: {cleaned_msg}"
                    error_messages.append(full_error)
                    logging.error(f"JBO Error: {full_error}")

            if error_messages:
                detail_text = " | ".join(error_messages)

        # If no JBO errors found, extract all text from detail
        if not detail_text:
            detail_text = re.sub(r"<[^>]+>", " ", detail_content).strip()
            detail_text = " ".join(detail_text.split())
            logging.error(f"SOAP Fault - detail: {detail_text}")

    # Try to extract missing attribute/association info
    missing_attr_match = re.search(
        r"Missing\s*\[([^\]]+)\]",
        xml_text,
        re.DOTALL | re.IGNORECASE
    )
    if missing_attr_match:
        missing_attr = missing_attr_match.group(1).strip()
        missing_info = f"Missing [{missing_attr}]"
        logging.error(f"Missing field info: {missing_info}")
        if detail_text:
            detail_text += f" - {missing_info}"
        else:
            detail_text = missing_info

    # Combine fault string and detail
    if fault_string and detail_text:
        return f"{fault_string} | {detail_text}"
    elif fault_string:
        return fault_string
    elif detail_text:
        return detail_text
    else:
        logging.error(f"Unknown SOAP error - Full response logged")
        return "Unknown SOAP error"


def extract_receipt_number(xml_text: str) -> str:
    """Try to pull ReceiptNumber from the success response."""
    match = re.search(r"<[^>]*ReceiptNumber[^>]*>(.*?)</[^>]*ReceiptNumber[^>]*>", xml_text, re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else ""


def call_soap_api(row: dict, row_num: int, config: dict):
    """
    Send a single SOAP request with retry logic.
    Returns (status, http_code, error_msg, receipt_number, validation_errors).
    """
    # Pre-validation of mandatory fields
    is_valid, missing_fields = validate_mandatory_fields(row, row_num)
    if not is_valid:
        validation_error = f"Validation failed: {', '.join(missing_fields)}"
        logging.error(f"Row {row_num} - {validation_error}")
        return "VALIDATION_ERROR", 0, validation_error, row.get("ReceiptNumber", ""), missing_fields

    payload = build_soap_payload(row)
    headers = {
        "Content-Type": "text/xml; charset=utf-8",
        "SOAPAction": "http://xmlns.oracle.com/apps/financials/receivables/receipts/shared/miscellaneousReceiptService/commonService/createMiscellaneousReceipt",
    }

    # Retry logic with exponential backoff
    max_retries = int(config.get("max_retries", 3))
    retry_delay = float(config.get("retry_delay", 1.0))

    for attempt in range(max_retries):
        try:
            logging.info(f"Row {row_num} - Attempt {attempt + 1}/{max_retries} - Receipt: {row.get('ReceiptNumber', '')}")

            resp = requests.post(
                config["endpoint"],
                data=payload.encode("utf-8"),
                headers=headers,
                auth=HTTPBasicAuth(config["username"], config["password"]),
                timeout=60,
                verify=True,
            )
            http_code = resp.status_code

            # Log full response for debugging
            logging.debug(f"Row {row_num} - Response status: {http_code}")
            logging.debug(f"Row {row_num} - Response body: {resp.text[:1000]}")

            if http_code == 200 and "<Fault" not in resp.text and "<fault" not in resp.text.lower():
                receipt = extract_receipt_number(resp.text) or row.get("ReceiptNumber", "")
                logging.info(f"Row {row_num} - SUCCESS - Receipt: {receipt}")
                return "SUCCESS", http_code, "", receipt, []
            else:
                fault = extract_fault(resp.text)

                # Check if error is retryable (e.g., timeout, connection errors)
                retryable_errors = ["timeout", "connection", "temporarily unavailable"]
                is_retryable = any(err in fault.lower() for err in retryable_errors)

                if is_retryable and attempt < max_retries - 1:
                    wait_time = retry_delay * (2 ** attempt)  # Exponential backoff
                    logging.warning(f"Row {row_num} - Retryable error, waiting {wait_time}s before retry: {fault}")
                    time.sleep(wait_time)
                    continue
                else:
                    logging.error(f"Row {row_num} - SOAP_FAULT - {fault}")
                    # Log full response for analysis
                    logging.error(f"Row {row_num} - Full SOAP Response: {resp.text}")
                    return "SOAP_FAULT", http_code, fault, row.get("ReceiptNumber", ""), []

        except requests.exceptions.Timeout as exc:
            if attempt < max_retries - 1:
                wait_time = retry_delay * (2 ** attempt)
                logging.warning(f"Row {row_num} - Timeout, retrying in {wait_time}s: {str(exc)}")
                time.sleep(wait_time)
                continue
            else:
                error_msg = f"Timeout after {max_retries} attempts: {str(exc)}"
                logging.error(f"Row {row_num} - {error_msg}")
                return "HTTP_ERROR", 0, error_msg, row.get("ReceiptNumber", ""), []

        except requests.exceptions.RequestException as exc:
            if attempt < max_retries - 1:
                wait_time = retry_delay * (2 ** attempt)
                logging.warning(f"Row {row_num} - HTTP error, retrying in {wait_time}s: {str(exc)}")
                time.sleep(wait_time)
                continue
            else:
                error_msg = f"HTTP error after {max_retries} attempts: {str(exc)}"
                logging.error(f"Row {row_num} - {error_msg}")
                return "HTTP_ERROR", 0, error_msg, row.get("ReceiptNumber", ""), []

    # Should not reach here, but return error if it does
    return "HTTP_ERROR", 0, "Max retries exceeded", row.get("ReceiptNumber", ""), []


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

    def _handle_result(row: dict, row_num: int, status: str, http_code: int, error: str, receipt: str, validation_errors: list):
        _job_state["processed"] += 1
        if status == "SUCCESS":
            _job_state["success"] += 1
            icon = "✅"
            log_status = "SUCCESS"
        else:
            _job_state["failed"] += 1
            icon = "❌"
            log_status = status

        # Prepare result row with validation errors if any
        result_row = {
            **row,
            "Status": status,
            "HttpCode": http_code,
            "Error": error,
        }

        # Add validation errors to result if present
        if validation_errors:
            result_row["ValidationErrors"] = "; ".join(validation_errors)

        _job_state["results"].append(result_row)

        elapsed = time.time() - start_time
        processed = _job_state["processed"]
        total = _job_state["total"]
        speed = processed / elapsed if elapsed > 0 else 0
        remaining = int((total - processed) / speed) if speed > 0 else 0

        ts = datetime.now().strftime("%H:%M:%S")
        if status == "SUCCESS":
            msg_text = f"[{ts}] [Row {row_num}] {icon} SUCCESS | {receipt}"
        elif status == "VALIDATION_ERROR":
            msg_text = f"[{ts}] [Row {row_num}] {icon} {log_status} | Missing fields: {', '.join([f.split(' (')[0] for f in validation_errors])}"
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
                    status, http_code, error, receipt, validation_errors = future.result()
                except Exception as exc:
                    status, http_code, error, receipt, validation_errors = "HTTP_ERROR", 0, str(exc), row.get("ReceiptNumber", ""), []
                _handle_result(row, row_num, status, http_code, error, receipt, validation_errors)
                time.sleep(delay)
    else:
        for row_num, row in enumerate(rows, start=1):
            if _stop_event.is_set():
                break
            status, http_code, error, receipt, validation_errors = call_soap_api(row, row_num, config)
            _handle_result(row, row_num, status, http_code, error, receipt, validation_errors)
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
        "max_retries": payload.get("max_retries", 3),
        "retry_delay": payload.get("retry_delay", 1.0),
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
