"""
Oracle Fusion SOAP API Validator and Processor
Standalone script for validating and processing bulk SOAP API requests
with comprehensive error handling and logging.

Features:
- Pre-validation of mandatory fields before sending SOAP requests
- Enhanced SOAP fault parsing to extract full JBO error details
- Detailed logging for missing/null fields
- Retry logic with exponential backoff
- Batch processing with per-row error reporting
"""

import csv
import logging
import re
import time
from typing import Dict, List, Tuple

import requests
from requests.auth import HTTPBasicAuth


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('soap_validation.log'),
        logging.StreamHandler()
    ]
)

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
        value = str(row.get(field_name, "")).strip()
        if not value:
            missing_fields.append(f"{field_name} ({error_msg})")
            logging.warning(f"Row {row_num}: Missing {field_name} - {error_msg}")

    # Validate date formats
    date_fields = ["ReceiptDate", "DepositDate", "GlDate"]
    for date_field in date_fields:
        value = str(row.get(date_field, "")).strip()
        if value:
            # Check date format (YYYY-MM-DD or YYYY/MM/DD)
            if not re.match(r'^\d{4}[-/]\d{2}[-/]\d{2}$', value):
                missing_fields.append(f"{date_field} (Invalid date format, expected YYYY-MM-DD)")
                logging.warning(f"Row {row_num}: Invalid date format for {date_field}: {value}")

    # Validate Amount is numeric
    amount = str(row.get("Amount", "")).strip()
    if amount:
        try:
            float(amount)
        except ValueError:
            missing_fields.append("Amount (Must be a valid number)")
            logging.warning(f"Row {row_num}: Invalid Amount value: {amount}")

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

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope
    xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
    xmlns:types="http://xmlns.oracle.com/apps/financials/receivables/receipts/shared/miscellaneousReceiptService/commonService/types/"
    xmlns:misc="http://xmlns.oracle.com/apps/financials/receivables/receipts/miscellaneousReceipts/">
  <soapenv:Header/>
  <soapenv:Body>
    <types:createMiscellaneousReceipt>
      <types:miscellaneousReceipt>
        <misc:Amount>{get_field("Amount")}</misc:Amount>
        <misc:CurrencyCode>{get_field("CurrencyCode")}</misc:CurrencyCode>
        <misc:ReceiptNumber>{get_field("ReceiptNumber")}</misc:ReceiptNumber>
        <misc:ReceiptDate>{normalize_date(get_field("ReceiptDate"))}</misc:ReceiptDate>
        <misc:DepositDate>{normalize_date(get_field("DepositDate"))}</misc:DepositDate>
        <misc:GlDate>{normalize_date(get_field("GlDate"))}</misc:GlDate>
        <misc:ReceiptMethodName>{get_field("ReceiptMethodName")}</misc:ReceiptMethodName>
        <misc:ReceivableActivityName>{get_field("ReceivableActivityName")}</misc:ReceivableActivityName>
        <misc:BankAccountNumber>{get_field("BankAccountNumber")}</misc:BankAccountNumber>
        <misc:OrgId>{get_field("OrgId")}</misc:OrgId>
      </types:miscellaneousReceipt>
    </types:createMiscellaneousReceipt>
  </soapenv:Body>
</soapenv:Envelope>"""


def extract_soap_fault_details(xml_text: str) -> str:
    """
    Extract comprehensive fault details from a SOAP Fault response.
    Parses Oracle JBO errors and extracts full error messages including
    the complete JBO-27027 message showing which fields are missing.
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

        # Extract JBO error codes and messages (including JBO-27024, JBO-27027)
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
        # Log full response for detailed analysis
        logging.error(f"Unknown SOAP error - Full response: {xml_text}")
        return "Unknown SOAP error - see logs for full response"


def call_soap_api_with_validation(
    row: dict,
    row_num: int,
    endpoint: str,
    username: str,
    password: str,
    max_retries: int = 3,
    retry_delay: float = 1.0
) -> Dict:
    """
    Send a single SOAP request with pre-validation and retry logic.
    Returns a dictionary with status, error details, and validation info.
    """
    result = {
        "row_number": row_num,
        "receipt_number": row.get("ReceiptNumber", ""),
        "status": "",
        "http_code": 0,
        "error": "",
        "validation_errors": [],
        "attempts": 0
    }

    # Pre-validation of mandatory fields
    is_valid, missing_fields = validate_mandatory_fields(row, row_num)
    if not is_valid:
        result["status"] = "VALIDATION_ERROR"
        result["validation_errors"] = missing_fields
        result["error"] = f"Validation failed: {', '.join(missing_fields)}"
        logging.error(f"Row {row_num} - {result['error']}")
        return result

    payload = build_soap_payload(row)
    headers = {
        "Content-Type": "text/xml; charset=utf-8",
        "SOAPAction": "http://xmlns.oracle.com/apps/financials/receivables/receipts/shared/miscellaneousReceiptService/commonService/createMiscellaneousReceipt",
    }

    # Retry logic with exponential backoff
    for attempt in range(max_retries):
        result["attempts"] = attempt + 1
        try:
            logging.info(
                f"Row {row_num} - Attempt {attempt + 1}/{max_retries} - "
                f"Receipt: {row.get('ReceiptNumber', '')}"
            )

            resp = requests.post(
                endpoint,
                data=payload.encode("utf-8"),
                headers=headers,
                auth=HTTPBasicAuth(username, password),
                timeout=60,
                verify=True,
            )
            result["http_code"] = resp.status_code

            # Log response for debugging
            logging.debug(f"Row {row_num} - Response status: {resp.status_code}")
            logging.debug(f"Row {row_num} - Response body: {resp.text[:1000]}")

            # Check for success
            if resp.status_code == 200 and "<Fault" not in resp.text and "<fault" not in resp.text.lower():
                result["status"] = "SUCCESS"
                logging.info(f"Row {row_num} - SUCCESS - Receipt: {result['receipt_number']}")
                return result
            else:
                # Parse SOAP fault
                fault = extract_soap_fault_details(resp.text)

                # Check if error is retryable
                retryable_errors = ["timeout", "connection", "temporarily unavailable"]
                is_retryable = any(err in fault.lower() for err in retryable_errors)

                if is_retryable and attempt < max_retries - 1:
                    wait_time = retry_delay * (2 ** attempt)  # Exponential backoff
                    logging.warning(
                        f"Row {row_num} - Retryable error, waiting {wait_time}s "
                        f"before retry: {fault}"
                    )
                    time.sleep(wait_time)
                    continue
                else:
                    result["status"] = "SOAP_FAULT"
                    result["error"] = fault
                    logging.error(f"Row {row_num} - SOAP_FAULT - {fault}")
                    # Log full response for detailed analysis
                    logging.error(f"Row {row_num} - Full SOAP Response: {resp.text}")
                    return result

        except requests.exceptions.Timeout as exc:
            if attempt < max_retries - 1:
                wait_time = retry_delay * (2 ** attempt)
                logging.warning(f"Row {row_num} - Timeout, retrying in {wait_time}s: {str(exc)}")
                time.sleep(wait_time)
                continue
            else:
                result["status"] = "HTTP_ERROR"
                result["error"] = f"Timeout after {max_retries} attempts: {str(exc)}"
                logging.error(f"Row {row_num} - {result['error']}")
                return result

        except requests.exceptions.RequestException as exc:
            if attempt < max_retries - 1:
                wait_time = retry_delay * (2 ** attempt)
                logging.warning(f"Row {row_num} - HTTP error, retrying in {wait_time}s: {str(exc)}")
                time.sleep(wait_time)
                continue
            else:
                result["status"] = "HTTP_ERROR"
                result["error"] = f"HTTP error after {max_retries} attempts: {str(exc)}"
                logging.error(f"Row {row_num} - {result['error']}")
                return result

    # Should not reach here, but return error if it does
    result["status"] = "HTTP_ERROR"
    result["error"] = "Max retries exceeded"
    return result


def process_csv_file(
    csv_file_path: str,
    endpoint: str,
    username: str,
    password: str,
    max_retries: int = 3,
    retry_delay: float = 1.0,
    output_file: str = "results.csv"
) -> None:
    """
    Process a CSV file of receipts with validation and error handling.

    Args:
        csv_file_path: Path to input CSV file
        endpoint: Oracle Fusion SOAP endpoint URL
        username: Oracle Fusion username
        password: Oracle Fusion password
        max_retries: Maximum retry attempts per request (default: 3)
        retry_delay: Initial delay between retries in seconds (default: 1.0)
        output_file: Path to output results CSV file
    """
    logging.info(f"Starting batch processing from {csv_file_path}")
    logging.info(f"Endpoint: {endpoint}")
    logging.info(f"Max retries: {max_retries}, Retry delay: {retry_delay}s")

    # Read CSV file
    with open(csv_file_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    total_rows = len(rows)
    logging.info(f"Loaded {total_rows} rows from CSV")

    # Process each row
    results = []
    success_count = 0
    failed_count = 0

    for row_num, row in enumerate(rows, start=1):
        logging.info(f"Processing row {row_num}/{total_rows}")

        result = call_soap_api_with_validation(
            row=row,
            row_num=row_num,
            endpoint=endpoint,
            username=username,
            password=password,
            max_retries=max_retries,
            retry_delay=retry_delay
        )

        # Combine original row data with result
        result_row = {**row}
        result_row["Status"] = result["status"]
        result_row["HttpCode"] = result["http_code"]
        result_row["Error"] = result["error"]
        result_row["Attempts"] = result["attempts"]

        if result["validation_errors"]:
            result_row["ValidationErrors"] = "; ".join(result["validation_errors"])

        results.append(result_row)

        if result["status"] == "SUCCESS":
            success_count += 1
            logging.info(f"✅ Row {row_num} - SUCCESS")
        else:
            failed_count += 1
            logging.error(f"❌ Row {row_num} - {result['status']} - {result['error'][:100]}")

    # Write results to CSV
    if results:
        fieldnames = list(results[0].keys())
        with open(output_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(results)

        logging.info(f"\nResults written to {output_file}")

    # Summary
    logging.info(f"\n{'='*60}")
    logging.info(f"Processing complete!")
    logging.info(f"Total rows: {total_rows}")
    logging.info(f"Successful: {success_count}")
    logging.info(f"Failed: {failed_count}")
    logging.info(f"Success rate: {(success_count/total_rows*100):.2f}%")
    logging.info(f"{'='*60}")


if __name__ == "__main__":
    import sys

    # Example usage
    if len(sys.argv) < 5:
        print("Usage: python soap_validator.py <csv_file> <endpoint> <username> <password> [max_retries] [retry_delay]")
        print("\nExample:")
        print("  python soap_validator.py sample_receipts.csv \\")
        print("    https://your-fusion-instance.fa.em2.oraclecloud.com/fscmRestApi/... \\")
        print("    your_username your_password 3 1.0")
        sys.exit(1)

    csv_file = sys.argv[1]
    endpoint = sys.argv[2]
    username = sys.argv[3]
    password = sys.argv[4]
    max_retries = int(sys.argv[5]) if len(sys.argv) > 5 else 3
    retry_delay = float(sys.argv[6]) if len(sys.argv) > 6 else 1.0

    process_csv_file(
        csv_file_path=csv_file,
        endpoint=endpoint,
        username=username,
        password=password,
        max_retries=max_retries,
        retry_delay=retry_delay
    )
