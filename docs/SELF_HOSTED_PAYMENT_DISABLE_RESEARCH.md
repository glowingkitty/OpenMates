# Self-Hosted Version: Payment/Billing Disable Research

## Overview
This document summarizes the research findings for disabling payment/billing functionality in the self-hosted version of OpenMates. The self-hosted version should work without any payment processing, using existing API keys without credit checks.

## Key Finding: Domain Detection Mechanism

The system already has a domain security service that loads an encrypted allowed domain file at startup. This is the perfect mechanism to detect if we're running in self-hosted mode.

**Location**: `backend/core/api/app/services/domain_security.py`

**Key Method**: `validate_hosting_domain()` - Called at server startup (line 525 in `main.py`)
- Reads `PRODUCTION_URL` or `FRONTEND_URLS` environment variable
- Extracts domain from URL
- Validates against encrypted `domain_security_allowed.encrypted` file
- The allowed domain is stored in `_ALLOWED_DOMAIN` global variable (line 282-283)
- If domain is NOT `openmates.org`, we're in self-hosted mode

**Current Behavior**:
- Server startup validates domain (lines 507-540 in `main.py`)
- If domain is restricted, server exits
- If domain is allowed (openmates.org), server continues
- For self-hosted: domain will be something other than openmates.org

## Payment/Billing Activation Logic

**Payment/Billing should be ENABLED when:**
1. Domain is `openmates.org` (regardless of environment - production or development)
2. Development server running on `localhost` (or `127.0.0.1`, `::1`, `0.0.0.0`)

**Payment/Billing should be DISABLED when:**
1. Domain is NOT `openmates.org` AND production environment
2. Domain is NOT `openmates.org` AND development environment with non-localhost domain

**Implementation Logic:**
```python
# Get domain from environment
domain = extract_domain_from_env()  # From PRODUCTION_URL or FRONTEND_URLS
is_localhost = domain in ["localhost", "127.0.0.1", "::1", "0.0.0.0"]
is_openmates_domain = domain == "openmates.org"
is_development = os.getenv("SERVER_ENVIRONMENT", "development").lower() == "development"

# Payment enabled if:
# - openmates.org domain (any environment)
# - OR (development AND localhost)
payment_enabled = is_openmates_domain or (is_development and is_localhost)
is_self_hosted = not is_openmates_domain and not (is_development and is_localhost)
```

## Required Changes Summary

### 1. Server Startup: Payment/Billing Detection

**File**: `backend/core/api/main.py`

**Location**: After domain validation (around line 540)

**Action Needed**:
- After domain validation, determine payment status based on:
  1. Extract domain from `PRODUCTION_URL` or `FRONTEND_URLS`
  2. Check if domain is `openmates.org`
  3. Check if domain is localhost (`localhost`, `127.0.0.1`, `::1`, `0.0.0.0`)
  4. Check `SERVER_ENVIRONMENT` (development or production)
- Set flags:
  - `app.state.is_self_hosted = True` if domain is NOT openmates.org AND NOT (development + localhost)
  - `app.state.payment_enabled = True` if domain is openmates.org OR (development + localhost)
  - `app.state.is_development = True` if `SERVER_ENVIRONMENT == "development"`
  - `app.state.server_edition = "self_hosted" | "development" | "production"` (for header display)
- Store these flags in `app.state` for use throughout the application

**Code Reference**:
- Domain validation happens at lines 507-540
- `_ALLOWED_DOMAIN` is loaded in `domain_security.py` line 282-283
- Need to import and access: `from backend.core.api.app.services.domain_security import _ALLOWED_DOMAIN`

### 2. FastAPI Route Registration: Conditional Payment Routes

**File**: `backend/core/api/main.py`

**Current Routes to Conditionally Register** (lines 873-876):
```python
app.include_router(invoice.router, include_in_schema=False)
app.include_router(credit_note.router, include_in_schema=False)
app.include_router(payments.router, include_in_schema=False)
```

**Action Needed**:
- Only include these routers if `app.state.payment_enabled == True`
- Wrap in conditional check before `create_app()` returns

**Payment Routes in `payments.py`** (20 endpoints total):
1. `GET /v1/payments/config` - Payment provider config
2. `POST /v1/payments/create-order` - Create payment order
3. `POST /v1/payments/webhook` - Payment webhook (Stripe/Revolut)
4. `POST /v1/payments/order-status` - Get order status
5. `POST /v1/payments/save-payment-method` - Save payment method
6. `POST /v1/payments/create-subscription` - Create auto top-up subscription
7. `GET /v1/payments/subscription` - Get subscription details
8. `GET /v1/payments/has-payment-method` - Check if user has payment method
9. `GET /v1/payments/payment-methods` - List payment methods
10. `GET /v1/payments/user-auth-methods` - Get user auth methods
11. `POST /v1/payments/process-payment-with-saved-method` - Process payment
12. `POST /v1/payments/cancel-subscription` - Cancel subscription
13. `POST /v1/payments/redeem-gift-card` - Redeem gift card
14. `POST /v1/payments/buy-gift-card` - Buy gift card
15. `GET /v1/payments/redeemed-gift-cards` - Get redeemed gift cards
16. `GET /v1/payments/purchased-gift-cards` - Get purchased gift cards
17. `GET /v1/payments/invoices` - Get user invoices
18. `GET /v1/payments/invoices/{invoice_id}/download` - Download invoice PDF
19. `GET /v1/payments/invoices/{invoice_id}/credit-note/download` - Download credit note PDF
20. `POST /v1/payments/refund` - Request refund

**Invoice Routes in `invoice.py`** (2 endpoints):
1. `POST /v1/invoice/generate` - Generate invoice PDF
2. `GET /v1/invoice/preview` - Preview invoice

**Credit Note Routes in `credit_note.py`** (2 endpoints):
1. `POST /v1/credit-note/generate` - Generate credit note PDF
2. `GET /v1/credit-note/preview` - Preview credit note

### 3. Service Initialization: Conditional Payment Services

**File**: `backend/core/api/main.py`

**Services to Conditionally Initialize** (in `lifespan` function):

**PaymentService** (line 350):
- Currently always initialized
- **Action**: Only initialize if `payment_enabled == True`

**InvoiceNinjaService** (lines 353-355):
- Currently always initialized
- **Action**: Only initialize if `payment_enabled == True`

**PaymentService initialization** (lines 547-583):
- Currently always runs
- **Action**: Only run if `payment_enabled == True`

**StripeProductSync** (if exists):
- Check if this is initialized anywhere
- **Action**: Only initialize if `payment_enabled == True`

### 4. Environment Variables: Remove Payment Keys from .env.example

**File**: `.env.example` (currently filtered, need to check contents)

**Action Needed**:
- Remove or comment out all Stripe-related environment variables
- Remove or comment out all Invoice Ninja-related environment variables
- Remove or comment out all Revolut-related environment variables
- Keep API keys for other services (Brave, Google Maps, etc.)

**Expected Variables to Remove**:
- `SECRET__STRIPE__PRODUCTION_SECRET_KEY`
- `SECRET__STRIPE__SANDBOX_SECRET_KEY`
- `SECRET__STRIPE__PRODUCTION_WEBHOOK_SECRET`
- `SECRET__STRIPE__SANDBOX_WEBHOOK_SECRET`
- `SECRET__INVOICE_NINJA__*` (all Invoice Ninja secrets)
- `SECRET__REVOLUT__*` (all Revolut secrets)

**Note**: These are stored in Vault, not .env, but the .env.example should document that they're not needed for self-hosted.

### 5. Frontend: Signup Flow - Skip Payment Steps

**Files**:
- `frontend/packages/ui/src/stores/signupState.ts`
- `frontend/packages/ui/src/components/signup/Signup.svelte`

**Current Signup Steps** (from `signupState.ts` lines 22-37):
1. STEP_BASICS
2. STEP_CONFIRM_EMAIL
3. STEP_SECURE_ACCOUNT
4. STEP_PASSWORD
5. STEP_ONE_TIME_CODES
6. STEP_BACKUP_CODES
7. STEP_TFA_APP_REMINDER
8. **STEP_CREDITS** ← Skip in self-hosted
9. **STEP_PAYMENT** ← Skip in self-hosted
10. **STEP_AUTO_TOP_UP** ← Skip in self-hosted
11. STEP_COMPLETION

**Action Needed**:
- Add API endpoint to check if payment is enabled: `GET /v1/settings/payment-enabled`
- In signup flow, check this endpoint
- If payment disabled, skip STEP_CREDITS, STEP_PAYMENT, STEP_AUTO_TOP_UP
- Go directly from STEP_TFA_APP_REMINDER to STEP_COMPLETION

**Implementation**:
- In `Signup.svelte`, add check after user authentication
- Modify step sequence logic to conditionally include payment steps
- Update `signupState.ts` to support conditional step sequences

### 6. Frontend: Settings - Hide Billing/Gift Card Sections

**File**: `frontend/packages/ui/src/components/Settings.svelte`

**Current Billing Settings** (lines 75-83, 148-162):
- `SettingsBuyCredits`
- `SettingsBuyCreditsPayment`
- `SettingsBuyCreditsConfirmation`
- `SettingsRedeemGiftCard`
- `SettingsAutoTopUp`
- `SettingsLowBalanceAutotopup`
- `SettingsMonthlyAutotopup`
- `SettingsInvoices`

**Current Gift Card Settings** (lines 85-89, 157-162):
- `SettingsGiftCards`
- `SettingsGiftCardsRedeem`
- `SettingsGiftCardsRedeemed`
- `SettingsGiftCardsBuy`
- `SettingsGiftCardsBuyPayment`
- `SettingsGiftCardsPurchaseConfirmation`

**Action Needed**:
- Add API check for payment enabled (same endpoint as signup)
- Conditionally hide/remove billing and gift card menu items
- Conditionally exclude these routes from `baseSettingsViews` object

**Settings Routes to Hide**:
- `'billing'` and all sub-routes
- `'gift_cards'` and all sub-routes

### 7. Credit Checking: Disable for Self-Hosted

**Files**:
- `backend/apps/ai/processing/preprocessor.py` (lines 100-147)
- `backend/core/api/app/services/billing_service.py` (lines 27-125)

**Current Behavior**:
- `preprocessor.py` checks credits before processing (line 129)
- Returns error if insufficient credits (lines 129-145)
- `billing_service.py` charges credits and checks balance (lines 98-106)

**Action Needed**:
- In `preprocessor.py`, check `app.state.payment_enabled` (or pass flag)
- If `payment_enabled == False`, skip credit check (always allow)
- In `billing_service.py`, check `payment_enabled` flag
- If `payment_enabled == False`, skip balance check but still create usage entries

**Important**: Usage entries should still be created for tracking purposes, even in self-hosted mode.

**Code Locations**:
- `preprocessor.py` line 129: `if user_credits < MINIMUM_REQUEST_COST:`
- `billing_service.py` line 99: `if current_credits < credits_to_deduct:`

### 8. Usage Entries: Continue Creating (No Changes Needed)

**Files**:
- `backend/core/api/app/services/directus/usage.py` (lines 21-103)
- `backend/core/api/app/routes/internal_api.py` (lines 189-241)

**Current Behavior**:
- Usage entries are created independently of payment system
- They track: app_id, skill_id, credits_charged, tokens, model, etc.
- Used for analytics and user visibility

**Action**: ✅ **No changes needed** - Usage entries should continue to be created in self-hosted mode for tracking purposes.

### 9. API Endpoint: Server Status Check

**New Endpoint Needed**: `GET /v1/settings/server-status`

**File**: `backend/core/api/app/routes/settings.py` (or create new endpoint)

**Response**:
```json
{
  "payment_enabled": true/false,
  "is_self_hosted": true/false,
  "is_development": true/false,
  "server_edition": "self_hosted" | "development" | "production"
}
```

**Action Needed**:
- Create this endpoint to allow frontend to check server status
- Read from `app.state.payment_enabled`, `app.state.is_self_hosted`, `app.state.is_development`, `app.state.server_edition`
- No authentication required (public endpoint for frontend check)
- Used by frontend to:
  - Show/hide payment-related UI
  - Display server edition in header

### 10. Frontend: Header - Display Server Edition

**File**: `frontend/packages/ui/src/components/Header.svelte`

**Action Needed**:
- Add API call to fetch server status from `GET /v1/settings/server-status`
- Display server edition text under the OpenMates logo:
  - If `server_edition === "self_hosted"`: Show "Self Hosting Edition"
  - If `server_edition === "development"`: Show "Development Server"
  - If `server_edition === "production"`: Show nothing (default production)
- Style appropriately (smaller text, muted color, positioned under logo)

**Implementation**:
- Add state variable for server edition: `let serverEdition = $state<string | null>(null)`
- Fetch on component mount from `GET /v1/settings/server-status`
- Conditionally render edition text based on `server_edition` value
- Position below logo using CSS (after line 200 in Header.svelte)
- Add after the logo link:
  ```svelte
  {#if serverEdition === 'self_hosted'}
      <div class="server-edition">Self Hosting Edition</div>
  {:else if serverEdition === 'development'}
      <div class="server-edition">Development Server</div>
  {/if}
  ```
- Style with smaller font, muted color, positioned directly below logo

### 11. Additional Considerations

#### Health Checks
**File**: `backend/core/api/app/tasks/health_check_tasks.py` (lines 853-903)

**Action**: 
- Skip Stripe health check if `payment_enabled == False`
- Skip Invoice Ninja health check if `payment_enabled == False`

#### Email Tasks
**Files**: Various email task files in `backend/core/api/app/tasks/email_tasks/`

**Action**:
- Payment confirmation emails should not be sent in self-hosted mode
- Invoice emails should not be sent in self-hosted mode
- Credit note emails should not be sent in self-hosted mode

#### Webhook Endpoints
**File**: `backend/core/api/app/routes/payments.py` (line 482)

**Action**:
- Payment webhook endpoint won't be registered if payment routes are disabled
- This is already handled by conditional route registration

#### Creator Tips and Revenue Sharing
**Files**: 
- `backend/core/api/app/routes/creators.py` (lines 90-170) - Creator tips endpoint
- `backend/apps/videos/skills/transcript_skill.py` - Video transcript revenue sharing
- `backend/apps/web/skills/read_skill.py` - Web read revenue sharing

**Current Behavior**:
- Creator tips transfer credits between users (not external payments)
- Uses `billing_service.charge_user_credits()` to deduct credits
- Checks if user has sufficient credits (line 146)
- Creates usage entry and creator income entry
- Revenue sharing: 50% of credits go to creators when processing their content

**Action**:
- **Disable creator tips entirely** in self-hosted mode
- **Disable revenue sharing** in self-hosted mode (no creator income entries)
- Conditionally register creator router only if `payment_enabled == True`
- Or add check at start of tip endpoint to return 404/403 if `payment_enabled == False`
- For revenue sharing in skills: Skip creator income creation if `payment_enabled == False`

## Summary of Files to Modify

### Backend Files:
1. `backend/core/api/main.py` - Domain check, service initialization, route registration, server edition detection
2. `backend/core/api/app/services/domain_security.py` - Export `_ALLOWED_DOMAIN` for access, add domain extraction helper
3. `backend/apps/ai/processing/preprocessor.py` - Skip credit check if self-hosted
4. `backend/core/api/app/services/billing_service.py` - Skip balance check if self-hosted
5. `backend/core/api/app/routes/settings.py` - Add server-status endpoint
6. `backend/core/api/app/routes/creators.py` - Disable creator tips if self-hosted
7. `backend/apps/videos/skills/transcript_skill.py` - Skip revenue sharing if self-hosted
8. `backend/apps/web/skills/read_skill.py` - Skip revenue sharing if self-hosted
9. `backend/core/api/app/tasks/health_check_tasks.py` - Skip payment health checks
10. `.env.example` - Remove payment-related environment variables

### Frontend Files:
1. `frontend/packages/ui/src/components/signup/Signup.svelte` - Skip payment steps
2. `frontend/packages/ui/src/stores/signupState.ts` - Conditional step sequences
3. `frontend/packages/ui/src/components/Settings.svelte` - Hide billing/gift card sections
4. `frontend/packages/ui/src/components/Header.svelte` - Display server edition text
5. `frontend/packages/ui/src/config/api.ts` - Add server-status endpoint

## Missing Items from Original List

Your original list was comprehensive! Additional items found:

1. ✅ **Health checks** - Need to skip payment service health checks
2. ✅ **Email tasks** - Payment-related emails should not be sent
3. ✅ **Creator tips and revenue sharing** - Disable entirely for self-hosted
4. ✅ **API endpoint** - Need public endpoint to check server status for frontend
5. ✅ **Header display** - Show "Self Hosting Edition" or "Development Server" in header
6. ✅ **Development server payment logic** - Payment enabled on localhost OR openmates.org domain in development

## Testing Checklist (For Implementation Phase)

### Self-Hosted Mode (non-openmates.org domain, production or development):
1. ✅ Server starts successfully on non-openmates.org domain
2. ✅ Payment routes return 404 in self-hosted mode
3. ✅ Creator tips endpoint returns 404/403 in self-hosted mode
4. ✅ Revenue sharing is disabled (no creator income entries created)
5. ✅ Signup flow skips payment steps
6. ✅ Settings page doesn't show billing/gift card sections
7. ✅ Header shows "Self Hosting Edition" text
8. ✅ Credit checks are bypassed (requests proceed without credit validation)
9. ✅ Usage entries are still created
10. ✅ API keys work without credit checks
11. ✅ No payment-related environment variables needed
12. ✅ Health checks don't fail for missing payment services
13. ✅ No payment-related emails are sent

### Development Server Mode (localhost OR openmates.org domain):
1. ✅ Server starts successfully on localhost
2. ✅ Server starts successfully on openmates.org domain in development
3. ✅ Payment routes are accessible
4. ✅ Creator tips work
5. ✅ Revenue sharing works
6. ✅ Signup flow includes payment steps
7. ✅ Settings page shows billing/gift card sections
8. ✅ Header shows "Development Server" text
9. ✅ Credit checks work normally
10. ✅ Payment processing works (Stripe/Revolut)

### Development Server Mode (non-openmates.org domain, NOT localhost):
1. ✅ Server starts successfully
2. ✅ Payment routes return 404
3. ✅ Creator tips disabled
4. ✅ Revenue sharing disabled
5. ✅ Header shows "Self Hosting Edition" (treated as self-hosted)
