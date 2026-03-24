---
status: active
last_verified: 2026-03-24
key_files:
  - backend/core/api/app/routes/payments.py
  - backend/core/api/app/services/payment/stripe_service.py
  - backend/core/api/app/services/billing_service.py
  - frontend/packages/ui/src/components/signup/steps/autotopup/AutoTopUpBottomContent.svelte
  - shared/config/pricing.yml
---

# Auto Top-Up

> Monthly auto top-up is fully implemented via Stripe subscriptions. Low-balance auto top-up is planned but not yet built.

## Why This Exists

Users need automated credit replenishment so they do not run out mid-conversation. Monthly subscriptions provide predictable billing; low-balance triggers (future) would prevent interruptions for heavy users.

## How It Works

### Monthly Auto Top-Up (Implemented)

**Signup flow:**
1. User completes initial credit purchase.
2. Auto top-up screen presented (`AutoTopUpTopContent.svelte` + `AutoTopUpBottomContent.svelte`).
3. User toggles on, selects tier (intelligent suggestion: promotes 10K tier if user bought 1K).
4. `POST /v1/payments/save-payment-method` encrypts Stripe payment method ID with user's vault key.
5. `POST /v1/payments/create-subscription` creates a Stripe subscription with the saved method.

**Monthly renewal (automated via webhooks):**
1. Stripe sends `invoice.payment_succeeded` webhook.
2. Backend looks up user by `stripe_subscription_id`.
3. Calculates total credits = base + bonus (from `pricing.yml` tier lookup).
4. Adds credits to user account (encrypted balance in Directus).
5. Broadcasts `user_credits_updated` via WebSocket for real-time UI update.

**Subscription lifecycle webhooks:**
- `customer.subscription.updated` -- updates status and next billing date.
- `customer.subscription.deleted` -- marks subscription as canceled.
- `invoice.payment_failed` -- updates status to `past_due`.

### API Endpoints

| Endpoint                              | Purpose                                        |
|---------------------------------------|------------------------------------------------|
| `POST /v1/payments/save-payment-method`| Encrypt and store Stripe payment method ID    |
| `POST /v1/payments/create-subscription`| Create monthly Stripe subscription            |
| `GET /v1/payments/subscription`       | Get active subscription details with tier info |
| `POST /v1/payments/cancel-subscription`| Cancel at period end                          |
| `POST /v1/payments/webhook`           | Handle all Stripe webhook events               |

### Database Schema

Stored on user record (`backend/core/directus/schemas/users.yml`):

- `encrypted_payment_method_id` -- Stripe payment method (encrypted with vault key)
- `stripe_subscription_id` -- Stripe subscription ID (cleartext)
- `subscription_status` -- `active`, `canceled`, `past_due`
- `subscription_credits` -- base credit amount for tier lookup
- `subscription_currency` -- `eur`, `usd`, `jpy`
- `next_billing_date` -- ISO 8601 timestamp

### Pricing Configuration

Each tier in `shared/config/pricing.yml` specifies base credits, multi-currency prices, and `monthly_auto_top_up_extra_credits` (bonus). Only tiers with bonus > 0 support subscriptions.

### Security

- Payment method IDs encrypted with user-specific vault keys (zero-knowledge).
- All webhooks verified via Stripe signature validation with timestamp replay protection.
- Subscription operations require authenticated user session.

## Edge Cases

- Payment method save failure does not block signup completion -- user can set up later in settings.
- Subscription creation failure logged but user can continue and retry from settings.
- WebSocket disconnected during credit update: credit is still added server-side; user sees it on next session.
- Webhook replay: idempotency via order status cache prevents duplicate credit additions.

## Future: Low-Balance Auto Top-Up

Not yet implemented. Planned approach: integrate balance checking into `BillingService.charge_user_credits()` so detection happens inline with credit deduction (no polling needed). Would use a one-time Stripe PaymentIntent (not subscription) with the saved payment method. Fixed threshold of 100 credits, configurable top-up amount, 1-hour cooldown, max 1/day, disable after 3 consecutive failures. Requires 2FA to enable. Settings UI only (not part of signup).

## Related Docs

- [Payment Processing](./payment-processing.md) -- Stripe integration, tier system, chargeback handling
- [Signup & Auth](../core/signup-and-auth.md) -- signup flow context
