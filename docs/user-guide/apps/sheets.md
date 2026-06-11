---
status: active
doc_type: guide
audience:
  - end-users
last_verified: 2026-06-11
claims:
  - id: user-guide-apps-sheets-source
    type: unit
    claim: The Sheets guide is grounded in sheet embed preview/fullscreen components.
    file: scripts/tests/test_user_guide_app_docs_claims.py
    assertion: user-guide-apps-sheets-source
---

# Sheets

> View tables and spreadsheets with sorting, and export them as files.

## What It Does

The Sheets app automatically detects tables in your mate's responses and displays them as interactive spreadsheet previews. When your mate creates a comparison table, a data summary, or any tabular data, it appears as a clean, readable card you can open in fullscreen.

**How it works:**

- Markdown tables in your mate's responses are automatically converted into sheet previews.
- Click a preview to open the full table in a reader view with sorting and filtering.
- You can download tables as Excel (.xlsx) or CSV files.
- Tables can have titles for easy identification when multiple tables appear in a conversation.

## How to Use It

- Ask your mate to organise data as a table: "Compare these three laptops in a table"
- Request data summaries: "Create a table of the pros and cons"
- Your mate automatically formats tabular data as sheet previews.

## Tips

- Tables appear as compact preview cards showing the first few rows and columns. Open in fullscreen to see the complete data.
- Multiple tables in one message are grouped together for easy scrolling.
- The download feature is useful for getting data into your own spreadsheet software.

## Related

- [Docs](./docs.md) -- Create formatted text documents
- [PDF](./pdf.md) -- Read and search PDF documents
- [Math](./math.md) -- Accurate calculations and data analysis
