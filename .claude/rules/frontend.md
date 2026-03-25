---
description: Frontend coding standards for Svelte 5, TypeScript, and CSS
globs:
  - "frontend/**/*.svelte"
  - "frontend/**/*.ts"
  - "frontend/**/*.tsx"
  - "frontend/**/*.css"
---

@docs/contributing/standards/frontend.md

## Additional Frontend Rules

- **Required props over optional:** Callback props (`onFullscreen`, `onClose`, `onSubmit`) MUST be typed as required, not optional. Use two component variants or a discriminated union type if sometimes unneeded.
- **Sidebar-closed as default test scenario:** When testing chat features, verify with sidebar closed (default for viewports <=1440px). Five bugs were caused by stores assuming sidebar was mounted.
- **Cold-boot verification:** After fixing chat/navigation/sync bugs, verify by clearing IndexedDB and localStorage, then reloading.
- **External images:** Use `proxyImage()` / `proxyFavicon()` from `imageProxy.ts`.
- **Embed components:** Always use `UnifiedEmbedPreview.svelte` / `UnifiedEmbedFullscreen.svelte` as base.
- **Stores** must NOT import from other stores' internal modules. Use barrel exports.
