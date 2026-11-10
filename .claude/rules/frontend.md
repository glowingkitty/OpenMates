---
paths:
  - "frontend/**/*.svelte"
  - "frontend/**/*.ts"
  - "frontend/**/*.tsx"
  - "frontend/**/*.css"
---
Before non-trivial frontend changes read `docs/contributing/standards/frontend.md` (and `DESIGN.md` for visual work).

## Additional Frontend Rules

- **Required props over optional:** Callback props (`onFullscreen`, `onClose`, `onSubmit`) MUST be typed as required, not optional. Use two component variants or a discriminated union type if sometimes unneeded.
- **Sidebar-closed as default test scenario:** When testing chat features, verify with sidebar closed (default for viewports <=1440px). Five bugs were caused by stores assuming sidebar was mounted.
- **Cold-boot verification:** After fixing chat/navigation/sync bugs, verify by clearing IndexedDB and localStorage, then reloading.
- **Reviewed deployed visual smoke:** For larger deployed UI work, run `node frontend/apps/web_app/scripts/visual-smoke.mjs --url https://app.dev.openmates.org/<route> --session <id>`, inspect the laptop and mobile screenshots, and record a pass only with `Defects:` and `Accepted differences:` in `scripts/sessions.py visual-smoke` evidence.
- **Show what you see:** Send every screenshot you open to judge changed UI to the user immediately with `SendUserFile` (one line: what it shows, visible defects). Minimum per UI task: the current look before the change when existing UI is modified, the first rendered result, each later visible revision, and the final state. Do not wait for the final reply and do not replace the image with a description. Component specs attach named screenshots (`testInfo.attach(name, { body: await locator.screenshot(), contentType: 'image/png' })`) for each state worth judging, so the CI artifact contains them.
- **Component preview first:** For any new or modified UI element, component, or screen, verify the focused state on its `/dev/preview/{component-path}?chrome=0` page before any route-level or full E2E spec, following `/verify-component-preview`. The deployed `https://app.dev.openmates.org/dev/preview/...` page shows only the current dev build (use it for the "before" look); the changed candidate is checked by the focused component spec in isolated CI (Vite-only profile, runner-local URL). A component without a `.preview.ts` fixture or focused spec gets one as part of the change. Every preview inspection, test, screenshot, and recording must use `chrome=0` so only the component is visible. Use the `.preview.ts` default fixture for the standard state and encode every non-default input or configuration in URL query parameters such as `variant`, `props`, `theme`, `background`, and `width`; never operate or record the configuration UI. Then cover meaningful hover, focus, click, expanded/collapsed, and on/off states in a focused component spec before route-level specs.
- **External images:** Use `proxyImage()` / `proxyFavicon()` from `imageProxy.ts`.
- **Embed components:** Always use `UnifiedEmbedPreview.svelte` / `UnifiedEmbedFullscreen.svelte` as base.
- **Stores** must NOT import from other stores' internal modules. Use barrel exports.
