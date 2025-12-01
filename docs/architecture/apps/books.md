# Books app architecture

## Skills

### Search

Searches within uploaded ebooks (EPUB, MOBI) and book excerpts using grep-like pattern matching. For PDF searching, see [PDF App](./pdf.md).

**Features:**
- Support for multiple ebooks and search queries in a single call (processed in parallel, up to 5 requests)
- Regex pattern matching support for finding passages, chapters, quotes
- Case-sensitive and case-insensitive search options
- Returns matched passages with context (surrounding paragraphs/chapters) and page numbers
- Preserves formatting for ebook readers (EPUB, MOBI)
- Efficient text extraction and caching for large ebooks

**Input Parameters:**
- `file_ids`: Array of ebook file IDs
- `query`: Search pattern (e.g., "character name", "theme", or regex pattern)
- `case_sensitive`: Boolean (default: false)
- `context_lines`: Number of lines before/after match (default: 3)
- `regex`: Boolean to enable regex mode (default: false)

**Output:**
- Results grouped by book and query
- Each match includes:
  - Page or chapter number
  - Matched passage
  - Surrounding context
  - Book metadata (title, author)

### Summarize by Chapter

Generates summaries of specific chapters or sections within books.

**Features:**
- Extract and summarize individual chapters
- Support for multiple chapters in one request
- Customizable summary length (brief, detailed, key points)
- Identifies themes, plot points, and character development

## Settings & memories

### To read list

List of books which one still wants to read and what one hopes to get out of them if anything.