---
status: active
last_verified: 2026-06-03
---

# Documentation Site

> All OpenMates documentation is available as a searchable, fast-loading website integrated into the main app.

## What It Does

The documentation site turns all of the project's guides, architecture docs, and help pages into browsable web pages. If you are logged in, you are already authenticated -- no separate login needed.

## How to Access

Visit the **/docs** section of the OpenMates web app. From there you can:

- **Browse** using the sidebar navigation with collapsible folders.
- **Search** across all documentation with full-text search.
- **Copy** a page (or an entire folder of pages) as markdown to your clipboard.
- **Download** any page or folder as a PDF.

## Loading Behavior

The documentation is optimized for fast online loading. The docs index loads a small navigation manifest first, individual pages load only their own content, and the full-text search index loads only when you use search.

## Interactive Testing (for Developers)

The **/docs/api** section includes interactive documentation where you can test endpoints directly. If you are logged in, your credentials are used automatically -- no need to copy and paste keys.

## Tips

- Use the search bar to find specific topics quickly.
- Documentation updates are included with app updates -- you always see the latest version.
- The copy button gives you markdown, not HTML, which is useful for sharing in other tools.

## Related

- [Getting Started](getting-started.md) -- Overview of OpenMates
- [Keyboard Shortcuts](keyboard-shortcuts.md) -- Quick navigation
