# OpenMates Website

Marketing and documentation website for OpenMates.

## Documentation System

The website includes an automated documentation system that converts markdown files from `/docs` into interactive web pages.

### Features

1. **📋 Copy Button** - Copy current page or entire folder as markdown to clipboard
2. **📥 Download PDF** - Generate and download PDF from current page or folder (works offline)
3. **📚 Sidebar Navigation** - Hierarchical navigation using the same design as the web app
4. **✈️ Offline Mode** - Full PWA support for offline access to documentation

### How It Works

#### Build Process

1. **Markdown Processing** (`npm run process-docs`)
   - Scans `/docs` directory recursively
   - Generates `src/lib/generated/docs-data.json` with all documentation
   - Preserves markdown content and creates navigation structure

2. **Dynamic Routes** (`/docs/[...slug]`)
   - SvelteKit dynamic route handles all doc pages
   - Loads content from generated JSON
   - Supports prerendering for static generation

3. **Service Worker** (`static/sw.js`)
   - Caches documentation pages for offline access
   - Network-first strategy with cache fallback
   - Automatically activated on page load

### Development

```bash
# Start dev server (processes docs automatically)
pnpm dev

# Process docs manually
pnpm run process-docs

# Build for production
pnpm build
```

### Adding Documentation

1. Add or edit markdown files in `/docs` directory
2. Run `pnpm dev` or `pnpm run process-docs`
3. Documentation will be automatically available at `/docs/[path]`

Example:
- File: `/docs/architecture/ai_model_selection.md`
- URL: `http://localhost:5173/docs/architecture/ai_model_selection`

### Components

- **DocsSidebar.svelte** - Navigation sidebar (reuses web app sidebar design)
- **DocsContent.svelte** - Markdown content renderer
- **pdfGenerator.ts** - Client-side PDF generation utility

### Dependencies

- `marked` - Markdown parsing
- `jspdf` - PDF generation (client-side, works offline)

### PWA Configuration

- `manifest.json` - PWA manifest for installability
- `sw.js` - Service worker for offline support
- `app.html` - Service worker registration

### URL Structure

- `/docs` - Documentation index
- `/docs/[folder]` - Folder view (lists all documents)
- `/docs/[folder]/[file]` - Individual document
- `/docs/[folder]/[subfolder]/[file]` - Nested documents

### Offline Support

The documentation system works fully offline:
1. Visit documentation pages while online (they get cached)
2. Service worker caches pages automatically
3. Offline access works for all visited pages
4. PDF generation works offline (client-side)
5. Copy to clipboard works offline

### Testing Offline Mode

1. Open documentation pages
2. Open DevTools → Application → Service Workers
3. Check "Offline" checkbox
4. Navigate docs - they should still work
5. Try copying and downloading PDFs

## Project Structure

```
frontend/apps/website/
├── scripts/
│   └── process-docs.js          # Markdown processor
├── src/
│   ├── lib/
│   │   ├── components/
│   │   │   ├── DocsSidebar.svelte    # Docs navigation
│   │   │   └── DocsContent.svelte    # Content renderer
│   │   ├── generated/
│   │   │   └── docs-data.json        # Generated docs data (auto-created)
│   │   └── utils/
│   │       └── pdfGenerator.ts       # PDF generation
│   └── routes/
│       └── docs/
│           └── [...slug]/
│               ├── +page.ts          # Data loader
│               └── +page.svelte      # Page component
├── static/
│   ├── manifest.json                 # PWA manifest
│   └── sw.js                         # Service worker
└── app.html                          # HTML template with SW registration
```

## License

See LICENSE file in repository root.
