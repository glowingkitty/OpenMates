---
status: active
last_verified: 2026-03-24
key_files:
  - backend/core/api/app/routes/payments.py
  - backend/core/api/app/services/payment/stripe_service.py
  - backend/core/api/app/services/billing_service.py
  - shared/config/pricing.yml
---

# Payment Processing

> Stripe-based credit purchases with a chargeback-prevention tier system, EU consumer law compliance, and planned SEPA/Paddle support.

## Why This Exists

OpenMates uses a credit-based billing model. Users purchase credits via card payments, which are consumed by AI model usage and other API calls. The tier system limits chargeback exposure for new users while allowing trusted users higher limits.

## How It Works

### Payment Flow

1. User selects credit tier and currency (EUR, USD, JPY).
2. Client creates a Stripe PaymentIntent via `POST /v1/payments/create-order`.
3. Stripe.js handles card input and 3D Secure if required.
4. On success, Stripe sends `payment_intent.succeeded` webhook.
5. Backend extracts order details from metadata, decrypts and adds credits, updates cache, broadcasts balance via WebSocket.

### Chargeback Prevention

**Email + 2FA required:** Users must confirm email and set up 2FA (TOTP or passkey) during signup before purchasing -- filters automated scam attempts.

**Tier system (O(1) cached lookup):**

| Tier   | Monthly Limit | Requirement                              |
|--------|--------------|------------------------------------------|
| Tier 0 | No card      | 2+ chargebacks (SEPA only)               |
| Tier 1 | 75 EUR       | Default for new users, or after 1 chargeback |
| Tier 2 | 150 EUR      | 3 consecutive months without chargeback  |
| Tier 3 | 300 EUR      | 6 consecutive months without chargeback  |
| Tier 4 | 500 EUR      | 12 consecutive months without chargeback |

- First chargeback: reset to Tier 1, reset consecutive months counter.
- Second chargeback: reset to Tier 0 (card payments blocked, SEPA only).
- Monthly spending counter resets at start of each calendar month.
- USD/JPY purchases converted to EUR for limit checking.
- SEPA transfers are not subject to tier limits.

### EU Consumer Law Compliance

- Explicit consent checkbox (unchecked by default) for immediate digital service execution at checkout.
- Consent logged with timestamp and hashed IP for compliance.
- Purchase confirmation email + invoice PDF include withdrawal waiver notice (durable medium).
- Once credits used, withdrawal right expires (legally protected).
- Gift cards cannot be refunded once redeemed.
- Unused credits refundable within 14 days.

### Receipt Email Decryption

- **User-initiated payments:** `encrypted_email_address` decrypted with client-provided `email_encryption_key`.
- **Auto top-up payments:** No client key available; uses `encrypted_email_auto_topup` (Vault-transit encrypted server-side when user enables auto top-up).

### SEPA Transfer (Planned)

For high-volume users and Tier 0 users:
- Regular SEPA: credits added when transfer received (1-2 business days).
- SEPA Instant: credits added immediately on confirmation.
- Transaction purpose format: `Account: {user_account_id}, Transaction: {transaction_id}`.
- Incoming transfers monitored via Revolut Business API.
- Mismatched amounts auto-refunded; user notified if account ID present.

## Edge Cases

- Tier 0 users receive clear error message directing them to SEPA transfer.
- Tier data cached on user record for O(1) lookup -- no expensive invoice queries per purchase.
- Currency conversion uses current rates; limits checked in EUR equivalent.

## Related Docs

- [Auto Top-Up](./auto-topup.md) -- monthly subscriptions and planned low-balance triggers
- [Signup & Auth](../core/signup-and-auth.md) -- email confirmation and 2FA setup flow
- Privacy Policy: `shared/docs/privacy_policy.yml`
