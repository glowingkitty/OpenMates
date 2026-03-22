#!/usr/bin/env python3
"""
Test GetDocsResponse serialization to see if that's where the documentation is being lost.
"""

import sys
import os
import json

sys.path.insert(0, "/app" if os.path.exists("/app") else os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from backend.apps.code.skills.get_docs_skill import GetDocsResponse

# Test 1: Create a GetDocsResponse with documentation
print("Test 1: Creating GetDocsResponse with documentation")
response = GetDocsResponse(
    library={
        "id": "/stripe/stripe-js",
        "title": "Stripe.js",
        "description": "Test description"
    },
    documentation="This is test documentation content",
    source="context7",
    error=None
)

print(f"Response object: {response}")
print(f"Response.documentation: {repr(response.documentation)}")
print(f"Response.documentation type: {type(response.documentation)}")
print(f"Response.documentation length: {len(response.documentation) if response.documentation else 0}")

# Test 2: Convert to dict
print("\nTest 2: Converting to dict using model_dump()")
response_dict = response.model_dump()
print(f"response_dict['documentation']: {repr(response_dict.get('documentation'))}")
print(f"response_dict['documentation'] type: {type(response_dict.get('documentation'))}")
print(f"response_dict['documentation'] length: {len(response_dict.get('documentation')) if response_dict.get('documentation') else 0}")

# Test 3: Convert to JSON
print("\nTest 3: Converting to JSON")
response_json = response.model_dump_json()
print(f"JSON: {response_json}")
parsed = json.loads(response_json)
print(f"Parsed JSON['documentation']: {repr(parsed.get('documentation'))}")

# Test 4: Test with empty string (should work)
print("\nTest 4: Creating GetDocsResponse with empty string documentation")
response_empty = GetDocsResponse(
    library={"id": "/test/test", "title": "Test"},
    documentation="",
    source="context7",
    error=None
)
print(f"Empty response.documentation: {repr(response_empty.documentation)}")
print(f"Empty response_dict['documentation']: {repr(response_empty.model_dump().get('documentation'))}")

# Test 5: Check if None vs empty string handling
print("\nTest 5: Checking field defaults")
print(f"GetDocsResponse documentation field default: {GetDocsResponse.__fields__['documentation'].default if hasattr(GetDocsResponse, '__fields__') else 'N/A'}")
print(f"GetDocsResponse documentation field info: {GetDocsResponse.model_fields.get('documentation') if hasattr(GetDocsResponse, 'model_fields') else 'N/A'}")
