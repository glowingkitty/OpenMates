---
status: active
doc_type: guide
audience:
  - users
last_verified: 2026-06-10
claims:
  - id: user-guide-billing-gift-cards-source
    type: unit
    claim: Gift-card redemption is grounded in the implemented redeem form and payment routes.
    file: scripts/tests/test_user_guide_billing_docs_claims.py
    assertion: user-guide-billing-gift-cards-source
---

# Gift Cards

## Summary

Redeem a gift card code to add credits to your account.

## What It Does

Gift cards add their stored credit value to your account. Standard cards are single-use; a narrow reusable-card exception exists for infrastructure and smoke-test cards that may also be restricted to a specific email domain. Once a normal card is redeemed, the credits are available immediately.

## How to Redeem a Gift Card

1. Go to **Settings > Billing > Buy Credits**.
2. Click **I have a gift card**.
3. Enter your gift card code.
4. Click **Redeem code**.
5. Your credit balance updates instantly across all your devices.

If you change your mind, click **Cancel** to return to the credit purchase options.

## What to Know

- **Single-use by default**: Standard cards can only be redeemed once. Server-issued reusable test cards are the exception, not the normal user flow.
- **Case-insensitive**: You can type the code in uppercase or lowercase -- it does not matter.
- **Stored credit value**: The card's configured credit value is added to your current balance.
- **Immediate update**: Successful redemption updates your credit balance on signed-in devices.

## Error Messages

| Message | Meaning |
|---------|---------|
| "Invalid gift card code or code has already been redeemed" | The code was not found. Either it was already used or the code is incorrect. |
| "Invalid gift card: credits value is invalid" | The gift card exists but has an invalid credit value. Contact the person who gave it to you. |

## Tips

- Double-check the code for typos before redeeming.
- Credits from gift cards work exactly the same as purchased credits -- they never expire.
- Your new balance appears on all your signed-in devices right away.

## Related

- [Pricing](pricing.md) -- How credits work
- [Usage & Billing](usage.md) -- Viewing your credit usage
