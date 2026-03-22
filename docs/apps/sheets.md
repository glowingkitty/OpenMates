# Sheets app architecture

The Sheets app allows for viewing and editing spreadsheets.

## Skills

### Search

Searches spreadsheets and uploaded table data for values, formulas, or patterns using grep-like functionality.

**Features:**

- Support for searching multiple spreadsheets in parallel (up to 5 requests)
- Searches cell values, formula results, and formula text
- Case-sensitive and case-insensitive search options
- Regex pattern matching for complex queries
- Returns matched cells with row/column references and context
- Shows surrounding cells for context
- Works with Excel, Google Sheets, OpenOffice Calc formats

**Input Parameters:**

- `file_ids`: Array of spreadsheet file IDs
- `query`: Search pattern (e.g., "value", regex pattern, formula pattern)
- `case_sensitive`: Boolean (default: false)
- `search_formulas`: Boolean to search formula text instead of values (default: false)
- `regex`: Boolean to enable regex mode (default: false)

**Output:**

- Results grouped by spreadsheet and query
- Each match includes:
  - Cell reference (e.g., A1, B3:D5)
  - Cell value or formula
  - Row and column context
  - Sheet name (if multiple sheets)
  - Match count per spreadsheet

### Filter & Aggregate

Filters rows based on criteria and performs aggregations (sum, count, average) across multiple data ranges.

**Features:**

- Multiple filter conditions with AND/OR logic
- Aggregation functions (SUM, COUNT, AVERAGE, MIN, MAX, etc.)
- Support for date and numeric comparisons
- Returns filtered results and summary statistics

## Rendering Technology

### Design Decision: Custom Read-Only View (no external spreadsheet library)

> **Status**: Decided 2026-02-13
> **Decision**: Build a custom read-only table renderer with sorting and filtering. No external spreadsheet library for now.

#### Context

We evaluated several JavaScript spreadsheet/data-grid libraries for rendering sheet embeds in fullscreen mode. Requirements:

- Read-only display with sorting and filtering (short-term)
- Full editing with formulas, cell formatting, colors (long-term)
- AGPL-3.0 license compatibility (OpenMates is AGPL)
- Fast loading, minimal bundle size
- Works with Svelte 5

#### Libraries Evaluated

| Library                 | License                     | Bundle Size | AGPL Compatible | Verdict                                                                                                                     |
| ----------------------- | --------------------------- | ----------- | --------------- | --------------------------------------------------------------------------------------------------------------------------- |
| **Handsontable** (v16+) | Proprietary ($899/dev/year) | ~400KB      | N/A (not free)  | **Rejected** — requires paid commercial license since v7.0.0 (2019). No MIT community edition exists anymore.               |
| **AG Grid Community**   | MIT                         | ~300KB      | Yes             | Good data grid, but not a spreadsheet — no formulas/cell formatting. Would require full replacement when editing is needed. |
| **RevoGrid**            | MIT (open-core)             | ~150KB      | Yes             | Has Svelte wrapper. Similar to AG Grid — data grid, not spreadsheet. Smaller community.                                     |
| **Jspreadsheet CE**     | MIT                         | ~80KB       | Yes             | True spreadsheet with basic formulas. Good upgrade path. But adds dependency for features we can build ourselves.           |
| **Univer**              | Apache-2.0                  | ~3MB+       | Yes             | Full Google Sheets-like engine. Overkill and too heavy for read-only display.                                               |
| **Fortune Sheet**       | MIT                         | ~500KB      | Yes             | Excel-like UI. React-oriented, harder Svelte integration.                                                                   |

#### Decision

**Build a custom read-only view** instead of adding any external dependency:

1. **Zero bundle size impact** — no new dependency
2. **No dependency maintenance/security surface** — fewer supply chain risks for an AGPL project
3. **Full design system control** — matches our CSS custom properties and theme perfectly
4. **Simple implementation** — table data is already parsed into arrays in `sheetEmbedContent.ts`; sorting = `Array.sort()`, filtering = `Array.filter()`, CSV export = string concatenation
5. **Deferred library choice** — when full editing (formulas, cell formatting) is needed later, we can make an informed choice based on actual requirements and what's available at that time

The previous doc references to "handsontable & HyperFormula" were aspirational and never implemented. Neither package was ever installed.

#### Future: Editing Mode

When editing support is needed, re-evaluate:

- **Jspreadsheet CE** (MIT) or **Univer** (Apache-2.0) as the most likely candidates
- Handsontable only if commercial license budget is approved
- The custom read-only view will remain as the default for non-editable contexts

---

## Embedded previews

### Sheet

Used every time a spreadsheet is contained in a message in the chat history or message input field.
For uploaded Microsoft Excel, Google Sheets, OpenOffice Calc spreadsheets.

Can include a title via the title standard: `<!-- title: "..." -->` in the line before the table.

Data processing is done via unified `parseMessage()` function described in [message_parsing.md](../architecture/message-parsing.md).

#### Table Auto-Detection Pipeline

> **Status**: Implemented 2026-02-13

Markdown tables in AI responses are automatically detected and converted to `sheets-sheet` embed nodes. The pipeline works in three stages:

1. **Markdown → TipTap**: `markdown-it` parses markdown tables into TipTap `{ type: "table", content: [tableRow...] }` nodes.

2. **Embed detection** ([embedParsing.ts#parseEmbedNodes()](../../frontend/packages/ui/src/message_parsing/embedParsing.ts)): Scans raw markdown text for table patterns (header row + separator row + data rows). Creates `sheets-sheet` embed attributes with parsed table data, row/col counts, and content stored via `contentRef` in the client EmbedStore.

3. **Document enhancement** ([documentEnhancement.ts#enhanceDocumentWithEmbeds()](../../frontend/packages/ui/src/message_parsing/documentEnhancement.ts)): Matches TipTap `table` nodes to their corresponding `sheets-sheet` embed attributes using three strategies:
   - **Content match**: Reconstructs markdown text from the TipTap table node (`extractTableTextFromNode()`) and compares against the embed's stored code content with normalized whitespace.
   - **Dimension match**: For stream embeds (where content is in EmbedStore, not inline), matches by row/col count.
   - **Fallback**: If exactly one unmatched sheet embed remains, uses it.

   The matched table node is replaced with `{ type: "paragraph", content: [{ type: "embed", attrs: sheetEmbed }] }`, which the Svelte embed renderer picks up as a `SheetEmbedPreview` or `SheetEmbedFullscreen` component.

**Key files:**

- Table detection: [embedParsing.ts](../../frontend/packages/ui/src/message_parsing/embedParsing.ts) (lines 396-550)
- Table → embed replacement: [documentEnhancement.ts](../../frontend/packages/ui/src/message_parsing/documentEnhancement.ts) (`findMatchingEmbedForTable()`, `extractTableTextFromNode()`)
- Entry point: [parse_message.ts](../../frontend/packages/ui/src/message_parsing/parse_message.ts)
- Table data parsing: [sheetEmbedContent.ts](../../frontend/packages/ui/src/components/embeds/sheets/sheetEmbedContent.ts)

#### Sheet | Processing

[![Sheet | Processing | Preview & Fullscreen view in mobile & desktop](../../images/apps/sheets/previews/sheet/processing.jpg)](https://www.figma.com/design/PzgE78TVxG0eWuEeO6o8ve/Website?node-id=3514-41257&t=V4FPCQaihiRx7h7e-4)

When the sheet is still being processed, those layouts are used.

##### Sheet | Processing | Input example (Markdown table)

```markdown
<!-- title: "Device comparison" -->

| Column 1 | Column 2 | Column 3 |
| -------- | -------- | -------- |
| Row 1    | Row 1    | Row 1    |
| Row 2    | Row 2    | Row 2    |
| Row 3    | Row 3    |
```

> Note: Later we should also add support for rendering Google Sheets JSON structure for more complex sheets.

##### Sheet | Processing | Output

- tiptap node (lightweight) with:
  - cell count (number)
    - contentRef (string) pointing to full sheet content in client EmbedStore (memory + IndexedDB)
    - contentHash? (string, sha256 when finished; used for preview caching)
    - preview is derived at render-time and limited to cells A1:D6 only
    - "Write" text and 'modify' icon, indicating that the sheet is still being processed

- Figma design:
  - [Preview mobile](https://www.figma.com/design/PzgE78TVxG0eWuEeO6o8ve/Website?node-id=3514-41345&t=R9j0Nv3WdNV351nc-4)
  - [Preview desktop](https://www.figma.com/design/PzgE78TVxG0eWuEeO6o8ve/Website?node-id=3514-41360&t=R9j0Nv3WdNV351nc-4)

##### Sheet | Processing | Fullscreen view

Show sheet in fullscreen mode, with preview element in bottom of the screen (with cell count and "Write" text and icon, indicating that the sheet is still being processed). The download and copy to clipboard buttons are also available in the top left corner. Top right corner has the minimize button, which closes the fullscreen view.

Figma design:

- [Mobile](https://www.figma.com/design/PzgE78TVxG0eWuEeO6o8ve/Website?node-id=3415-40088&t=R9j0Nv3WdNV351nc-4)
- [Desktop](https://www.figma.com/design/PzgE78TVxG0eWuEeO6o8ve/Website?node-id=3415-40111&t=R9j0Nv3WdNV351nc-4)

#### Sheet | Finished

[![Sheet | Finished | Preview & Fullscreen view in mobile & desktop](../../images/apps/sheets/previews/sheet/finished.jpg)](https://www.figma.com/design/PzgE78TVxG0eWuEeO6o8ve/Website?node-id=3514-41375&t=R9j0Nv3WdNV351nc-4)

When the sheet is finished being processed, those layouts are used.

##### Sheet | Finished | Input example (Markdown table)

```markdown
<!-- title: "Device comparison" -->

| Column 1 | Column 2 | Column 3 |
| -------- | -------- | -------- |
| Row 1    | Row 1    | Row 1    |
| Row 2    | Row 2    | Row 2    |
| Row 3    | Row 3    | Row 3    |
```

> Note: Later we should also add support for rendering Google Sheets JSON structure for more complex sheets.

##### Sheet | Finished | Output

- tiptap node (lightweight) with:
  - cell count (number)
    - title or filename (string)
    - contentRef (string) pointing to full sheet content in client ContentStore (loaded on fullscreen)
    - contentHash (string, sha256 for immutable snapshot/caching)
    - preview is derived at render-time and limited to cells A1:D6 only

- Figma design:
  - [File preview mobile](https://www.figma.com/design/PzgE78TVxG0eWuEeO6o8ve/Website?node-id=3019-35325&t=R9j0Nv3WdNV351nc-4)
  - [File preview desktop](https://www.figma.com/design/PzgE78TVxG0eWuEeO6o8ve/Website?node-id=3424-41865&t=R9j0Nv3WdNV351nc-4)
  - [Table preview mobile](https://www.figma.com/design/PzgE78TVxG0eWuEeO6o8ve/Website?node-id=3425-42255&t=R9j0Nv3WdNV351nc-4)
  - [Table preview desktop](https://www.figma.com/design/PzgE78TVxG0eWuEeO6o8ve/Website?node-id=3425-42248&t=R9j0Nv3WdNV351nc-4)

##### Sheet | Finished | Fullscreen view

Show sheet in fullscreen mode, with preview element in bottom of the screen (with filename, cell count and filetype). The download, copy to clipboard and modify buttons are also available in the top left corner. Top right corner has the minimize button, which closes the fullscreen view. Full content is resolved via `contentRef` from the client EmbedStore and rendered with a custom read-only table view in fullscreen (see [Rendering Technology](#rendering-technology) for rationale).

> Note: Modify functionality is not yet planned out and should be added in the future. When editing is implemented, the read-only custom renderer will be replaced with a full spreadsheet library.

Figma design:

- [Mobile](https://www.figma.com/design/PzgE78TVxG0eWuEeO6o8ve/Website?node-id=3514-41456&t=R9j0Nv3WdNV351nc-4)
- [Desktop](https://www.figma.com/design/PzgE78TVxG0eWuEeO6o8ve/Website?node-id=3514-41469&t=R9j0Nv3WdNV351nc-4)

#### Sheet | Chat example

[![Sheet | Chat example](../../images/apps/sheets/previews/sheet/chat_example.jpg)](https://www.figma.com/design/PzgE78TVxG0eWuEeO6o8ve/Website?node-id=3514-41526&t=R9j0Nv3WdNV351nc-4)

Shows how sheet previews are rendered in a chat message. Mobile / desktop layouts are used depending on the viewport width.

**Multiple previews:**

General rule for all previews/apps: If multiple previews of the same type are rendered in a chat message, they should be grouped together in a horizontally scrollable container. The previews must be sorted from status "Processing" (left) to "Finished" (right), so that the user can always see if there are any unfinished previews. Scroll bar is visible if there are scrollable elements. Uses "mobile" layout of the previews for mobile, "desktop" layout for desktop.

**Single preview:**

If there is only one preview of the same type, no additional container with scrollbar is needed. If a text is following the preview, it will be regularly rendered below the preview. Same if a preview or group of previews of another type is following the preview. Uses "desktop" layout of the preview both for mobile and desktop.
