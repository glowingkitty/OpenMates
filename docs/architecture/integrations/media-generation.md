---
status: active
last_verified: 2026-03-24
key_files:
  - frontend/apps/web_app/src/routes/dev/media/+page.svelte
  - frontend/apps/web_app/src/routes/dev/media/components/MediaCanvas.svelte
  - frontend/apps/web_app/src/routes/dev/media/components/DeviceIframe.svelte
  - frontend/apps/web_app/src/routes/dev/media/components/DevicePhone.svelte
  - frontend/apps/web_app/src/routes/dev/media/components/DeviceLaptop.svelte
  - frontend/apps/web_app/src/routes/dev/media/components/BrandHeader.svelte
  - frontend/apps/web_app/src/routes/dev/media/components/ThemeScope.svelte
  - frontend/apps/web_app/src/routes/dev/media/scripts/capture.spec.ts
---

# Media Generation

> System for generating OG images, social graphics, and Instagram content using real app screenshots via device-framed iframes and Playwright capture.

## Why This Exists

Marketing assets (OG images, Instagram posts/stories/carousels) need to show the actual app UI. Instead of hand-maintained mock components that drift from reality, device frames contain iframes that load the real app in media mode (`?media=1`), ensuring screenshots always match the current UI.

## How It Works

### Media Mode (`?media=1`)

When the main app detects `?media=1`:
1. Adds `body.media-mode` CSS class (hides notifications, cookie banner, login overlay, footer, dev console, keyboard hints)
2. Waits for `document.fonts.ready`
3. Adds `.media-app-ready` to `document.body` (signals parent iframe)

**URL parameters** (only active with `?media=1`):

| Parameter | Values | Effect |
|-----------|--------|--------|
| `seed` | Integer | Seeded PRNG for deterministic suggestion card order |
| `sidebar` | `open`/`closed` | Force sidebar state regardless of viewport |
| `inspirations` | `none`/`fixed` | Hide or show daily inspiration banner |
| `#chat-id` | Chat UUID | Open a specific chat |

### Template Architecture

```
src/routes/dev/media/
├── +page.svelte                    # Gallery index
├── components/                     # Reusable: MediaCanvas, DeviceIframe, DevicePhone,
│                                   #   DeviceLaptop, BrandHeader, ThemeScope
├── data/                           # YAML config loader + TypeScript types
├── templates/                      # Individual templates
│   ├── og-github/                  # 1200x630
│   ├── og-social/                  # 1200x630
│   ├── instagram-single/           # 1080x1080
│   ├── instagram-carousel/         # 1080x1080 multi-slide
│   └── instagram-story/            # 1080x1920
└── scripts/capture.spec.ts         # Playwright automation
```

Each template has a `config.yml` (dimensions, brand info, iframe URLs) and a `+page.svelte`. Templates are dev-only (`/dev/` routes gated by hostname).

### Components

- **`MediaCanvas`** -- exact pixel dimensions, `.media-ready` sentinel for Playwright, dark gradient background
- **`DeviceIframe`** -- loads real app via iframe, watches for `.media-app-ready` via MutationObserver, calls `onready()`
- **`DevicePhone` / `DeviceLaptop`** -- CSS-only device frames with content slots
- **`BrandHeader`** -- logo + headline + feature bullet points
- **`ThemeScope`** -- forces dark/light CSS variables in scoped container

### Screenshot Ready Signal Flow

1. Playwright navigates to `/dev/media/templates/{template}`
2. Template creates `DeviceIframe` components with `/?media=1...` URLs
3. App loads, renders, waits for fonts, adds `.media-app-ready`
4. `DeviceIframe` detects via MutationObserver, calls `onready()`
5. All iframes ready -> template sets `ready=true` on `MediaCanvas`
6. `MediaCanvas` adds `.media-ready` CSS class
7. Playwright detects `.media-ready`, captures screenshot (30s timeout)

### Capture Commands

```bash
cd frontend/apps/web_app
npx playwright test src/routes/dev/media/scripts/capture.spec.ts          # All
npx playwright test --grep "og-github" .../capture.spec.ts                # Specific
OUTPUT_DIR=./marketing npx playwright test .../capture.spec.ts            # Custom output
MEDIA_BASE_URL=http://localhost:5173 npx playwright test .../capture.spec.ts  # Local dev
RECORD_VIDEO=1 npx playwright test --grep "instagram-story" ...           # Video
```

Output goes to `media-output/` by default.

### Canonical Format Dimensions

| Format | Width | Height | Use Case |
|--------|-------|--------|----------|
| `og` | 1200 | 630 | GitHub, Twitter, LinkedIn, Facebook |
| `instagram-square` | 1080 | 1080 | Instagram post |
| `instagram-story` | 1080 | 1920 | Instagram/TikTok story |
| `twitter-header` | 1500 | 500 | Twitter/X profile header |
| `github-social` | 1280 | 640 | GitHub social preview |

## Edge Cases

- **Login screen in iframe:** Media test account not logged in. Playwright capture script logs in via `beforeAll`.
- **Timeout:** `.media-ready` never set if an iframe fails. Check browser console for errors, increase `WAIT_TIMEOUT`.
- **Non-deterministic content:** Missing `&seed=N` parameter. Ensure consistent seed across all iframe URLs.
- **Sidebar won't open:** Missing `&sidebar=open` or viewport too small. Media mode sidebar override ignores viewport width.

## Related Docs

- [Web App Architecture](../frontend/web-app.md) -- main app structure
- [Daily Inspiration](../frontend/daily-inspiration.md) -- `inspirations` parameter control
