# Payment processing architecture

- first early alpha stage: EU only cards via stripe
- future update: Paddel & international support 

## Problem

How do keep chargebacks to a minimum?

## Solution

### E-mail confirmation

Users need to confirm their e-mail address during signup before they can purchase credits. Should already filter out most automated scam attempts where bots try to test stolen credit card numbers.

### 2-factor authentication or passkey

Users need to setup 2FA OTP app (if they signup via password) or passkey during signup. Should also filter out most automated scam attempts where bots try to test stolen credit card numbers.

### Limited refund policy

Clearly explain to user that unused credits can be refunded within 14 days. But used credits are not refundable (since we are charged for API usage of AI models and other APIs). Purchased gift cards are excluded and cannot be refunded once they have been used.

**EU/German Consumer Law Compliance:**
- Users must explicitly consent to immediate execution of digital services via unchecked checkbox at checkout
- Consent is logged with timestamp and hashed IP address for compliance
- Purchase confirmation email includes withdrawal waiver notice (durable medium requirement)
- Invoice PDF includes withdrawal waiver notice
- Once credits are used, withdrawal right expires (legally protected)
- Gift cards cannot be refunded once redeemed

### Tier system

Limit potential fees by chargebacks by limiting the amount that can be purchased per month via card payment, until user is more trusted. Limits are based on consecutive months without chargebacks.

The tier system uses efficient O(1) checking by caching tier data on the user record, avoiding expensive invoice queries on every purchase.

| Tier | Monthly Limit (EUR) | Requirement |
| --- | --- | --- |
| Tier 0 | No card payments | 2+ chargebacks (SEPA transfer only) |
| Tier 1 | 75€ | New users (default) or after 1 chargeback |
| Tier 2 | 150€ | 3 consecutive months without chargeback |
| Tier 3 | 300€ | 6 consecutive months without chargeback |
| Tier 4 | 500€ | 12 consecutive months without chargeback |

**Tier Progression:**
- Users start at Tier 1 (75€/month limit)
- After 3 consecutive months with successful payments and no chargebacks → Tier 2 (150€/month)
- After 6 consecutive months without chargeback → Tier 3 (300€/month)
- After 12 consecutive months without chargeback → Tier 4 (500€/month)
- Users with 1 chargeback: Maximum tier is Tier 1 (cannot progress beyond)
- Users with 2+ chargebacks: Tier 0 (no card payments, SEPA only)

**Chargeback Penalty System (Graduated):**
- **First chargeback**: Reset to Tier 1 (75€/month limit), reset consecutive months counter to 0
- **Second chargeback**: Reset to Tier 0 (no card payments allowed, SEPA transfer only)
- Chargeback count is tracked and prevents tier progression beyond Tier 1

**Tier Reset:**
- First chargeback: Resets to Tier 1, resets consecutive months counter to 0
- Second chargeback: Resets to Tier 0 (no card payments), resets consecutive months counter to 0
- Monthly spending counter resets automatically at the start of each calendar month

**Implementation Details:**
- Tier limits are checked before creating payment orders (fast cached lookup)
- Tier 0 users are blocked from card payments with clear error message directing to SEPA
- Monthly spending is tracked in encrypted field on user record
- Currency conversion: USD and JPY purchases are converted to EUR for limit checking
- Purchase count limits removed: only total monthly spending value is limited
- SEPA transfers are not subject to tier limits (for legitimate power users, including Tier 0 users)

### SEPA transfer / Sofortüberweisung

For legitimate users who use OpenMates a lot and therefore need more credits, allowing SEPA transfer or Sofortüberweisung is an option.

For regular SEPA transfer, inform user that credits will be added to their account once transaction is received (typically within 1-2 business days).

For SEPA Instant Credit Transfer, wait in web app UI for transaction to be confirmed and immediately add credits to the user's account.

```text
Transaction purpose: "Account: {user_account_id}, Transaction: {transaction_id}"
Amount: {amount for credits including VAT}
```

> During parsing make sure even if only the account id and transaction id are present without 'Account:' or 'Transaction:' prefix, it is still parsed correctly.

Incoming SEPA transfers must be monitored automatically via Revolut Business API and once transfer is received, credits should be added to the user's account.
If a SEPA transfer is received without account id in transaction purpose or with value not matching the amount for credits including VAT, it should be auto refunded and if the account id is present, the user should be notified.