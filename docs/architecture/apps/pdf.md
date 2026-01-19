# PDF App Architecture

The PDF app allows for viewing, searching, and analyzing PDF documents.

## Skills

### Search

Searches within PDF documents using high-performance `rg` (ripgrep) functionality to find text, phrases, or patterns.

**Features:**
- Support for searching multiple PDFs in parallel (up to 5 requests)
- Regex pattern matching support using `rg` (ripgrep)
- Case-sensitive and case-insensitive search options
- Returns matched content with page numbers and context
- Shows surrounding text before/after matches
- Efficient text extraction and caching for large PDFs
- Preserves PDF structure (pages, sections) in results

**Input Parameters:**
- `file_ids`: Array of PDF file IDs to search within
- `query`: Search pattern (supports regex)
- `case_sensitive`: Boolean (default: false)
- `context_lines`: Number of lines before/after match to include (default: 2)
- `regex`: Boolean to enable regex mode (default: true)

**Output:**
- Grouped results by file and query
- Each match includes:
  - Page number
  - Matched text
  - Context lines before/after
  - File metadata (name, total pages)

**Processing:**
- Extracts text from PDFs on first search, caches for subsequent searches
- Celery-based processing with parallel requests using `rg` (ripgrep) for search
- Returns results incrementally as searches complete
- Handles both text-based and scanned PDFs (with OCR support)

### Extract Text

Extracts all text content from a PDF and returns it in plain text format.

**Features:**
- Full document text extraction
- Preserves page breaks and basic structure
- Supports batch extraction (multiple PDFs)
- Useful for further processing or analysis

### Analyze Structure

Analyzes PDF structure to identify sections, headings, and document hierarchy.

**Features:**
- Detects headings, sections, and subsections
- Identifies table of contents structure
- Maps page numbers to sections
- Useful for understanding document organization
