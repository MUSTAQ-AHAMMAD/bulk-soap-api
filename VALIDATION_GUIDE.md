# Oracle SOAP API Validation and Error Handling Guide

This guide explains the enhanced validation, error handling, and retry logic implemented to fix Oracle ADF validation errors (JBO-27024, JBO-27027).

## Overview

The codebase now includes comprehensive validation and error handling for Oracle Fusion SOAP API requests, specifically targeting the `createMiscellaneousReceipt` service.

## Key Features Implemented

### 1. Pre-Validation of Mandatory Fields

Before sending any SOAP request, the system validates all mandatory fields:

**Mandatory Fields:**
- `Amount` - Receipt amount (must be numeric)
- `CurrencyCode` - ISO currency code (e.g., SAR, USD)
- `ReceiptNumber` - Unique receipt identifier
- `ReceiptDate` - Date of receipt (YYYY-MM-DD format)
- `ReceiptMethodName` - Payment method name
- `ReceivableActivityName` - Activity name
- `BankAccountNumber` - Bank account number
- `OrgId` - Organization/Business Unit ID

**Additional Validation:**
- Date format validation (YYYY-MM-DD or YYYY/MM/DD)
- Amount numeric validation
- Empty/null field detection

### 2. Enhanced SOAP Fault Parsing

The system now extracts complete error details from Oracle SOAP faults:

**What it captures:**
- Full `<faultstring>` content
- Complete `<detail>` section
- All JBO error codes (JBO-27024, JBO-27027, etc.)
- Missing field information from "Missing [attribute/association]" messages
- Full error messages (not truncated)

**Example output:**
```
JBO-27024: Failed to validate a row with key oracle.jbo.Key[300000209350041] in MiscellaneousReceiptEO |
JBO-27027: Missing [CustomerAccountId] - Missing [CustomerAccountId]
```

### 3. Detailed Logging

All operations are logged to both console and `soap_processing.log`:

**Log levels:**
- `INFO` - Successful operations, processing status
- `WARNING` - Validation failures, retryable errors
- `ERROR` - SOAP faults, HTTP errors, missing fields
- `DEBUG` - Full request/response payloads

**Example log entries:**
```
2026-04-25 01:02:18 - WARNING - Row 5: Missing Amount - Receipt amount is required
2026-04-25 01:02:19 - ERROR - Row 10: SOAP Fault - JBO-27024: Failed to validate...
2026-04-25 01:02:20 - ERROR - Missing field info: Missing [CustomerAccountId]
```

### 4. Retry Logic with Exponential Backoff

Automatically retries failed requests with intelligent backoff:

**Retry Configuration:**
- `max_retries` - Number of retry attempts (default: 3)
- `retry_delay` - Initial delay between retries (default: 1.0 seconds)

**Backoff Strategy:**
- Attempt 1: Immediate
- Attempt 2: Wait 1 second (retry_delay × 2^0)
- Attempt 3: Wait 2 seconds (retry_delay × 2^1)
- Attempt 4: Wait 4 seconds (retry_delay × 2^2)

**Retryable Errors:**
- Timeout errors
- Connection errors
- "Temporarily unavailable" messages

**Non-Retryable Errors:**
- Validation errors (missing fields)
- JBO validation errors
- Authentication errors

### 5. Per-Row Error Reporting

Each row in the results includes detailed error information:

**Result Columns:**
- Original CSV columns (Amount, CurrencyCode, etc.)
- `Status` - SUCCESS | VALIDATION_ERROR | SOAP_FAULT | HTTP_ERROR
- `HttpCode` - HTTP response code
- `Error` - Detailed error message
- `ValidationErrors` - Semicolon-separated list of validation failures
- `Attempts` - Number of retry attempts made

## Usage

### Using the Web Application (main.py)

The FastAPI web application now includes all validation features:

```bash
python main.py
```

Then open http://localhost:8000 in your browser.

**New Configuration Options:**
- Max Retries (default: 3)
- Retry Delay (default: 1.0 seconds)

### Using the Standalone Script (soap_validator.py)

For command-line batch processing:

```bash
python soap_validator.py <csv_file> <endpoint> <username> <password> [max_retries] [retry_delay]
```

**Example:**
```bash
python soap_validator.py sample_receipts.csv \
  https://your-instance.oraclecloud.com/fscmRestApi/.../createMiscellaneousReceipt \
  myusername mypassword 3 1.0
```

**Output:**
- Results written to `results.csv`
- Detailed logs in `soap_validation.log`
- Console summary with success/failure counts

## Troubleshooting Common Errors

### JBO-27024: Failed to validate a row

**Cause:** Row-level validation failed in Oracle EO (Entity Object)

**Solution:**
1. Check the accompanying JBO-27027 message for missing fields
2. Review validation errors in the results CSV
3. Ensure all mandatory fields are populated

### JBO-27027: Missing [attribute/association]

**Cause:** Required field is null or missing

**Solution:**
1. Check ValidationErrors column in results
2. The missing field name is shown in brackets
3. Add the missing field to your CSV data

**Common missing fields:**
- `CustomerAccountId` - If processing customer receipts
- `BankBranchId` - If required by your configuration
- `RemittanceBankAccountId` - For certain payment methods

### Validation Errors Before API Call

**Cause:** Pre-validation detected missing/invalid data

**Solution:**
1. Review the ValidationErrors column
2. Fix the data in your CSV:
   - Ensure dates are in YYYY-MM-DD format
   - Ensure Amount is numeric
   - Fill all mandatory fields
3. Re-upload and process

## Best Practices

### 1. Data Preparation

✅ **Do:**
- Use consistent date formats (YYYY-MM-DD)
- Validate CSV data before uploading
- Include all mandatory fields
- Use valid Organization IDs

❌ **Don't:**
- Leave mandatory fields empty
- Use inconsistent date formats
- Include invalid characters in amounts
- Mix different business units in same batch

### 2. Error Handling

✅ **Do:**
- Review validation errors before submitting
- Check logs for detailed error messages
- Use retry logic for transient errors
- Export results for record-keeping

❌ **Don't:**
- Ignore validation warnings
- Retry non-retryable errors indefinitely
- Process large batches without testing first

### 3. Performance

✅ **Do:**
- Use concurrent mode for large batches
- Adjust delay based on API rate limits
- Monitor logs for performance issues
- Process in smaller batches if needed

❌ **Don't:**
- Set delay too low (may hit rate limits)
- Use too many workers (may overwhelm API)
- Process without monitoring progress

## Example Scenarios

### Scenario 1: Missing Receipt Date

**Input CSV:**
```csv
Amount,CurrencyCode,ReceiptNumber,ReceiptDate,ReceiptMethodName,...
-11.41,SAR,MISC-001,,Mada,...
```

**Result:**
```
Status: VALIDATION_ERROR
ValidationErrors: ReceiptDate (Receipt date is required)
Error: Validation failed: ReceiptDate (Receipt date is required)
```

**Fix:** Add the receipt date:
```csv
Amount,CurrencyCode,ReceiptNumber,ReceiptDate,ReceiptMethodName,...
-11.41,SAR,MISC-001,2026-03-05,Mada,...
```

### Scenario 2: Invalid Date Format

**Input CSV:**
```csv
ReceiptDate
03/05/2026
```

**Result:**
```
Status: VALIDATION_ERROR
ValidationErrors: ReceiptDate (Invalid date format, expected YYYY-MM-DD)
```

**Fix:** Use YYYY-MM-DD format:
```csv
ReceiptDate
2026-03-05
```

### Scenario 3: Missing Oracle Field (JBO-27027)

**SOAP Response:**
```xml
<faultstring>oracle.jbo.RowCreateException</faultstring>
<detail>
  JBO-27024: Failed to validate a row with key oracle.jbo.Key[300000209350041]
  JBO-27027: Missing [CustomerAccountId]
</detail>
```

**Result:**
```
Status: SOAP_FAULT
Error: JBO-27024: Failed to validate a row with key oracle.jbo.Key[300000209350041] |
       JBO-27027: Missing [CustomerAccountId] - Missing [CustomerAccountId]
```

**Fix:**
1. Add CustomerAccountId to your CSV columns
2. Update the SOAP payload builder in `build_soap_payload()` to include:
```python
<misc:CustomerAccountId>{row.get("CustomerAccountId", "")}</misc:CustomerAccountId>
```

## API Reference

### validate_mandatory_fields(row, row_num)

Pre-validates a row before SOAP request.

**Parameters:**
- `row` (dict): CSV row data
- `row_num` (int): Row number for logging

**Returns:**
- `(is_valid, missing_fields)` - Tuple with validation status and list of errors

### extract_soap_fault_details(xml_text)

Extracts full error details from SOAP fault response.

**Parameters:**
- `xml_text` (str): SOAP response XML

**Returns:**
- `str` - Formatted error message with all JBO codes and missing field info

### call_soap_api_with_validation(row, row_num, endpoint, username, password, max_retries, retry_delay)

Sends SOAP request with validation and retry logic.

**Parameters:**
- `row` (dict): CSV row data
- `row_num` (int): Row number
- `endpoint` (str): SOAP endpoint URL
- `username` (str): Oracle username
- `password` (str): Oracle password
- `max_retries` (int): Maximum retry attempts
- `retry_delay` (float): Initial retry delay

**Returns:**
- `dict` - Result dictionary with status, errors, and validation info

## Log File Analysis

### Finding Validation Errors

```bash
grep "VALIDATION_ERROR" soap_processing.log
```

### Finding Missing Fields

```bash
grep "Missing field info" soap_processing.log
```

### Finding SOAP Faults

```bash
grep "SOAP_FAULT" soap_processing.log
```

### Finding Retry Attempts

```bash
grep "Attempt" soap_processing.log
```

## Support and Debugging

### Enable Debug Logging

In your script, change the logging level:

```python
logging.basicConfig(
    level=logging.DEBUG,  # Changed from INFO
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('soap_processing.log'),
        logging.StreamHandler()
    ]
)
```

### View Full SOAP Responses

Debug logs include complete SOAP request/response payloads for analysis.

### Test Individual Receipts

Use the standalone script with a single-row CSV to test problematic receipts:

```bash
python soap_validator.py single_receipt.csv ... 1 0
```

(max_retries=1, retry_delay=0 for quick testing)

## Version History

### Version 2.0 (Current)
- ✅ Pre-validation of mandatory fields
- ✅ Enhanced SOAP fault parsing (full JBO errors)
- ✅ Detailed logging with file output
- ✅ Retry logic with exponential backoff
- ✅ Per-row validation error reporting
- ✅ Standalone validator script
- ✅ Missing field detection and reporting

### Version 1.0
- Basic SOAP request processing
- Simple fault string extraction
- Sequential/concurrent processing
- Web UI with WebSocket progress
