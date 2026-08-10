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
import base64
import importlib.util
import json
import shutil
import tempfile
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

# Add project root to path for imports
project_root = Path('/app') if Path('/app').exists() else Path(__file__).resolve().parents[5]
sys.path.insert(0, str(project_root))
# When this script is executed by path, Python puts this services directory on
# sys.path, which shadows the standard library email package with services/email.
services_dir = str(Path(__file__).parent)
sys.path = [path for path in sys.path if path != services_dir]
if not Path('/app').exists():
    os.environ.setdefault('DOMAIN_SECURITY_CONFIG_DIR', services_dir)

# Import directly from the module file to avoid triggering __init__.py imports
# This prevents importing other services that may have dependency issues
domain_security_path = Path(__file__).parent / 'domain_security.py'
spec = importlib.util.spec_from_file_location("domain_security", domain_security_path)
domain_security_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(domain_security_module)
DomainSecurityService = domain_security_module.DomainSecurityService


def _canonical_policy_bytes(policy: dict) -> bytes:
    return (json.dumps(policy, sort_keys=True, separators=(',', ':')) + '\n').encode('utf-8')


def _legacy_policy() -> dict:
    service = DomainSecurityService()
    service.load_security_config()
    return {
        'allowed_domain': domain_security_module._ALLOWED_DOMAIN,
        'policy_version': 1,
        'restricted_domains': sorted(service.restricted_domains),
        'schema_version': 1,
        'suspicious_patterns': list(domain_security_module._SUSPICIOUS_PATTERNS),
    }


def _write_signed_policy(config_dir: Path, policy: dict, private_key: Ed25519PrivateKey) -> None:
    policy_bytes = _canonical_policy_bytes(policy)
    (config_dir / 'domain_security_policy.json').write_bytes(policy_bytes)
    signature = private_key.sign(policy_bytes)
    (config_dir / 'domain_security_policy.sig').write_text(
        base64.b64encode(signature).decode('ascii') + '\n',
        encoding='ascii',
    )


def _set_policy_public_key(private_key: Ed25519PrivateKey) -> None:
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    domain_security_module._DOMAIN_POLICY_PUBLIC_KEY_B64 = base64.b64encode(public_key).decode('ascii')


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
        print("\nFile paths:")
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
        ("user@research.google.com", True, "Google subdomain (should be blocked)"),
        ("user@labs.openai.com", True, "OpenAI subdomain (should be blocked)"),
        ("user@google.com.evil.test", False, "Lookalike suffix domain (should be allowed)"),
        ("user@notgoogle.com", False, "Prefix lookalike domain (should be allowed)"),
        
        # Allowed domain
        ("user@openmates.org", False, "Official OpenMates domain (should be allowed)"),
        
        # Platform-name checks apply to hosting validation, not signup emails.
        ("user@oopenmates.org", False, "Double 'o' variation email (should be allowed)"),
        ("user@0penmates.org", False, "Zero instead of 'o' email (should be allowed)"),
        ("user@openmates.com", False, "Different TLD email (should be allowed)"),
        ("user@open-mates.org", False, "Hyphenated variation email (should be allowed)"),
        
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
        ("research.google.com", True, "Google subdomain (should be blocked)"),
        ("labs.openai.com", True, "OpenAI subdomain (should be blocked)"),
        ("google.com.evil.test", False, "Lookalike suffix domain (should be allowed)"),
        ("notgoogle.com", False, "Prefix lookalike domain (should be allowed)"),
        
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
        ("research.google.com", True, "Subdomain of restricted domain"),
        ("google.com.evil.test", False, "Restricted name as prefix only"),
        ("notgoogle.com", False, "Restricted name without domain boundary"),
        
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


def test_runtime_integrity_tamper_detection():
    """Test that missing encrypted config after load fails closed."""
    print_header("TEST 5: Runtime Integrity Tamper Detection")

    source_dir = Path(os.getenv('DOMAIN_SECURITY_CONFIG_DIR', '/app/backend/core/api/app/services'))
    previous_config_dir = os.environ.get('DOMAIN_SECURITY_CONFIG_DIR')

    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            for file_name in [
                'domain_security_restricted.encrypted',
                'domain_security_allowed.encrypted',
                'domain_security_patterns.encrypted',
            ]:
                shutil.copy2(source_dir / file_name, tmp_path / file_name)

            os.environ['DOMAIN_SECURITY_CONFIG_DIR'] = str(tmp_path)
            service = DomainSecurityService()
            service.load_security_config()

            (tmp_path / 'domain_security_restricted.encrypted').unlink()
            is_allowed, reason = service.validate_email_domain('user@example.com')
            if is_allowed:
                print("✗ FAIL: Deleted restricted-domain file did not fail closed")
                return False
            print(f"✓ PASS: Deleted restricted-domain file failed closed: {reason}")

            is_allowed_after_failure, reason_after_failure = service.validate_email_domain('user@example.com')
            if is_allowed_after_failure:
                print("✗ FAIL: Integrity failure was not sticky")
                return False
            print(f"✓ PASS: Integrity failure remains sticky: {reason_after_failure}")
            return True
    finally:
        if previous_config_dir is None:
            os.environ.pop('DOMAIN_SECURITY_CONFIG_DIR', None)
        else:
            os.environ['DOMAIN_SECURITY_CONFIG_DIR'] = previous_config_dir


def test_signed_policy_compatibility():
    """Verify valid signed policy loading and fail-closed invalid bundles."""
    print_header("TEST 6: Signed Policy Compatibility")
    policy = _legacy_policy()
    private_key = Ed25519PrivateKey.generate()
    _set_policy_public_key(private_key)
    previous_config_dir = os.environ.get('DOMAIN_SECURITY_CONFIG_DIR')

    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            os.environ['DOMAIN_SECURITY_CONFIG_DIR'] = str(tmp_path)
            _write_signed_policy(tmp_path, policy, private_key)

            service = DomainSecurityService()
            if not service.load_security_config():
                print("✗ FAIL: Valid signed policy did not load")
                return False
            if service.restricted_domains != set(policy['restricted_domains']):
                print("✗ FAIL: Signed restricted domains changed")
                return False
            if service.validate_email_domain('user@google.com')[0]:
                print("✗ FAIL: Signed policy changed the blocked-domain response")
                return False
            if service.validate_email_domain('user@example.com') != (True, None):
                print("✗ FAIL: Signed policy changed the allowed-domain response")
                return False
            service.signed_policy_signature_path.unlink()
            service._last_integrity_check_at = 0.0
            if service.validate_email_domain('user@example.com')[0]:
                print("✗ FAIL: Signed policy tampering did not fail closed")
                return False

        invalid_policies = [
            {**policy, 'schema_version': 2},
            {**policy, 'restricted_domains': [*policy['restricted_domains'], 'bad_domain']},
            {**policy, 'suspicious_patterns': [*policy['suspicious_patterns'], '[']},
        ]
        for invalid_policy in invalid_policies:
            with tempfile.TemporaryDirectory() as tmp_dir:
                tmp_path = Path(tmp_dir)
                os.environ['DOMAIN_SECURITY_CONFIG_DIR'] = str(tmp_path)
                _write_signed_policy(tmp_path, invalid_policy, private_key)
                try:
                    DomainSecurityService().load_security_config()
                except SystemExit:
                    continue
                print(f"✗ FAIL: Invalid signed policy loaded: {invalid_policy}")
                return False

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            os.environ['DOMAIN_SECURITY_CONFIG_DIR'] = str(tmp_path)
            for legacy_name in (
                'domain_security_restricted.encrypted',
                'domain_security_allowed.encrypted',
                'domain_security_patterns.encrypted',
            ):
                shutil.copy2(Path(services_dir) / legacy_name, tmp_path / legacy_name)
            _write_signed_policy(tmp_path, policy, private_key)
            signature_path = tmp_path / 'domain_security_policy.sig'
            signature = bytearray(base64.b64decode(signature_path.read_text(encoding='ascii')))
            signature[0] ^= 1
            signature_path.write_text(base64.b64encode(signature).decode('ascii') + '\n')
            try:
                DomainSecurityService().load_security_config()
            except SystemExit:
                print("✓ PASS: Invalid signed bundle did not fall back to legacy files")
            else:
                print("✗ FAIL: Invalid signed bundle fell back to legacy files")
                return False

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            os.environ['DOMAIN_SECURITY_CONFIG_DIR'] = str(tmp_path)
            legacy_hashes = {}
            for legacy_name in (
                'domain_security_restricted.encrypted',
                'domain_security_allowed.encrypted',
                'domain_security_patterns.encrypted',
            ):
                source = Path(services_dir) / legacy_name
                destination = tmp_path / legacy_name
                shutil.copy2(source, destination)
                legacy_hashes[legacy_name] = destination.read_bytes()
            _write_signed_policy(tmp_path, policy, private_key)
            signed_service = DomainSecurityService()
            signed_service.load_security_config()
            if not signed_service._using_signed_policy:
                print("✗ FAIL: Mixed-version reader did not prefer the valid signed bundle")
                return False
            (tmp_path / 'domain_security_policy.json').unlink()
            (tmp_path / 'domain_security_policy.sig').unlink()
            legacy_service = DomainSecurityService()
            legacy_service.load_security_config()
            if legacy_service._using_signed_policy or legacy_service.restricted_domains != set(policy['restricted_domains']):
                print("✗ FAIL: Legacy rollback did not restore the unchanged policy")
                return False
            if any((tmp_path / name).read_bytes() != content for name, content in legacy_hashes.items()):
                print("✗ FAIL: Signed loading changed a legacy policy file")
                return False

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            os.environ['DOMAIN_SECURITY_CONFIG_DIR'] = str(tmp_path)
            (tmp_path / 'domain_security_policy.json').write_bytes(_canonical_policy_bytes(policy))
            try:
                DomainSecurityService().load_security_config()
            except SystemExit:
                print("✓ PASS: Partial signed bundle failed closed")
            else:
                print("✗ FAIL: Partial signed bundle did not fail closed")
                return False

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            os.environ['DOMAIN_SECURITY_CONFIG_DIR'] = str(tmp_path)
            noncanonical = json.dumps(policy, indent=2).encode('utf-8')
            (tmp_path / 'domain_security_policy.json').write_bytes(noncanonical)
            (tmp_path / 'domain_security_policy.sig').write_text(
                base64.b64encode(private_key.sign(noncanonical)).decode('ascii') + '\n',
                encoding='ascii',
            )
            try:
                DomainSecurityService().load_security_config()
            except SystemExit:
                print("✓ PASS: Non-canonical signed policy failed closed")
            else:
                print("✗ FAIL: Non-canonical signed policy loaded")
                return False

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            os.environ['DOMAIN_SECURITY_CONFIG_DIR'] = str(tmp_path)
            (tmp_path / 'domain_security_policy.json').write_bytes(b'{not-json')
            (tmp_path / 'domain_security_policy.sig').write_text(
                base64.b64encode(bytes(64)).decode('ascii') + '\n',
                encoding='ascii',
            )
            loads_calls = 0
            original_loads = domain_security_module.json.loads

            def tracked_loads(*args, **kwargs):
                nonlocal loads_calls
                loads_calls += 1
                return original_loads(*args, **kwargs)

            domain_security_module.json.loads = tracked_loads
            try:
                DomainSecurityService().load_security_config()
            except SystemExit:
                pass
            finally:
                domain_security_module.json.loads = original_loads
            if loads_calls != 0:
                print("✗ FAIL: Unverified signed policy bytes were parsed")
                return False

        print("✓ PASS: Signed policy compatibility and fail-closed cases")
        return True
    finally:
        if previous_config_dir is None:
            os.environ.pop('DOMAIN_SECURITY_CONFIG_DIR', None)
        else:
            os.environ['DOMAIN_SECURITY_CONFIG_DIR'] = previous_config_dir


def test_signing_tool_secret_boundary():
    """Verify canonical signing artifacts without writing private material."""
    print_header("TEST 7: Signing Tool Secret Boundary")
    signing_tool_path = project_root / 'scripts/sign_domain_security_policy.py'
    signing_spec = importlib.util.spec_from_file_location('sign_domain_security_policy', signing_tool_path)
    signing_module = importlib.util.module_from_spec(signing_spec)
    signing_spec.loader.exec_module(signing_module)
    private_key = Ed25519PrivateKey.generate()
    private_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    previous_private_key = os.environ.get('DOMAIN_SECURITY_SIGNING_PRIVATE_KEY_B64')
    try:
        os.environ['DOMAIN_SECURITY_SIGNING_PRIVATE_KEY_B64'] = base64.b64encode(private_bytes).decode('ascii')
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            policy_path = tmp_path / 'domain_security_policy.json'
            signature_path = tmp_path / 'domain_security_policy.sig'
            public_key_path = tmp_path / 'domain_security_policy.pub'
            policy = _legacy_policy()
            policy_path.write_text(json.dumps(policy, indent=2), encoding='utf-8')

            signing_module.sign_policy(policy_path, signature_path, public_key_path)

            if policy_path.read_bytes() != _canonical_policy_bytes(policy):
                print("✗ FAIL: Signing tool did not canonicalize policy JSON")
                return False
            if len(base64.b64decode(signature_path.read_text(encoding='ascii'))) != 64:
                print("✗ FAIL: Signing tool emitted an invalid signature")
                return False
            if len(base64.b64decode(public_key_path.read_text(encoding='ascii'))) != 32:
                print("✗ FAIL: Signing tool emitted an invalid public key")
                return False
            private_text = base64.b64encode(private_bytes).decode('ascii')
            if any(private_text in path.read_text(encoding='ascii') for path in tmp_path.iterdir()):
                print("✗ FAIL: Signing tool persisted private key material")
                return False
        print("✓ PASS: Signing tool emits canonical public artifacts only")
        return True
    finally:
        if previous_private_key is None:
            os.environ.pop('DOMAIN_SECURITY_SIGNING_PRIVATE_KEY_B64', None)
        else:
            os.environ['DOMAIN_SECURITY_SIGNING_PRIVATE_KEY_B64'] = previous_private_key


def main():
    """Run all tests."""
    print("\n" + "="*60)
    print("Domain Security Blocklist Test Suite")
    print("Running inside Docker container")
    print("="*60)
    
    # Print environment info
    print("\nEnvironment:")
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
    
    # Test 5: Runtime integrity tamper detection
    results.append(("Runtime Integrity Tamper Detection", test_runtime_integrity_tamper_detection()))

    # Test 6: Signed-policy compatibility and fail-closed loading
    results.append(("Signed Policy Compatibility", test_signed_policy_compatibility()))

    # Test 7: Protected signing tool secret boundary
    signing_tool_path = project_root / 'scripts/sign_domain_security_policy.py'
    if signing_tool_path.exists():
        results.append(("Signing Tool Secret Boundary", test_signing_tool_secret_boundary()))
    else:
        print("\nSKIP: Signing tool is intentionally not included in the API runtime image")
    
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
