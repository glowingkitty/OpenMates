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
- **Reviewed deployed visual smoke:** For larger deployed UI work, run `node frontend/apps/web_app/scripts/visual-smoke.mjs --url https://app.dev.openmates.org/<route> --session <id>`, inspect the laptop and mobile screenshots, and record a pass only with `Defects:` and `Accepted differences:` in `scripts/sessions.py visual-smoke` evidence.
- **Component preview first:** For any new or modified UI element, component, or screen, verify the focused state at `https://app.dev.openmates.org/dev/preview/{component-path}?chrome=0` before broader flow specs. Every preview inspection, test, screenshot, and recording must use `chrome=0` so only the component is visible. Use the `.preview.ts` default fixture for the standard state and encode every non-default input or configuration in URL query parameters such as `variant`, `props`, `theme`, `background`, and `width`; never operate or record the configuration UI. Then cover meaningful hover, focus, click, expanded/collapsed, and on/off states in a focused component spec before route-level specs.
- **External images:** Use `proxyImage()` / `proxyFavicon()` from `imageProxy.ts`.
- **Embed components:** Always use `UnifiedEmbedPreview.svelte` / `UnifiedEmbedFullscreen.svelte` as base.
- **Stores** must NOT import from other stores' internal modules. Use barrel exports.
