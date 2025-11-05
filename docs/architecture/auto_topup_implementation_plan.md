# Auto Top-Up Implementation Plan

## Overview

Add monthly auto top-up functionality to OpenMates signup flow. The auto top-up screen appears after successful payment as the final step before the app loads.

## Figma Design Reference

[Auto Top-Up Screen - Figma](https://www.figma.com/design/PzgE78TVxG0eWuEeO6o8ve/Website?node-id=3699-47780&t=wOQp8b53NulCmAmL-4)

## Key Requirements

1. **Signup Flow Changes**
   - Remove profile picture step (comment out, move to settings later)
   - Auto top-up screen is the LAST screen after payment success
   - Shows "Purchase successful!" + auto top-up option
   - "Finish setup" button completes signup and loads main app

2. **Auto Top-Up Logic**
   - Suggest tier matching user's purchase
   - Exception: 1,000 credits purchase → suggest 10,000 credits tier
   - User can activate or skip

3. **New Signup Sequence**
   ```
   1. Basics
   2. Confirm Email
   3. Secure Account
   4. Password (if password chosen)
   5. One-Time Codes (2FA)
   6. Backup Codes
   7. Recovery Key
   8. TFA App Reminder
   9. (Profile Picture - REMOVED)
   10. Credits Selection
   11. Payment
   12. Auto Top-Up ← NEW (final step)
   13. Completion
   ```

---

## Phase 1: Frontend Changes

### 1.1 Update Signup State

**File**: `frontend/packages/ui/src/stores/signupState.ts`

- Add `STEP_AUTO_TOP_UP` constant
- Comment out `STEP_PROFILE_PICTURE` from sequence
- Update `getStepFromPath()` for 'auto-top-up' route

### 1.2 Create Auto Top-Up Components

**File**: `frontend/packages/ui/src/components/signup/steps/autotopup/AutoTopUpTopContent.svelte`
- Success message
- Purchase summary

**File**: `frontend/packages/ui/src/components/signup/steps/autotopup/AutoTopUpBottomContent.svelte`
- Toggle for activation
- Credit tier display (base + bonus)
- Price display
- "Skip" and "Activate & Finish Setup" buttons

### 1.3 Update Payment Components

- Store payment method ID after successful payment
- Transition to auto top-up step instead of completion
- Pass purchased credits/price/currency to next step

### 1.4 Update Main Signup Component

- Import and register auto top-up components
- Handle flow: payment → auto top-up → completion

---

## Phase 2: Backend Changes

### 2.1 Database Schema

**File**: `backend/core/directus/schemas/users.yml`

Add fields:
```yaml
encrypted_payment_method_id: string(512)
stripe_subscription_id: string(255)
subscription_status: string(50)
subscription_credits: integer
subscription_bonus_credits: integer
subscription_currency: string(3)
subscription_price: integer
next_billing_date: string(256)
```

### 2.2 New API Endpoints

**POST** `/v1/payments/save-payment-method`
- Save encrypted Stripe payment_method ID

**POST** `/v1/payments/create-subscription`
- Create Stripe subscription
- Store subscription details

**GET** `/v1/payments/subscription`
- Get user's subscription details

**POST** `/v1/payments/cancel-subscription`
- Cancel active subscription

### 2.3 Update Stripe Service

Add methods:
- `create_customer()`
- `create_subscription()`
- `cancel_subscription()`
- `get_subscription()`

### 2.4 Webhook Updates

Handle new events:
- `invoice.payment_succeeded` - Add credits on renewal
- `customer.subscription.deleted` - Mark canceled
- `invoice.payment_failed` - Handle failures
- `customer.subscription.updated` - Update details

---

## Phase 3: Implementation Steps

### Step 1: Frontend Signup Flow
1. Update `signupState.ts`
2. Create auto top-up components
3. Update payment flow
4. Update Signup.svelte

### Step 2: Backend Schema & Endpoints
1. Update Directus user schema
2. Create subscription endpoints
3. Update Stripe service
4. Update webhook handler

### Step 3: Testing
1. Test signup with auto top-up activation
2. Test signup skipping auto top-up
3. Test webhook processing
4. Test subscription management

---

## Security

- Payment method IDs encrypted with user's vault key
- 2FA required for subscription operations
- Stripe signature verification on webhooks
- Zero-knowledge architecture maintained