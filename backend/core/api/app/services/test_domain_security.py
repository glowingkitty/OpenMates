#!/usr/bin/env python3
"""
Test script for domain security blocklist functionality.

This script is designed to run inside the Docker container via:
    docker exec <api_container> python /app/backend/core/api/app/services/test_domain_security.py

It tests:
1. Email domain validation (blocked domains should be rejected)
2. Allowed domains should pass
3. Suspicious patterns should be blocked
4. Configuration loading

Usage:
    docker exec api python /app/backend/core/api/app/services/test_domain_security.py
    
    Or use the helper script from project root:
    ./scripts/run_domain_security_tests.sh
"""

import sys
import os
import importlib.util
from pathlib import Path

# Add project root to path for imports
sys.path.insert(0, '/app')

# Import directly from the module file to avoid triggering __init__.py imports
# This prevents importing other services that may have dependency issues
import importlib.util
domain_security_path = Path(__file__).parent / 'domain_security.py'
spec = importlib.util.spec_from_file_location("domain_security", domain_security_path)
domain_security_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(domain_security_module)
DomainSecurityService = domain_security_module.DomainSecurityService


def print_header(title: str):
    """Print a formatted test section header."""
    print("\n" + "="*60)
    print(title)
    print("="*60)


def test_config_loading():
    """Test that encrypted configuration files can be loaded."""
    print_header("TEST 1: Configuration Loading")
    
    service = DomainSecurityService()
    
    try:
        service.load_security_config()
        print("✓ Configuration loaded successfully")
        
        # Check that data was loaded
        if not service.config_loaded:
            print("✗ Config loaded flag is not set")
            return False
        
        if not service.restricted_domains:
            print("✗ No restricted domains loaded")
            return False
        
        print(f"✓ Loaded {len(service.restricted_domains)} restricted domains")
        
        # Check module-level variables
        _ALLOWED_DOMAIN = domain_security_module._ALLOWED_DOMAIN
        _PLATFORM_NAME = domain_security_module._PLATFORM_NAME
        _SUSPICIOUS_PATTERNS = domain_security_module._SUSPICIOUS_PATTERNS
        
        if not _ALLOWED_DOMAIN:
            print("✗ Allowed domain not loaded")
            return False
        
        print(f"✓ Allowed domain loaded: {_ALLOWED_DOMAIN}")
        
        if not _PLATFORM_NAME:
            print("✗ Platform name not extracted")
            return False
        
        print(f"✓ Platform name extracted: {_PLATFORM_NAME}")
        
        if not _SUSPICIOUS_PATTERNS:
            print("✗ No suspicious patterns loaded")
            return False
        
        print(f"✓ Loaded {len(_SUSPICIOUS_PATTERNS)} suspicious patterns")
        
        # Print file paths for verification
        print(f"\nFile paths:")
        print(f"  Restricted: {service.restricted_domains_path}")
        print(f"  Allowed: {service.allowed_domain_path}")
        print(f"  Patterns: {service.suspicious_patterns_path}")
        
        return True
        
    except SystemExit as e:
        print(f"✗ SystemExit raised (server would not start): {e}")
        return False
    except Exception as e:
        print(f"✗ Failed to load configuration: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_email_domain_validation():
    """Test email domain validation for signup blocking."""
    print_header("TEST 2: Email Domain Validation")
    
    # Initialize service and load config
    service = DomainSecurityService()
    try:
        service.load_security_config()
    except Exception as e:
        print(f"✗ Failed to load security configuration: {e}")
        return False
    
    # Test cases: (email, should_be_blocked, description)
    test_cases = [
        # Blocked domains (from restricted_domains.txt)
        ("user@google.com", True, "Google domain (should be blocked)"),
        ("user@microsoft.com", True, "Microsoft domain (should be blocked)"),
        ("user@amazon.com", True, "Amazon domain (should be blocked)"),
        ("user@meta.com", True, "Meta domain (should be blocked)"),
        ("user@openai.com", True, "OpenAI domain (should be blocked)"),
        ("user@anthropic.com", True, "Anthropic domain (should be blocked)"),
        
        # Allowed domain
        ("user@openmates.org", False, "Official OpenMates domain (should be allowed)"),
        
        # Suspicious patterns (typosquatting)
        ("user@oopenmates.org", True, "Double 'o' variation (should be blocked)"),
        ("user@0penmates.org", True, "Zero instead of 'o' (should be blocked)"),
        ("user@openmates.com", True, "Different TLD (should be blocked)"),
        ("user@open-mates.org", True, "Hyphenated variation (should be blocked)"),
        
        # Normal domains (should be allowed)
        ("user@example.com", False, "Normal domain (should be allowed)"),
        ("user@test.org", False, "Test domain (should be allowed)"),
        ("user@university.edu", False, "University domain (should be allowed)"),
        ("user@smallcompany.com", False, "Small company domain (should be allowed)"),
    ]
    
    passed = 0
    failed = 0
    
    for email, should_be_blocked, description in test_cases:
        is_allowed, error_message = service.validate_email_domain(email)
        is_blocked = not is_allowed
        
        if is_blocked == should_be_blocked:
            print(f"✓ PASS: {description}")
            print(f"  Email: {email} -> Blocked: {is_blocked} (expected: {should_be_blocked})")
            passed += 1
        else:
            print(f"✗ FAIL: {description}")
            print(f"  Email: {email} -> Blocked: {is_blocked} (expected: {should_be_blocked})")
            if error_message:
                print(f"  Error: {error_message}")
            failed += 1
    
    print(f"\nResults: {passed} passed, {failed} failed")
    return failed == 0


def test_hosting_domain_validation():
    """Test hosting domain validation for server startup blocking."""
    print_header("TEST 3: Hosting Domain Validation")
    
    # Initialize service and load config
    service = DomainSecurityService()
    try:
        service.load_security_config()
    except Exception as e:
        print(f"✗ Failed to load security configuration: {e}")
        return False
    
    # Test cases: (domain, should_be_blocked, description)
    test_cases = [
        # Blocked domains
        ("google.com", True, "Google domain (should be blocked)"),
        ("microsoft.com", True, "Microsoft domain (should be blocked)"),
        ("amazon.com", True, "Amazon domain (should be blocked)"),
        ("openai.com", True, "OpenAI domain (should be blocked)"),
        
        # Allowed domain
        ("openmates.org", False, "Official OpenMates domain (should be allowed)"),
        
        # Suspicious patterns
        ("oopenmates.org", True, "Double 'o' variation (should be blocked)"),
        ("0penmates.org", True, "Zero instead of 'o' (should be blocked)"),
        ("openmates.com", True, "Different TLD (should be blocked)"),
        ("open-mates.org", True, "Hyphenated variation (should be blocked)"),
        
        # Normal domains
        ("example.com", False, "Normal domain (should be allowed)"),
        ("test.org", False, "Test domain (should be allowed)"),
        ("smallcompany.com", False, "Small company domain (should be allowed)"),
    ]
    
    passed = 0
    failed = 0
    
    for domain, should_be_blocked, description in test_cases:
        is_allowed, error_message = service.validate_hosting_domain(domain)
        is_blocked = not is_allowed
        
        if is_blocked == should_be_blocked:
            print(f"✓ PASS: {description}")
            print(f"  Domain: {domain} -> Blocked: {is_blocked} (expected: {should_be_blocked})")
            passed += 1
        else:
            print(f"✗ FAIL: {description}")
            print(f"  Domain: {domain} -> Blocked: {is_blocked} (expected: {should_be_blocked})")
            if error_message:
                print(f"  Error: {error_message}")
            failed += 1
    
    print(f"\nResults: {passed} passed, {failed} failed")
    return failed == 0


def test_domain_restriction_logic():
    """Test the is_domain_restricted method directly."""
    print_header("TEST 4: Domain Restriction Logic")
    
    service = DomainSecurityService()
    try:
        service.load_security_config()
    except Exception as e:
        print(f"✗ Failed to load security configuration: {e}")
        return False
    
    # Test cases: (domain, should_be_restricted, description)
    test_cases = [
        # Directly in restricted list
        ("google.com", True, "In restricted domains list"),
        ("microsoft.com", True, "In restricted domains list"),
        
        # Platform name variations
        ("openmates.org", False, "Official domain (allowed)"),
        ("oopenmates.org", True, "Typosquatting variation"),
        ("openmates.com", True, "Different TLD"),
        
        # Normal domains
        ("example.com", False, "Normal domain"),
        ("test.org", False, "Normal domain"),
    ]
    
    passed = 0
    failed = 0
    
    for domain, should_be_restricted, description in test_cases:
        is_restricted, reason = service.is_domain_restricted(domain)
        
        if is_restricted == should_be_restricted:
            print(f"✓ PASS: {description}")
            print(f"  Domain: {domain} -> Restricted: {is_restricted} (expected: {should_be_restricted})")
            if reason:
                print(f"  Reason: {reason}")
            passed += 1
        else:
            print(f"✗ FAIL: {description}")
            print(f"  Domain: {domain} -> Restricted: {is_restricted} (expected: {should_be_restricted})")
            if reason:
                print(f"  Reason: {reason}")
            failed += 1
    
    print(f"\nResults: {passed} passed, {failed} failed")
    return failed == 0


def main():
    """Run all tests."""
    print("\n" + "="*60)
    print("Domain Security Blocklist Test Suite")
    print("Running inside Docker container")
    print("="*60)
    
    # Print environment info
    print(f"\nEnvironment:")
    print(f"  Python: {sys.version}")
    print(f"  Working directory: {os.getcwd()}")
    print(f"  Config dir: {os.getenv('DOMAIN_SECURITY_CONFIG_DIR', '/app/backend/core/api/app/services')}")
    
    results = []
    
    # Test 1: Configuration loading
    results.append(("Configuration Loading", test_config_loading()))
    
    # Test 2: Email domain validation
    results.append(("Email Domain Validation", test_email_domain_validation()))
    
    # Test 3: Hosting domain validation
    results.append(("Hosting Domain Validation", test_hosting_domain_validation()))
    
    # Test 4: Domain restriction logic
    results.append(("Domain Restriction Logic", test_domain_restriction_logic()))
    
    # Summary
    print_header("TEST SUMMARY")
    
    all_passed = True
    for test_name, passed in results:
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"{status}: {test_name}")
        if not passed:
            all_passed = False
    
    print("\n" + "="*60)
    if all_passed:
        print("ALL TESTS PASSED ✓")
        return 0
    else:
        print("SOME TESTS FAILED ✗")
        return 1


if __name__ == '__main__':
    sys.exit(main())
