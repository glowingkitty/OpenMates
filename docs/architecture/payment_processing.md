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

Clearly explain to user that unused credits can be refunded within 30 days. But used credits are not refundable (since we are charged for API usage of AI models and other APIs)

### Tier system

Limit potential fees by chargebacks by limiting the amount of credits that can be purchased per month, until user is more trusted.

| | Tier 1 | Tier 2 | Tier 3 |
| --- | --- | --- | --- |
| Max credits purchases per month | 3 | 5 | unlimited |
| Max purchases per month (via card) | 50€ | 100€ | unlimited |

**Tier 1:** New users

**Tier 2:** Users with credit purchases in 3 separate months (doesn't need to be consecutive)

**Tier 3:** Users with credit purchases in 6 separate months (doesn't need to be consecutive)

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