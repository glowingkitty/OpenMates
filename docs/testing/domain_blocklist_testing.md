# Domain Blocklist Testing Guide

This guide explains how to test the domain security blocklist functionality for both email signup and self-hosting scenarios.

## Overview

The domain blocklist system:
- Blocks email signups from restricted domains
- Prevents server startup on restricted domains
- Detects typosquatting variations of "openmates"
- Only allows `openmates.org` as the official domain

## Prerequisites

1. **Encrypted files must exist**: Run the encryption script first:
   ```bash
   python scripts/encrypt_domain_security.py \
       --restricted-input restricted_domains.txt \
       --allowed-input allowed_domain.txt \
       --patterns-input suspicious_patterns.txt
   ```

2. **Server must be running** (for API endpoint tests)

## Testing Methods

### Method 1: Docker-Based Test Script (Recommended)

Run the comprehensive test script inside the Docker container:

```bash
# Using the helper script (from project root)
./scripts/run_domain_security_tests.sh

# Or directly with docker exec
docker exec api python /app/backend/core/api/app/services/test_domain_security.py
```

This script tests:
- Configuration loading from encrypted files
- Email domain validation (blocked vs allowed)
- Hosting domain validation
- Domain restriction logic
- Edge cases

**Note**: This method is recommended because it:
- Runs in the actual runtime environment
- Uses the correct Docker paths (`/app/backend/...`)
- Has all dependencies available
- Tests the exact configuration that the server uses

### Method 2: Manual API Testing

#### Test Email Signup Blocking

Use `curl` or a REST client to test the email signup endpoint:

```bash
# Test blocked domain (should fail)
curl -X POST http://localhost:8000/v1/auth/request_confirm_email_code \
  -H "Content-Type: application/json" \
  -H "Origin: http://localhost:5173" \
  -d '{
    "email": "user@google.com",
    "hashed_email": "test_hash",
    "invite_code": "",
    "language": "en",
    "darkmode": false
  }'

# Expected response:
# {
#   "success": false,
#   "message": "Domain not supported",
#   "error_code": "DOMAIN_NOT_SUPPORTED"
# }

# Test allowed domain (should succeed)
curl -X POST http://localhost:8000/v1/auth/request_confirm_email_code \
  -H "Content-Type: application/json" \
  -H "Origin: http://localhost:5173" \
  -d '{
    "email": "user@example.com",
    "hashed_email": "test_hash",
    "invite_code": "",
    "language": "en",
    "darkmode": false
  }'

# Expected response:
# {
#   "success": true,
#   "message": "Verification code will be sent to your email."
# }
```

#### Test Suspicious Patterns

```bash
# Test typosquatting variation (should fail)
curl -X POST http://localhost:8000/v1/auth/request_confirm_email_code \
  -H "Content-Type: application/json" \
  -H "Origin: http://localhost:5173" \
  -d '{
    "email": "user@oopenmates.org",
    "hashed_email": "test_hash",
    "invite_code": "",
    "language": "en",
    "darkmode": false
  }'

# Expected: "Domain not supported" error
```

### Method 3: Test Server Startup Blocking

#### Test with Environment Variables

1. **Set blocked domain**:
   ```bash
   export PRODUCTION_URL="https://google.com"
   # Start server - should fail with "Domain not supported"
   ```

2. **Set allowed domain**:
   ```bash
   export PRODUCTION_URL="https://openmates.org"
   # Start server - should succeed
   ```

3. **Set suspicious pattern**:
   ```bash
   export PRODUCTION_URL="https://oopenmates.org"
   # Start server - should fail with "Domain not supported"
   ```

#### Test in Docker Compose

Edit `backend/core/docker-compose.yml` or your environment file:

```yaml
environment:
  PRODUCTION_URL: "https://google.com"  # Should cause startup failure
```

Then try to start the server:
```bash
docker-compose up
# Expected: Server exits with "Domain not supported" error
```

### Method 4: Frontend UI Testing

1. Start the frontend development server
2. Navigate to the signup page
3. Try to enter emails from:
   - **Blocked domains**: `user@google.com`, `user@microsoft.com`, etc.
   - **Suspicious patterns**: `user@oopenmates.org`, `user@0penmates.org`
   - **Allowed domain**: `user@openmates.org`
   - **Normal domains**: `user@example.com`

4. Verify that:
   - Blocked domains show "Domain not supported" error
   - Allowed domains proceed normally
   - Normal domains proceed normally

## Test Cases

### Email Signup Tests

| Email | Expected Result | Reason |
|-------|----------------|--------|
| `user@google.com` | ❌ Blocked | In restricted domains list |
| `user@microsoft.com` | ❌ Blocked | In restricted domains list |
| `user@openmates.org` | ✅ Allowed | Official domain |
| `user@oopenmates.org` | ❌ Blocked | Typosquatting (double 'o') |
| `user@0penmates.org` | ❌ Blocked | Typosquatting (zero instead of 'o') |
| `user@openmates.com` | ❌ Blocked | Different TLD |
| `user@example.com` | ✅ Allowed | Normal domain |
| `user@university.edu` | ✅ Allowed | Normal domain |

### Server Startup Tests

| PRODUCTION_URL | Expected Result | Reason |
|----------------|----------------|--------|
| `https://google.com` | ❌ Server won't start | In restricted domains list |
| `https://openmates.org` | ✅ Server starts | Official domain |
| `https://oopenmates.org` | ❌ Server won't start | Typosquatting |
| `https://example.com` | ✅ Server starts | Normal domain |

## Verifying Configuration Loading

Check server logs during startup:

```
INFO: Validating hosting domain against security policies...
INFO: Domain security configuration loaded successfully
INFO: Loaded 101 restricted domains
INFO: Loaded allowed domain: openmates.org
INFO: Extracted platform name: openmates
INFO: Loaded 7 suspicious patterns
INFO: Hosting domain validation passed
```

If configuration fails to load, you'll see:
```
CRITICAL: Encrypted restricted domains configuration file not found...
CRITICAL: Server files missing
```

## Troubleshooting

### Issue: "Server files missing" error

**Cause**: Encrypted files are missing or cannot be decrypted.

**Solution**:
1. Verify encrypted files exist:
   ```bash
   ls -la backend/core/api/app/services/domain_security*.encrypted
   ```

2. Re-encrypt files:
   ```bash
   python scripts/encrypt_domain_security.py \
       --restricted-input restricted_domains.txt \
       --allowed-input allowed_domain.txt \
       --patterns-input suspicious_patterns.txt
   ```

### Issue: Domains not being blocked

**Cause**: Configuration not loaded or service not initialized.

**Solution**:
1. Check server logs for configuration loading errors
2. Verify encrypted files are in the correct location
3. Ensure `DomainSecurityService` is initialized in `main.py`

### Issue: Allowed domain is blocked

**Cause**: Domain not matching exactly or configuration issue.

**Solution**:
1. Check `allowed_domain.txt` contains exactly `openmates.org`
2. Verify the encrypted file was created correctly
3. Check server logs for the loaded allowed domain value

## Integration with CI/CD

Add the test script to your CI pipeline:

```yaml
# .github/workflows/test.yml
- name: Test domain blocklist
  run: |
    python scripts/test_domain_blocklist.py
```

## Security Considerations

- **Never commit cleartext files**: Only encrypted files should be in git
- **Test in isolated environment**: Use test domains when possible
- **Monitor logs**: Watch for configuration loading errors
- **Verify encryption**: Ensure encrypted files cannot be easily decrypted without the key derivation logic
