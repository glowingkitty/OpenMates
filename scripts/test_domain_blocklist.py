#!/usr/bin/env python3
"""
Test script for domain security blocklist functionality.

This script tests:
1. Email domain validation (blocked domains should be rejected)
2. Allowed domains should pass
3. Suspicious patterns should be blocked
4. Server startup validation (simulated)

Usage:
    python scripts/test_domain_blocklist.py
"""

import sys
from pathlib import Path

# Add project root to path for imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from backend.core.api.app.services.domain_security import DomainSecurityService  # noqa: E402


def test_email_domain_validation():
    """Test email domain validation for signup blocking."""
    print("\n" + "="*60)
    print("TEST 1: Email Domain Validation")
    print("="*60)
    
    # Initialize service and load config
    service = DomainSecurityService()
    try:
        service.load_security_config()
        print("✓ Security configuration loaded successfully")
    except Exception as e:
        print(f"✗ Failed to load security configuration: {e}")
        return False
    
    # Test cases: (email, should_be_blocked, description)
    test_cases = [
        # Blocked domains (from restricted_domains.txt - using first few as examples)
        ("user@google.com", True, "Google domain (should be blocked)"),
        ("user@microsoft.com", True, "Microsoft domain (should be blocked)"),
        ("user@amazon.com", True, "Amazon domain (should be blocked)"),
        ("user@meta.com", True, "Meta domain (should be blocked)"),
        ("user@openai.com", True, "OpenAI domain (should be blocked)"),
        
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
    print("\n" + "="*60)
    print("TEST 2: Hosting Domain Validation")
    print("="*60)
    
    # Initialize service and load config
    service = DomainSecurityService()
    try:
        service.load_security_config()
        print("✓ Security configuration loaded successfully")
    except Exception as e:
        print(f"✗ Failed to load security configuration: {e}")
        return False
    
    # Test cases: (domain, should_be_blocked, description)
    test_cases = [
        # Blocked domains
        ("google.com", True, "Google domain (should be blocked)"),
        ("microsoft.com", True, "Microsoft domain (should be blocked)"),
        ("amazon.com", True, "Amazon domain (should be blocked)"),
        
        # Allowed domain
        ("openmates.org", False, "Official OpenMates domain (should be allowed)"),
        
        # Suspicious patterns
        ("oopenmates.org", True, "Double 'o' variation (should be blocked)"),
        ("0penmates.org", True, "Zero instead of 'o' (should be blocked)"),
        ("openmates.com", True, "Different TLD (should be blocked)"),
        
        # Normal domains
        ("example.com", False, "Normal domain (should be allowed)"),
        ("test.org", False, "Test domain (should be allowed)"),
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


def test_config_loading():
    """Test that encrypted configuration files can be loaded."""
    print("\n" + "="*60)
    print("TEST 3: Configuration Loading")
    print("="*60)
    
    service = DomainSecurityService()
    
    try:
        service.load_security_config()
        print("✓ Configuration loaded successfully")
        
        # Check that data was loaded
        if service.config_loaded:
            print("✓ Config loaded flag is set")
        else:
            print("✗ Config loaded flag is not set")
            return False
        
        if service.restricted_domains:
            print(f"✓ Loaded {len(service.restricted_domains)} restricted domains")
        else:
            print("✗ No restricted domains loaded")
            return False
        
        # Check module-level variables
        from backend.core.api.app.services.domain_security import _ALLOWED_DOMAIN, _PLATFORM_NAME, _SUSPICIOUS_PATTERNS
        
        if _ALLOWED_DOMAIN:
            print(f"✓ Allowed domain loaded: {_ALLOWED_DOMAIN}")
        else:
            print("✗ Allowed domain not loaded")
            return False
        
        if _PLATFORM_NAME:
            print(f"✓ Platform name extracted: {_PLATFORM_NAME}")
        else:
            print("✗ Platform name not extracted")
            return False
        
        if _SUSPICIOUS_PATTERNS:
            print(f"✓ Loaded {len(_SUSPICIOUS_PATTERNS)} suspicious patterns")
        else:
            print("✗ No suspicious patterns loaded")
            return False
        
        return True
        
    except SystemExit as e:
        print(f"✗ SystemExit raised (server would not start): {e}")
        return False
    except Exception as e:
        print(f"✗ Failed to load configuration: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_missing_files():
    """Test that missing encrypted files cause SystemExit."""
    print("\n" + "="*60)
    print("TEST 4: Missing Files Handling")
    print("="*60)
    
    service = DomainSecurityService()
    
    # Temporarily rename files to simulate missing files
    import shutil
    from pathlib import Path
    
    restricted_path = service.restricted_domains_path
    allowed_path = service.allowed_domain_path
    patterns_path = service.suspicious_patterns_path
    
    backup_dir = Path("/tmp/domain_security_backup")
    backup_dir.mkdir(exist_ok=True)
    
    try:
        # Backup and remove files
        if restricted_path.exists():
            shutil.move(str(restricted_path), str(backup_dir / "restricted.encrypted"))
        if allowed_path.exists():
            shutil.move(str(allowed_path), str(backup_dir / "allowed.encrypted"))
        if patterns_path.exists():
            shutil.move(str(patterns_path), str(backup_dir / "patterns.encrypted"))
        
        # Try to load config - should raise SystemExit
        try:
            service.load_security_config()
            print("✗ FAIL: Should have raised SystemExit for missing files")
            return False
        except SystemExit:
            print("✓ PASS: SystemExit raised correctly for missing files")
            return True
        except Exception as e:
            print(f"✗ FAIL: Wrong exception raised: {e}")
            return False
    finally:
        # Restore files
        if (backup_dir / "restricted.encrypted").exists():
            shutil.move(str(backup_dir / "restricted.encrypted"), str(restricted_path))
        if (backup_dir / "allowed.encrypted").exists():
            shutil.move(str(backup_dir / "allowed.encrypted"), str(allowed_path))
        if (backup_dir / "patterns.encrypted").exists():
            shutil.move(str(backup_dir / "patterns.encrypted"), str(patterns_path))


def main():
    """Run all tests."""
    print("\n" + "="*60)
    print("Domain Security Blocklist Test Suite")
    print("="*60)
    
    results = []
    
    # Test 1: Configuration loading
    results.append(("Configuration Loading", test_config_loading()))
    
    # Test 2: Email domain validation
    results.append(("Email Domain Validation", test_email_domain_validation()))
    
    # Test 3: Hosting domain validation
    results.append(("Hosting Domain Validation", test_hosting_domain_validation()))
    
    # Test 4: Missing files (optional - may be skipped if files are needed)
    # Uncomment to test missing files handling:
    # results.append(("Missing Files Handling", test_missing_files()))
    
    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    
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
