#!/usr/bin/env python3
"""
Example script demonstrating how to use the SOAP validator with test data.
This shows the validation and error handling capabilities without making actual API calls.
"""

import sys
import os

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from soap_validator import (
    validate_mandatory_fields,
    extract_soap_fault_details,
    build_soap_payload,
    MANDATORY_FIELDS
)


def demo_validation():
    """Demonstrate field validation with various test cases."""
    print("=" * 70)
    print("DEMO: Field Validation")
    print("=" * 70)

    test_cases = [
        {
            "name": "Valid Receipt",
            "row": {
                "Amount": "-11.41",
                "CurrencyCode": "SAR",
                "ReceiptNumber": "MISC-TEST-001",
                "ReceiptDate": "2026-03-05",
                "DepositDate": "2026-03-05",
                "GlDate": "2026-03-05",
                "ReceiptMethodName": "Mada",
                "ReceivableActivityName": "Bank Charge",
                "BankAccountNumber": "157-95017321-TEST",
                "OrgId": "300000001421038"
            }
        },
        {
            "name": "Missing Amount",
            "row": {
                "Amount": "",
                "CurrencyCode": "SAR",
                "ReceiptNumber": "MISC-TEST-002",
                "ReceiptDate": "2026-03-05",
                "ReceiptMethodName": "Mada",
                "ReceivableActivityName": "Bank Charge",
                "BankAccountNumber": "157-95017321-TEST",
                "OrgId": "300000001421038"
            }
        },
        {
            "name": "Invalid Date Format",
            "row": {
                "Amount": "-25.00",
                "CurrencyCode": "SAR",
                "ReceiptNumber": "MISC-TEST-003",
                "ReceiptDate": "03/05/2026",  # Wrong format
                "ReceiptMethodName": "Mada",
                "ReceivableActivityName": "Bank Charge",
                "BankAccountNumber": "157-95017321-TEST",
                "OrgId": "300000001421038"
            }
        },
        {
            "name": "Invalid Amount",
            "row": {
                "Amount": "abc",  # Not a number
                "CurrencyCode": "SAR",
                "ReceiptNumber": "MISC-TEST-004",
                "ReceiptDate": "2026-03-05",
                "ReceiptMethodName": "Mada",
                "ReceivableActivityName": "Bank Charge",
                "BankAccountNumber": "157-95017321-TEST",
                "OrgId": "300000001421038"
            }
        },
        {
            "name": "Multiple Missing Fields",
            "row": {
                "Amount": "-30.00",
                "CurrencyCode": "SAR",
                "ReceiptNumber": "",
                "ReceiptDate": "",
                "ReceiptMethodName": "",
                "ReceivableActivityName": "Bank Charge",
                "BankAccountNumber": "157-95017321-TEST",
                "OrgId": "300000001421038"
            }
        }
    ]

    for i, test_case in enumerate(test_cases, start=1):
        print(f"\n{i}. Test Case: {test_case['name']}")
        print("-" * 70)

        is_valid, missing_fields = validate_mandatory_fields(test_case["row"], i)

        if is_valid:
            print("   ✅ Status: VALID")
            print("   All mandatory fields present and valid")
        else:
            print("   ❌ Status: VALIDATION ERROR")
            print(f"   Missing/Invalid fields: {len(missing_fields)}")
            for field in missing_fields:
                print(f"      - {field}")


def demo_soap_fault_parsing():
    """Demonstrate SOAP fault parsing with various error types."""
    print("\n\n" + "=" * 70)
    print("DEMO: SOAP Fault Parsing")
    print("=" * 70)

    fault_examples = [
        {
            "name": "JBO-27024 with Missing Field",
            "xml": """<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <soap:Fault>
      <faultcode>soap:Server</faultcode>
      <faultstring>oracle.jbo.RowCreateException</faultstring>
      <detail>
        <ns1:ServiceErrorMessage xmlns:ns1="http://xmlns.oracle.com/adf/svc/errors/">
          <ns1:detail>JBO-27024: Failed to validate a row with key oracle.jbo.Key[300000209350041] in MiscellaneousReceiptEO
JBO-27027: Missing [CustomerAccountId]</ns1:detail>
        </ns1:ServiceErrorMessage>
      </detail>
    </soap:Fault>
  </soap:Body>
</soap:Envelope>"""
        },
        {
            "name": "Authentication Error",
            "xml": """<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <soap:Fault>
      <faultcode>soap:Client</faultcode>
      <faultstring>Authentication failed</faultstring>
      <detail>Invalid username or password</detail>
    </soap:Fault>
  </soap:Body>
</soap:Envelope>"""
        },
        {
            "name": "Multiple JBO Errors",
            "xml": """<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <soap:Fault>
      <faultcode>soap:Server</faultcode>
      <faultstring>oracle.jbo.ValidationException</faultstring>
      <detail>
        JBO-27024: Failed to validate a row with key oracle.jbo.Key[300000209349053]
        JBO-27027: Missing [ReceiptMethodId]
        JBO-35007: Attribute value is too long for ActivityName
      </detail>
    </soap:Fault>
  </soap:Body>
</soap:Envelope>"""
        }
    ]

    for i, example in enumerate(fault_examples, start=1):
        print(f"\n{i}. Fault Type: {example['name']}")
        print("-" * 70)

        parsed_error = extract_soap_fault_details(example["xml"])
        print(f"   Parsed Error: {parsed_error}")


def demo_soap_payload():
    """Demonstrate SOAP payload generation."""
    print("\n\n" + "=" * 70)
    print("DEMO: SOAP Payload Generation")
    print("=" * 70)

    test_row = {
        "Amount": "-11.41",
        "CurrencyCode": "SAR",
        "ReceiptNumber": "MISC-DEMO-001",
        "ReceiptDate": "2026-03-05",
        "DepositDate": "2026-03-05",
        "GlDate": "2026-03-05",
        "ReceiptMethodName": "Mada",
        "ReceivableActivityName": "Bank Charge",
        "BankAccountNumber": "157-95017321-TEST",
        "OrgId": "300000001421038"
    }

    payload = build_soap_payload(test_row)

    print("\nGenerated SOAP Envelope:")
    print("-" * 70)
    print(payload)


def demo_mandatory_fields():
    """Display all mandatory fields."""
    print("\n\n" + "=" * 70)
    print("DEMO: Mandatory Fields Reference")
    print("=" * 70)

    print(f"\nTotal Mandatory Fields: {len(MANDATORY_FIELDS)}")
    print("\nField List:")
    for i, (field, description) in enumerate(MANDATORY_FIELDS.items(), start=1):
        print(f"  {i}. {field:25s} - {description}")


def main():
    """Run all demos."""
    print("\n")
    print("╔" + "═" * 68 + "╗")
    print("║" + " " * 10 + "Oracle SOAP API Validator - Feature Demo" + " " * 16 + "║")
    print("╚" + "═" * 68 + "╝")

    # Run all demos
    demo_mandatory_fields()
    demo_validation()
    demo_soap_fault_parsing()
    demo_soap_payload()

    print("\n\n" + "=" * 70)
    print("DEMO COMPLETE")
    print("=" * 70)
    print("\nNext Steps:")
    print("1. Review VALIDATION_GUIDE.md for detailed documentation")
    print("2. Prepare your CSV file with all mandatory fields")
    print("3. Run: python soap_validator.py your_file.csv endpoint user pass")
    print("4. Review results.csv and soap_validation.log for details")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    main()
