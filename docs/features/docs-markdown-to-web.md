# Docs Markdown to Web Pages

> **Status**: Not implemented

## Overview
Auto-convert markdown files from `/docs` to Svelte pages during build process, making docs the single source of truth for the website docs section.

## Build Process
- Convert during Vercel deployment build
- Works in `pnpm dev` mode for local testing
- Source: `/docs/**/*.md` → Output: Svelte pages

## Features

### 1. Copy Button
Copies current page or entire folder (all sub-chapters) as markdown to clipboard.

### 2. Offline Mode (PWA)
Docs work offline by default as a Progressive Web App.

### 3. Download PDF Button
Downloads current page or folder as PDF, generated on-demand (works offline).

### 4. Sidebar Navigation
Reuse existing chat sidebar design from web app for showing chapters/files. Can be opened/closed.

## Implementation Notes
- Use existing sidebar component pattern from web app
- Markdown → Svelte conversion at build time
- PDF generation: client-side (e.g., jsPDF or similar)
- PWA service worker for offline caching

