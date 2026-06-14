---
status: active
doc_type: guide
audience:
  - users
last_verified: 2026-06-11
claims:
  - id: user-guide-creators-program-source
    type: unit
    claim: Creator program guidance is grounded in the current creator tip API.
    file: scripts/tests/test_user_guide_product_docs_claims.py
    assertion: user-guide-creators-program-source
---

# Creators Program

> Creator tipping lets users send credits to website or video creators. The current implemented API stores creator income against privacy-preserving owner hashes.

## What It Does

OpenMates includes a creator-tip API for sending credits to a website owner or video creator. Creator tips require the cloud payment system and are not available in self-hosted mode.

## How Revenue Sharing Works

### Supported Activities

The implemented creator endpoint accepts website or video creator identifiers and a positive credit amount. 100% of the tipped credits are assigned to the creator income entry; there is no platform fee on the tip itself.

### How It Works

1. **Creator identifier**: The website domain or video channel identifier is hashed before storage.
2. **Credits are deducted**: The tip amount is charged to the user through the billing service.
3. **Creator income entry**: The tip is recorded for the creator to claim when creator account flows are available.

## For Content Creators

### What Is Happening Now

Creator tips can be recorded for website or video owner identifiers. Public creator account and claim flows are still evolving.

### What Is Coming

- **Creator accounts**: Sign up and verify that you own a website or YouTube channel.
- **Claim your credits**: Once verified, all reserved credits transfer to your account.
- **Dashboard**: View statistics about how your content is being used (aggregated, no individual user data).
- **Claim policies**: Claim windows and unclaimed-credit handling will be documented when the creator account flow is available.

### Verification Methods

- **YouTube channels**: Automatic verification through YouTube.
- **Websites**: Verify by adding a small tag to your site or a DNS record.

### Using Your Credits

Once in your account, credits can be used to:

- Access OpenMates features and digital team mates.
- Support other creators by tipping them (coming soon).

Cash payouts are not available at this time.

## User Tips (Coming Soon)

A tipping feature is planned that will let you send credits directly to creators you appreciate. Tips will go 100% to the creator with no platform fee.

## Privacy

- Creator owner identifiers are hashed before storage.
- Creator tips use billing records for the tipping user, but creator income entries are keyed by the hashed owner identifier.

## Related

- [Pricing](billing/pricing.md) -- How credits work
- [Usage & Billing](billing/usage.md) -- Your credit usage
