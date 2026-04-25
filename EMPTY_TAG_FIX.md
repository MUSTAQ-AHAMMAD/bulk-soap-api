# Fix: Oracle Fusion Empty XML Tag Validation Errors

## Problem Statement

Even after implementing field validation and consistent value normalization, the application continued to receive JBO-27014 validation errors from Oracle Fusion:

```
JBO-27014: Attribute Amount in MiscellaneousReceiptEO is required.
JBO-27014: Attribute CurrencyCode in MiscellaneousReceiptEO is required.
JBO-27014: Attribute OrgId in MiscellaneousReceiptEO is required.
```

## Root Cause

The issue was that **empty XML tags were being sent to Oracle Fusion**, even though validation was catching empty values. Oracle Fusion treats empty XML tags as "present but invalid" rather than "absent", which triggers validation errors for required fields.

### Example of Problematic XML

```xml
<types:miscellaneousReceipt>
  <misc:Amount></misc:Amount>           <!-- Empty tag - Oracle rejects this -->
  <misc:CurrencyCode></misc:CurrencyCode>  <!-- Empty tag - Oracle rejects this -->
  <misc:ReceiptNumber>TEST-001</misc:ReceiptNumber>
  <misc:OrgId></misc:OrgId>             <!-- Empty tag - Oracle rejects this -->
</types:miscellaneousReceipt>
```

### Why This Happened

1. **Pre-validation caught empty values** and returned VALIDATION_ERROR
2. **But if validation was bypassed or data changed**, empty values would be converted to empty strings
3. **Empty strings in f-string templates** produced empty XML tags: `<misc:Amount>{""}</misc:Amount>`
4. **Oracle Fusion interpreted empty tags** as malformed required fields

## Solution

Modified `build_soap_payload()` to **conditionally include XML elements only when values are non-empty**. Empty or missing fields are completely omitted from the XML rather than sent as empty tags.

### Implementation

Added a new helper function `xml_element()` that:
1. Gets and normalizes the field value
2. Checks if the value is non-empty
3. Returns the complete XML element if value exists
4. Returns empty string if value is empty (effectively omitting the tag)

```python
def xml_element(tag_name: str, field_name: str, is_date: bool = False) -> str:
    value = get_field(field_name)
    if is_date:
        value = normalize_date(value)
    # Only include the XML element if there's a non-empty value
    if value:
        return f"\n        <misc:{tag_name}>{value}</misc:{tag_name}>"
    return ""
```

### Files Modified

1. `/home/runner/work/bulk-soap-api/bulk-soap-api/main.py` (lines 128-166)
2. `/home/runner/work/bulk-soap-api/bulk-soap-api/soap_validator.py` (lines 83-121)

## Behavior Comparison

### Before Fix

```xml
<!-- Empty fields produced empty tags -->
<types:miscellaneousReceipt>
  <misc:Amount></misc:Amount>
  <misc:CurrencyCode></misc:CurrencyCode>
  <misc:ReceiptNumber>TEST-001</misc:ReceiptNumber>
  <misc:ReceiptDate>2026-03-05</misc:ReceiptDate>
  <misc:OrgId></misc:OrgId>
</types:miscellaneousReceipt>

Result: Oracle rejects with JBO-27014 errors
```

### After Fix

```xml
<!-- Empty fields are completely omitted -->
<types:miscellaneousReceipt>
  <misc:ReceiptNumber>TEST-001</misc:ReceiptNumber>
  <misc:ReceiptDate>2026-03-05</misc:ReceiptDate>
</types:miscellaneousReceipt>

Result: Validation catches missing required fields before sending to Oracle
```

## Test Results

### Test 1: Valid Data ✅
**Input**: All required fields populated
```python
{
    "Amount": "-11.41",
    "CurrencyCode": "SAR",
    "ReceiptNumber": "TEST-001",
    "ReceiptDate": "2026-03-05",
    "OrgId": "300000001421038"
}
```

**Output**: All XML tags included
```xml
<misc:Amount>-11.41</misc:Amount>
<misc:CurrencyCode>SAR</misc:CurrencyCode>
<misc:ReceiptNumber>TEST-001</misc:ReceiptNumber>
<misc:ReceiptDate>2026-03-05</misc:ReceiptDate>
<misc:OrgId>300000001421038</misc:OrgId>
```

### Test 2: Empty Required Fields ✅
**Input**: Missing Amount, CurrencyCode, OrgId
```python
{
    "Amount": "",
    "CurrencyCode": "   ",  # whitespace
    "ReceiptNumber": "TEST-002",
    "ReceiptDate": "2026-03-05",
    "OrgId": None
}
```

**Output**: Empty fields completely omitted
```xml
<misc:ReceiptNumber>TEST-002</misc:ReceiptNumber>
<misc:ReceiptDate>2026-03-05</misc:ReceiptDate>
```

**Validation**: Catches missing fields before API call

### Test 3: Partial Data ✅
**Input**: Some optional fields empty
```python
{
    "Amount": "-25.00",
    "CurrencyCode": "SAR",
    "ReceiptNumber": "TEST-003",
    "ReceiptDate": "2026-03-05",
    "DepositDate": "",  # empty optional
    "OrgId": "300000001421038"
}
```

**Output**: Only populated fields included
```xml
<misc:Amount>-25.00</misc:Amount>
<misc:CurrencyCode>SAR</misc:CurrencyCode>
<misc:ReceiptNumber>TEST-003</misc:ReceiptNumber>
<misc:ReceiptDate>2026-03-05</misc:ReceiptDate>
<misc:OrgId>300000001421038</misc:OrgId>
```

## Benefits

1. **Prevents Oracle JBO-27014 Errors**: Empty required fields no longer sent as empty tags
2. **SOAP Best Practice**: Following standard SOAP pattern of omitting optional/empty elements
3. **Cleaner XML**: Smaller payloads without unnecessary empty tags
4. **Validation Still Works**: Pre-validation catches empty required fields
5. **Backward Compatible**: Valid data works exactly as before

## Defense in Depth

This fix provides **two layers of protection**:

1. **Layer 1 - Pre-validation**: `validate_mandatory_fields()` catches empty required fields and returns VALIDATION_ERROR
2. **Layer 2 - Payload Building**: `build_soap_payload()` omits empty fields entirely from XML

Even if validation is somehow bypassed, Oracle will still receive valid XML without empty tags.

## Related Issues

This fix addresses the persistent JBO-27014 errors that were occurring despite previous validation improvements:
- JBO-27024: Failed to validate a row
- JBO-27027: Missing mandatory attributes
- JBO-27014: Attribute X is required

## Version Information

- **Fix Applied**: 2026-04-25
- **Commit**: 92a2230
- **Branch**: claude/fix-required-attributes-misc-receipt
- **Files Changed**: main.py, soap_validator.py

## Related Documentation

- [FIX_SUMMARY.md](FIX_SUMMARY.md) - Previous validation consistency fix
- [VALIDATION_GUIDE.md](VALIDATION_GUIDE.md) - Complete validation guide
- [README.md](README.md) - Application overview
