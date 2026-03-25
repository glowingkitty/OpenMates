---
status: active
last_verified: 2026-03-24
---

# PDF

> Upload, read, search, and visually inspect PDF documents.

## What It Does

The PDF app processes uploaded PDF documents so your mate can read their content, search for specific text, and visually examine individual pages. It works with both text-based and scanned PDFs.

**Available skills:**

- **Read** -- Loads the text content of specific pages from an uploaded PDF. Your mate uses the table of contents (automatically detected) to find the most relevant sections. Good for getting summaries, answering questions about the content, or extracting information.
- **Search** -- Searches for specific words or phrases across all pages of a PDF. Returns matching text with surrounding context and page numbers. Works instantly without needing a separate search engine.
- **View** -- Shows your mate what specific pages look like visually. Useful for pages with diagrams, charts, complex tables, or images that text extraction might not capture well.

**How PDF processing works:**

- When you upload a PDF, it is processed in the background.
- The text on each page is extracted, and page screenshots are taken for visual analysis.
- A table of contents is automatically detected for documents with more than 10 pages.
- Your mate can then use any of the three skills above to work with the document.

## How to Use It

- Upload and ask: Upload a PDF and ask "What does this document say about pricing?"
- Search: "Find where it mentions 'delivery terms' in this contract"
- Summarise: "Give me a summary of chapter 3"
- Visual analysis: "Show me the chart on page 5 and explain what it shows"
- Navigate: "What topics are covered in this document?" (uses the auto-detected table of contents)

## Screenshots

![PDF read preview](../../images/user-guide/apps/pdf/previews/read/finished.jpg)

![PDF search results](../../images/user-guide/apps/pdf/previews/search/finished.jpg)

## Tips

- Your mate can see the table of contents and page-by-page word counts, so it can jump directly to the most relevant sections.
- For scanned documents, text is extracted using optical character recognition.
- The visual analysis skill is helpful when a page contains charts, diagrams, or complex layouts that text alone does not capture.
- You can ask about multiple sections in sequence -- your mate remembers what it has already read from the document.

## Related

- [Docs](./docs.md) -- Create new formatted documents
- [Code](./code.md) -- Look up programming documentation
- [Web](./web.md) -- Read web content
