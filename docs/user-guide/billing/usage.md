---
status: active
doc_type: guide
audience:
  - users
last_verified: 2026-06-10
claims:
  - id: user-guide-billing-usage-source
    type: unit
    claim: Usage viewing and export guidance is grounded in the settings usage component and backend usage endpoints.
    file: scripts/tests/test_user_guide_billing_docs_claims.py
    assertion: user-guide-billing-usage-source
---

# Usage & Billing

## Summary

Track your credit usage across chats, apps, and time periods. Export your history for your records.

## What It Does

The usage section in Settings shows you exactly how your credits have been spent. You can see summaries by month and drill down into individual requests for full details.

## How to View Your Usage

Go to **Settings > Usage** to see:

- **Monthly summaries** grouped by chat, app, or other category.
- **Credit totals** for each month.
- **Detailed breakdowns** when you click on any summary item, including which model was used and how many tokens were processed.

## Browsing Your History

- The last 3 months of detailed usage are available immediately.
- Click **Show more** to load older months. Older data is archived and may take a moment to load the first time.
- Once loaded, archived data is cached so subsequent views are fast.

## Exporting Usage Data

You can download your usage history as a file for your own records:

1. Go to **Settings > Usage**.
2. Click **Export**.
3. Use the currently loaded time window, or load more months first.
4. Usage data downloads as a CSV file.

For a complete data export including chats, settings, and invoices, see [Export Account](../export-account.md).

## What Is Tracked

Each usage entry records:

- **When** the request happened.
- **Which chat** it was in.
- **Which app and skill** were used, for example Web Search or Code Execution.
- **Credits charged**.
- **Model used** and token counts for input and output.

Sensitive usage details like credit amounts, token counts, model, provider, region, and code-run file details are encrypted. App IDs, skill IDs, chat IDs, message IDs, source labels, and API key hashes are stored in cleartext where needed for client-side matching and summaries.

## Tips

- Check your usage regularly to understand which features use the most credits.
- If a charge seems unexpected, export the chat to see the full billing breakdown including every request.
- Usage for incognito chats is grouped under a single Incognito label -- individual chat details are not recorded.

## Related

- [Pricing](pricing.md) -- How credits work
- [Gift Cards](gift-cards.md) -- Adding credits via gift card
- [Export Account](../export-account.md) -- Full data export
