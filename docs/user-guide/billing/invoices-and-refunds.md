---
status: active
doc_type: guide
audience:
  - users
last_verified: 2026-06-10
claims: []
---

# Invoices and Refunds

## Summary

OpenMates billing records include invoice history for paid cloud usage. Refund eligibility depends on the payment source and the implemented refund windows.

## Invoices

- Invoice files are available from billing settings and account exports when invoices exist for your account.
- Account exports can include invoice history; see [Export Account](../export-account.md).
- Invoices use account identifiers rather than plaintext email addresses where possible to reduce exposed personal data in accounting records.

## Refunds

- Unused purchased credits may be refundable during the supported refund window.
- Gift cards cannot be refunded after redemption.
- Account deletion can include refund handling for eligible unused purchased credits before account data cleanup runs.

## Related

- [Pricing](pricing.md) -- Credits and paid usage
- [Usage & Billing](usage.md) -- Usage history and exports
- [Gift Cards](gift-cards.md) -- Gift card credit behavior
- [Delete Account Architecture](../../architecture/core/delete-account.md) -- Technical refund and deletion sequence
