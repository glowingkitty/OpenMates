# Auto Top Up Architecture

## Requirements

- User can activate auto top up during signup or in the settings menu
- Auto top up on low balance and auto top up every month can be done independently
- Stripe payment method ID is stored encrypted during signup, so it can be used later in settings menu (but requires entering 2FA OTP code to confirm)
- Settings:
    - User must be able to activate/deactivate auto top up any time
    - User must be able to change which credits amount to top up
    - User must be able to purchase with existing or new payment method

## Current Implementation Status

### ✅ Fully Implemented: Monthly Auto Top-Up

The **monthly subscription-based auto top-up** is fully implemented and functional:

- **Signup Integration**: Users can activate monthly auto top-up during signup after their initial payment
- **Payment Method Storage**: Stripe payment method ID is saved encrypted with user's vault key
- **Subscription Creation**: Stripe subscriptions are created with proper product/price matching
- **Automated Monthly Renewals**: Fully automated via Stripe webhooks
  - Webhook handler processes `invoice.payment_succeeded` events
  - Credits (base + bonus) are automatically added to user account
  - Credit balance is encrypted and saved to Directus
  - Real-time WebSocket notification sent to user
- **Status Management**: Handles subscription lifecycle (active, canceled, past_due)
- **Webhook Infrastructure**: Complete webhook processing for all subscription events

**What Works Right Now:**
1. User completes signup and initial payment
2. User opts into monthly auto top-up on auto top-up screen
3. Stripe subscription is created with saved payment method
4. Every month, Stripe automatically charges the user
5. Webhook receives payment confirmation
6. Backend automatically adds credits (with bonus) to user account
7. User sees credit balance update in real-time

### ❌ Not Yet Implemented: Low Balance Auto Top-Up

The **low balance trigger-based auto top-up** is NOT currently implemented. This is a separate feature from monthly subscriptions:

**What's Missing:**
- No background monitoring of user credit balances
- No threshold configuration (threshold is fixed at 100 credits to simplify setup)
- No one-time payment trigger system
- No low balance detection logic
- No automatic one-time charge creation

**What Would Be Needed:**
1. Database fields for low balance settings:
   - `auto_topup_low_balance_enabled` (boolean)
   - `auto_topup_low_balance_threshold` (integer - credits, **fixed at 100 credits**, cannot be changed to simplify setup)
   - `auto_topup_low_balance_amount` (integer - credits to add)
   - `auto_topup_low_balance_last_triggered` (timestamp - prevent multiple triggers)

2. Monitoring system:
   - Background task or credit deduction interceptor
   - Check balance after each credit deduction
   - Trigger one-time payment when threshold crossed

3. One-time payment creation:
   - Use saved `encrypted_payment_method_id`
   - Create Stripe PaymentIntent (not subscription)
   - Handle payment confirmation webhook
   - Add credits when payment succeeds

4. Settings UI (not part of signup):
   - Enable/disable low balance auto top-up
   - Threshold is fixed at 100 credits (cannot be changed to simplify setup)
   - Configure top-up amount
   - Requires 2FA to enable/modify

**Current Workaround:**
Users can only use monthly subscriptions for automated top-ups. There is no automatic one-time charge when balance runs low. Users must manually purchase more credits when needed.

## Recommended Implementation Approach for Low Balance Auto Top-Up

### Architecture Decision: Billing Service Integration

The optimal approach is to integrate low balance checking directly into the existing [BillingService](../../backend/core/api/app/services/billing_service.py), which already handles credit deductions.

**Why This Approach:**
1. **Single Point of Deduction** - All credit deductions flow through `BillingService.charge_user_credits()`
2. **No Race Conditions** - Check happens in the same transaction as deduction
3. **Immediate Detection** - Triggers right when balance crosses threshold
4. **Minimal Overhead** - No polling or background tasks needed
5. **Consistent State** - Balance check sees the same state as the deduction

### Implementation Steps

#### 1. Database Schema Updates

Add fields to [users.yml](../../backend/core/directus/schemas/users.yml):

- `auto_topup_low_balance_enabled` (boolean) - Enable/disable feature
- `auto_topup_low_balance_threshold` (integer) - Credit threshold that triggers auto top-up (**fixed at 100 credits**, cannot be changed to simplify setup)
- `auto_topup_low_balance_amount` (integer) - Credits to purchase when triggered
- `auto_topup_low_balance_currency` (string, 3) - Currency for purchases
- `encrypted_auto_topup_last_triggered` (string, 512) - Encrypted timestamp to prevent rapid retriggering

#### 2. Billing Service Enhancement

Modify [BillingService.charge_user_credits()](../../backend/core/api/app/services/billing_service.py#L27):

**After credit deduction and cache update (around line 66):**
- Check if new balance is at or below configured threshold
- If low balance auto top-up is enabled, trigger async payment (fire-and-forget)
- Use `asyncio.create_task()` to avoid blocking the current request

**New method `_trigger_low_balance_topup()`:**

Processing flow:
1. Check cooldown period (minimum 1 hour between triggers)
2. Decrypt saved payment method ID using user's vault key
3. Retrieve configuration (credits amount, currency)
4. Create one-time Stripe PaymentIntent for configured amount
5. Automatically confirm payment using saved payment method
6. Update last triggered timestamp (encrypted)
7. Log success/failure

All operations run asynchronously to not impact the original credit deduction request.

#### 3. Payment Processing Integration

The existing webhook handler at [payments.py:264](../../backend/core/api/app/routes/payments.py#L264) processes `payment_intent.succeeded` events:
- Extracts order details from payment intent metadata
- Verifies payment success state
- Decrypts and adds credits to user account
- Updates order status in cache
- Broadcasts real-time balance update via WebSocket

No changes needed - auto top-up payments flow through the same webhook handler automatically.

#### 4. Settings UI (Future)

Create settings interface to:
- Enable/disable low balance auto top-up
- Threshold is fixed at 100 credits (cannot be changed to simplify setup)
- Set top-up amount (must match available pricing tiers)
- Requires 2FA confirmation to enable

#### 5. Safeguards

**Cooldown Period:**
- Minimum 1 hour between auto top-ups
- Prevents rapid-fire charges if service is buggy

**Payment Limits:**
- Only allow tier amounts from pricing.yml
- Maximum 1 auto top-up per day per user (additional safeguard)

**User Notifications:**
- Send email after successful auto top-up
- WebSocket notification to update UI
- Transaction appears in billing history

**Failure Handling:**
- Log all failed auto top-ups
- Disable feature after 3 consecutive failures
- Notify user via email to update payment method

### Alternative Approaches (Not Recommended)

#### ❌ Background Task / Cron Job
**Why Not:**
- Polls all users periodically (expensive)
- Delay between balance drop and detection
- Race conditions between check and actual balance
- Unnecessary database load

#### ❌ Ask Skill Task Integration
**Why Not:**
- Only checks when AI requests complete
- Misses credits spent elsewhere (gift cards, etc.)
- Tight coupling with AI logic
- Not all credit deductions go through ask_skill

#### ❌ Credit Deduction Interceptor
**Why Not:**
- Essentially the same as billing service approach
- BillingService already centralizes deductions
- No benefit to adding another layer

### Testing Low Balance Auto Top-Up

1. **Unit Tests:**
   - Mock stripe service
   - Test threshold detection logic
   - Verify cooldown enforcement
   - Test payment method decryption

2. **Integration Tests:**
   - Use Stripe test mode
   - Set low threshold (e.g., 10 credits)
   - Deduct credits to trigger auto top-up
   - Verify payment created and processed
   - Confirm credits added automatically

3. **Edge Cases:**
   - Payment method expired
   - Insufficient funds on card
   - Multiple rapid deductions
   - Concurrent requests
   - Stripe API timeout

### Cache-First Pattern

The implementation follows OpenMates' cache-first architecture to prevent conflicts and ensure consistency:

**Timestamp Handling:**
- Cache stores plaintext timestamp (float) for fast access
- Directus stores encrypted timestamp for persistence
- On read: Check cache first, decrypt from Directus only if cache miss
- On write: Update cache first, then encrypt and update Directus

**Configuration Fields:**
- All auto top-up configuration fields loaded into cache with user profile
- Threshold, amount, currency, enabled flag all cached
- No decryption needed for reads during credit deduction
- Settings changes must update both cache and Directus

**Why Cache-First:**
1. Prevents race conditions between multiple credit deductions
2. Avoids redundant decryption operations
3. Ensures consistent view of user state within a request
4. Matches pattern used for credit balance management

### Security Considerations

- Payment method IDs remain encrypted with user's vault key
- Timestamp encrypted in Directus, plaintext in ephemeral cache
- 2FA required to enable/modify auto top-up settings
- Audit log of all auto top-up triggers
- Rate limiting on settings changes
- Email confirmation for first-time enablement

## Overview

The auto top-up system provides users with automated monthly credit replenishment through Stripe subscriptions. The implementation maintains OpenMates' zero-knowledge security model by encrypting all sensitive payment data with user-specific vault keys.

## Architecture Components

### Frontend Components

#### Signup Flow Integration

The auto top-up step is integrated as the final step in the signup process, appearing after a successful initial payment. The main signup orchestration is handled in [Signup.svelte](../../frontend/packages/ui/src/components/signup/Signup.svelte).

**Step Sequence:**
1. Basic information and account creation
2. Email confirmation and security setup
3. Credits selection and payment
4. **Auto Top-Up activation** (optional)
5. Completion and app initialization

#### Auto Top-Up UI Components

Two dedicated components handle the auto top-up interface:

1. **[AutoTopUpTopContent.svelte](../../frontend/packages/ui/src/components/signup/steps/autotopup/AutoTopUpTopContent.svelte)** - Displays:
   - Success confirmation with animated check icon
   - Purchase summary (credits purchased and amount paid)
   - Introduction to auto top-up benefits

2. **[AutoTopUpBottomContent.svelte](../../frontend/packages/ui/src/components/signup/steps/autotopup/AutoTopUpBottomContent.svelte)** - Provides:
   - Toggle switch for enabling/disabling auto top-up
   - Intelligent tier suggestion (promotes 10,000 credit tier for users who bought 1,000 credits)
   - Credit breakdown showing base credits + bonus credits
   - Monthly price display
   - Benefits list highlighting recurring billing advantages
   - Action buttons: "Skip" or "Activate & Finish Setup"

### Backend Processing

#### API Endpoints

All subscription-related endpoints are defined in [payments.py](../../backend/core/api/app/routes/payments.py):

**Payment Method Management:**
- `POST /v1/payments/save-payment-method` - Extracts and encrypts payment method ID from successful PaymentIntent
- Encryption uses the user's vault key via [EncryptionService](../../backend/core/api/app/utils/encryption.py)

**Subscription Lifecycle:**
- `POST /v1/payments/create-subscription` - Creates monthly Stripe subscription with saved payment method
- `GET /v1/payments/subscription` - Retrieves active subscription details with tier info from pricing config
- `POST /v1/payments/cancel-subscription` - Cancels subscription at period end (allows user to use remaining time)

**Webhook Processing:**
- `POST /v1/payments/webhook` - Handles Stripe webhook events for subscription lifecycle

#### Payment Provider Integration

The [StripeService](../../backend/core/api/app/services/payment/stripe_service.py) provides the payment provider interface:

**Customer Management:**
- Creates Stripe customers with attached payment methods
- Links customers to user accounts via metadata

**Subscription Operations:**
- Creates recurring monthly subscriptions using pre-configured Stripe products
- Retrieves subscription status and billing information
- Cancels subscriptions while preserving access until period end

**Product Matching:**
- Finds Stripe products by credit amount (e.g., "21.000 credits")
- Matches currency-specific prices for multi-currency support
- Falls back to dynamic PaymentIntents if product not found

### Data Flow

#### During Signup

1. **Payment Success** - [Signup.svelte:393](../../frontend/packages/ui/src/components/signup/Signup.svelte#L393)
   - User completes initial credit purchase
   - `handlePaymentStateChange` detects success state
   - Payment method ID extracted from PaymentIntent
   - Backend saves encrypted payment method via `savePaymentMethod` endpoint
   - User transitions to auto top-up step

2. **Auto Top-Up Activation** - [AutoTopUpBottomContent.svelte:94](../../frontend/packages/ui/src/components/signup/steps/autotopup/AutoTopUpBottomContent.svelte#L94)
   - User toggles auto top-up on
   - Component shows subscription details with bonus credits
   - User clicks "Activate & Finish Setup"
   - `handleActivateSubscription` sends subscription request to backend

3. **Subscription Creation** - [payments.py:747](../../backend/core/api/app/routes/payments.py#L747)
   - Validates tier exists in pricing configuration
   - Decrypts saved payment method ID using user's vault key
   - Retrieves user email from cache
   - Creates or retrieves Stripe customer
   - Finds matching Stripe price for tier and currency
   - Creates subscription with metadata (credits, bonus, user ID)
   - Saves subscription details to Directus (encrypted fields remain encrypted)

4. **Signup Completion** - [Signup.svelte:423](../../frontend/packages/ui/src/components/signup/Signup.svelte#L423)
   - Updates user profile with `last_opened: '/chat/new'`
   - Establishes WebSocket connection for real-time updates
   - Transitions user to main application

#### Monthly Renewals

**Webhook Processing Flow** - [payments.py:486](../../backend/core/api/app/routes/payments.py#L486)

1. **Invoice Payment Succeeded Event**
   - Stripe sends `invoice.payment_succeeded` webhook
   - Webhook signature verified using Stripe webhook secret
   - Subscription ID extracted from invoice data

2. **User Lookup** - [user_lookup.py](../../backend/core/api/app/services/directus/user/user_lookup.py)
   - User retrieved by `stripe_subscription_id`
   - Subscription tier details loaded (credits amount, currency)

3. **Credit Calculation**
   - Base credits read from user's `subscription_credits` field
   - Bonus credits calculated from [pricing.yml](../../shared/config/pricing.yml) using tier lookup
   - Total credits = base credits + bonus credits

4. **Credit Addition**
   - Current credit balance retrieved from cache
   - New total calculated by adding subscription credits
   - New balance encrypted with user's vault key
   - Directus updated with encrypted credit balance

5. **Real-Time Notification**
   - Credit update published to Redis channel `user_updates::{user_id}`
   - WebSocket manager broadcasts `user_credits_updated` event
   - User's frontend receives update and refreshes balance display

#### Subscription Status Updates

**Status Change Events** - [payments.py:601](../../backend/core/api/app/routes/payments.py#L601)

- `customer.subscription.updated` - Updates status and next billing date
- `customer.subscription.deleted` - Marks subscription as canceled
- `invoice.payment_failed` - Updates status to `past_due`

All status changes are persisted to the `subscription_status` field in Directus.

### Database Schema

User subscription data is stored in [users.yml](../../backend/core/directus/schemas/users.yml) with the following fields:

**Encrypted Fields (secured with user's vault key):**
- `encrypted_payment_method_id` - Stripe payment method ID for recurring charges

**Cleartext Fields (not sensitive):**
- `stripe_subscription_id` - Stripe subscription identifier
- `subscription_status` - Current status (active, canceled, past_due)
- `subscription_credits` - Base credit amount for lookups in pricing config
- `subscription_currency` - Currency code (eur, usd, jpy)
- `next_billing_date` - ISO 8601 timestamp of next charge

### Security Considerations

**Zero-Knowledge Design:**
- Payment method IDs encrypted with user-specific vault keys
- Email addresses encrypted with client-side keys during order creation
- No plaintext payment data stored in application database

**Webhook Security:**
- All Stripe webhooks verified using signature validation
- Timestamp validation prevents replay attacks
- Event idempotency handled by checking order status in cache

**Access Control:**
- Subscription operations require authenticated user session
- User can only access their own subscription data
- Payment method decryption requires valid vault key

### Configuration

**Pricing Tiers** - [pricing.yml](../../shared/config/pricing.yml)

Each tier can specify:
- Base credit amount
- Prices in multiple currencies (EUR, USD, JPY)
- `monthly_auto_top_up_extra_credits` - Bonus for subscription (0 = no subscription support)
- Recommended tier flag

**Tier Validation:**
- Only tiers with bonus credits > 0 support subscriptions
- Pricing loaded at application startup
- Used for both order validation and subscription credit calculations

**API Configuration** - [api.ts](../../frontend/packages/ui/src/config/api.ts)

Defines subscription endpoints:
- Base URL selection (development/production)
- Endpoint path constants
- Request/response type definitions

### Error Handling

**Graceful Degradation:**
- Payment method save failures don't block signup completion
- Subscription creation failures logged but allow user to continue
- Users can set up subscriptions later in settings if signup fails

**Webhook Failures:**
- Failed credit additions logged with full context
- Order status updated to reflect failure state
- Subscription remains active for retry on next billing cycle

**User Experience:**
- Processing states shown during subscription activation
- Clear error messages for validation failures
- Skip option always available

## Future Enhancements

### Settings Menu Integration

**Planned Features:**
- View current subscription details
- Change subscription tier
- Update payment method (requires 2FA verification)
- Cancel subscription
- Reactivate canceled subscription
- View billing history

**Security Requirements:**
- 2FA OTP required for payment method changes
- Email confirmation for subscription modifications
- Audit log of all subscription actions

### Auto Top-Up on Low Balance

**Separate Feature:**
- Triggers one-time payment when balance falls below threshold (fixed at 100 credits)
- Independent from monthly subscription
- Uses saved payment method
- Threshold is fixed at 100 credits (cannot be changed to simplify setup)
- Configurable top-up amount
- Requires additional webhook handling for one-time charges

## Testing Considerations

**Test Scenarios:**

1. **Signup Flow:**
   - Complete payment → auto top-up presented
   - Enable auto top-up → subscription created
   - Skip auto top-up → proceed without subscription
   - Payment method save failure → graceful handling

2. **Monthly Renewals:**
   - Successful invoice payment → credits added with bonus
   - Failed payment → status updated to past_due
   - Subscription canceled → no further charges
   - WebSocket disconnected → credit update queued

3. **Currency Support:**
   - EUR, USD, JPY pricing correct
   - Currency symbols displayed properly
   - Amounts calculated in smallest unit (cents/yen)

4. **Edge Cases:**
   - User purchases 1,000 credits → 10,000 tier suggested
   - Subscription without bonus credits → rejected
   - Invalid tier → error with helpful message
   - Webhook replay → idempotency prevents duplicate credits

## Dependencies

**External Services:**
- Stripe API (payments and subscriptions)
- Vault (encryption key management)
- Redis (caching and pub/sub)
- Directus (data persistence)

**Internal Services:**
- [WebSocket Manager](../../backend/core/api/app/routes/websockets.py) - Real-time credit updates
- [Encryption Service](../../backend/core/api/app/utils/encryption.py) - Vault key operations
- [Cache Service](../../backend/core/api/app/services/cache) - Order and user data caching
- [Payment Service](../../backend/core/api/app/services/payment/payment_service.py) - Provider abstraction

## Monitoring and Observability

**Key Metrics:**
- Subscription activation rate during signup
- Monthly renewal success rate
- Payment method save success rate
- Credit addition latency
- Webhook processing time

**Logging:**
- All subscription operations logged with user ID and subscription ID
- Webhook events logged with event type and order ID
- Errors logged with full stack traces
- Audit trail for security-sensitive operations
