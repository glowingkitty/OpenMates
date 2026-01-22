#!/usr/bin/env python3
"""
CORS Configuration Test Script for OpenMates API
Tests both dev and production environments to compare CORS headers
"""

import requests
import sys
from typing import Dict

# Configuration
DEV_API = "https://api.dev.openmates.org"
PROD_API = "https://api.openmates.org"
DEV_ORIGIN = "https://app.dev.openmates.org"
PROD_ORIGIN = "https://openmates.org"

# Test endpoints
ENDPOINTS = [
    "/v1/auth/passkey/assertion/initiate",
    "/v1/settings/server-status",
    "/v1/auth/session",
]


def print_section(title: str):
    """Print a formatted section header"""
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


def print_subsection(title: str):
    """Print a formatted subsection header"""
    print("\n" + "-" * 60)
    print(title)
    print("-" * 60)


def test_options_preflight(api: str, origin: str, path: str, env: str) -> Dict:
    """Test OPTIONS preflight request"""
    url = f"{api}{path}"
    
    print_subsection(f"OPTIONS Preflight: {env} - {path}")
    print(f"URL: {url}")
    print(f"Origin: {origin}")
    
    try:
        response = requests.options(
            url,
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Content-Type",
            },
            timeout=10,
        )
        
        print(f"\nStatus Code: {response.status_code}")
        print("\nCORS Headers:")
        cors_headers = {
            "Access-Control-Allow-Origin": response.headers.get("Access-Control-Allow-Origin"),
            "Access-Control-Allow-Methods": response.headers.get("Access-Control-Allow-Methods"),
            "Access-Control-Allow-Headers": response.headers.get("Access-Control-Allow-Headers"),
            "Access-Control-Allow-Credentials": response.headers.get("Access-Control-Allow-Credentials"),
            "Access-Control-Max-Age": response.headers.get("Access-Control-Max-Age"),
        }
        
        for header, value in cors_headers.items():
            if value:
                print(f"  {header}: {value}")
            else:
                print(f"  {header}: ❌ MISSING")
        
        print("\nAll Response Headers:")
        for header, value in sorted(response.headers.items()):
            print(f"  {header}: {value}")
        
        return {
            "status_code": response.status_code,
            "cors_headers": cors_headers,
            "all_headers": dict(response.headers),
        }
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return {"error": str(e)}


def test_actual_request(api: str, origin: str, path: str, method: str, env: str) -> Dict:
    """Test actual GET/POST request"""
    url = f"{api}{path}"
    
    print_subsection(f"{method} Request: {env} - {path}")
    print(f"URL: {url}")
    print(f"Origin: {origin}")
    
    try:
        if method == "GET":
            response = requests.get(
                url,
                headers={"Origin": origin},
                timeout=10,
            )
        else:
            response = requests.post(
                url,
                headers={
                    "Origin": origin,
                    "Content-Type": "application/json",
                },
                json={},
                timeout=10,
            )
        
        print(f"\nStatus Code: {response.status_code}")
        print("\nCORS Headers:")
        cors_headers = {
            "Access-Control-Allow-Origin": response.headers.get("Access-Control-Allow-Origin"),
            "Access-Control-Allow-Credentials": response.headers.get("Access-Control-Allow-Credentials"),
            "Access-Control-Expose-Headers": response.headers.get("Access-Control-Expose-Headers"),
        }
        
        for header, value in cors_headers.items():
            if value:
                print(f"  {header}: {value}")
            else:
                print(f"  {header}: ❌ MISSING")
        
        print("\nAll Response Headers:")
        for header, value in sorted(response.headers.items()):
            print(f"  {header}: {value}")
        
        return {
            "status_code": response.status_code,
            "cors_headers": cors_headers,
            "all_headers": dict(response.headers),
        }
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return {"error": str(e)}


def compare_results(dev_result: Dict, prod_result: Dict, test_name: str):
    """Compare dev and production results"""
    print_subsection(f"Comparison: {test_name}")
    
    if "error" in dev_result or "error" in prod_result:
        print("❌ One or both tests failed - cannot compare")
        return
    
    dev_cors = dev_result.get("cors_headers", {})
    prod_cors = prod_result.get("cors_headers", {})
    
    print("\nCORS Header Comparison:")
    all_headers = set(list(dev_cors.keys()) + list(prod_cors.keys()))
    
    for header in sorted(all_headers):
        dev_val = dev_cors.get(header, "❌ MISSING")
        prod_val = prod_cors.get(header, "❌ MISSING")
        
        if dev_val == prod_val:
            print(f"  {header}: ✅ MATCH - {dev_val}")
        else:
            print(f"  {header}:")
            print(f"    DEV:  {dev_val}")
            print(f"    PROD: {prod_val}")


def main():
    """Main test function"""
    print_section("CORS Configuration Test - OpenMates API")
    
    dev_results = {}
    prod_results = {}
    
    # Test DEV environment
    print_section("TESTING DEV ENVIRONMENT")
    for endpoint in ENDPOINTS:
        print(f"\n🔍 Testing: {endpoint}")
        
        # Test OPTIONS
        dev_opt_key = f"{endpoint}_OPTIONS"
        dev_results[dev_opt_key] = test_options_preflight(
            DEV_API, DEV_ORIGIN, endpoint, "DEV"
        )
        
        # Test actual request (GET for server-status, POST for others)
        if "server-status" in endpoint:
            dev_act_key = f"{endpoint}_GET"
            dev_results[dev_act_key] = test_actual_request(
                DEV_API, DEV_ORIGIN, endpoint, "GET", "DEV"
            )
        else:
            dev_act_key = f"{endpoint}_POST"
            dev_results[dev_act_key] = test_actual_request(
                DEV_API, DEV_ORIGIN, endpoint, "POST", "DEV"
            )
    
    # Test PROD environment
    print_section("TESTING PRODUCTION ENVIRONMENT")
    for endpoint in ENDPOINTS:
        print(f"\n🔍 Testing: {endpoint}")
        
        # Test OPTIONS
        prod_opt_key = f"{endpoint}_OPTIONS"
        prod_results[prod_opt_key] = test_options_preflight(
            PROD_API, PROD_ORIGIN, endpoint, "PROD"
        )
        
        # Test actual request
        if "server-status" in endpoint:
            prod_act_key = f"{endpoint}_GET"
            prod_results[prod_act_key] = test_actual_request(
                PROD_API, PROD_ORIGIN, endpoint, "GET", "PROD"
            )
        else:
            prod_act_key = f"{endpoint}_POST"
            prod_results[prod_act_key] = test_actual_request(
                PROD_API, PROD_ORIGIN, endpoint, "POST", "PROD"
            )
    
    # Compare results
    print_section("COMPARISON SUMMARY")
    for key in dev_results.keys():
        if key in prod_results:
            compare_results(dev_results[key], prod_results[key], key)
    
    print_section("Test Complete")
    print("\nKey things to check:")
    print("1. ✅ OPTIONS requests should return Access-Control-Allow-Origin")
    print("2. ✅ Actual requests should return Access-Control-Allow-Origin")
    print("3. ✅ Headers should match the Origin sent (not wildcard *)")
    print("4. ✅ Access-Control-Allow-Credentials should be 'true' for webapp requests")
    print("5. ✅ DEV and PROD should have matching CORS headers")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)









