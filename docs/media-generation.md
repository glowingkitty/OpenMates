# Media Generation System

System for generating OG images, social media graphics, Instagram carousels/stories,
and marketing materials using real app screenshots.

**Location:** `frontend/apps/web_app/src/routes/dev/media/`
**Access:** Dev environments only (`/dev/` routes are gated by hostname check)
**Technology:** SvelteKit routes + real app iframes + Playwright screenshots

---

## How It Works

Device frames (phone, laptop) contain **iframes that load the real app** in media
mode (`?media=1`). This ensures screenshots always match the actual UI — no more
hand-maintained mock components that drift from the real app.

### Media Mode (`?media=1`)

When the main app detects `?media=1` in the URL, it:

1. Adds `body.media-mode` CSS class — hides notifications, cookie banner, login
   overlay, footer, dev console, keyboard hints
2. Waits for all fonts to load
3. Adds `.media-app-ready` class to `document.body` — signals the parent iframe
   that the app is ready for screenshot

### URL Parameters

All parameters are only active when `?media=1` is set:

| Parameter | Values | Effect |
|-----------|--------|--------|
| `media` | `1` | Enable media mode (required) |
| `seed` | Any integer | Seeded PRNG for deterministic suggestion card order |
| `sidebar` | `open` \| `closed` | Force sidebar state regardless of viewport |
| `inspirations` | `none` \| `fixed` | Hide or show fixed daily inspiration banner |
| `#chat-id` | Chat UUID | Open a specific chat (existing deep link) |

**Example URLs:**
```
/?media=1&seed=42&sidebar=closed&inspirations=fixed     # New chat view
/?media=1&seed=42&sidebar=open#chat-id={uuid}           # Chat with sidebar
```

---

## Quick Start

### 1. Browse templates

```
https://app.dev.openmates.org/dev/media
```

### 2. Capture screenshots

```bash
cd frontend/apps/web_app

# Capture all templates:
npx playwright test src/routes/dev/media/scripts/capture.spec.ts

# Capture a specific template:
npx playwright test --grep "og-github" src/routes/dev/media/scripts/capture.spec.ts

# Custom output directory:
OUTPUT_DIR=./marketing npx playwright test src/routes/dev/media/scripts/capture.spec.ts

# Custom base URL (local dev):
MEDIA_BASE_URL=http://localhost:5173 npx playwright test src/routes/dev/media/scripts/capture.spec.ts

# Record video:
RECORD_VIDEO=1 npx playwright test --grep "instagram-story" src/routes/dev/media/scripts/capture.spec.ts
```

Output goes to `media-output/` by default.

---

## Architecture

```
src/routes/dev/media/
├── +layout.ts              # ssr=false, prerender=false
├── +page.svelte            # Gallery index — lists all templates with previews
│
├── components/             # Reusable media components
│   ├── MediaCanvas.svelte          # Wrapper: exact pixel dimensions + .media-ready sentinel
│   ├── DeviceIframe.svelte         # Iframe wrapper: loads real app, detects .media-app-ready
│   ├── ThemeScope.svelte           # Forces dark/light CSS variables in scoped container
│   ├── DevicePhone.svelte          # Phone frame with screen content slot
│   ├── DeviceLaptop.svelte         # Laptop frame with browser chrome + screen slot
│   └── BrandHeader.svelte          # Logo + headline + feature bullet points
│
├── data/                   # Data loading and types
│   ├── types.ts                    # TypeScript interfaces for configs
│   └── loader.ts                   # YAML config loader (Vite glob import)
│
├── templates/              # Individual template routes
│   ├── og-github/                  # 1200×630 GitHub OG image
│   │   ├── config.yml
│   │   └── +page.svelte
│   ├── og-social/                  # 1200×630 social sharing
│   │   ├── config.yml
│   │   └── +page.svelte
│   ├── instagram-single/           # 1080×1080 Instagram post
│   │   ├── config.yml
│   │   └── +page.svelte
│   ├── instagram-carousel/         # 1080×1080 multi-slide
│   │   ├── config.yml
│   │   └── +page.svelte
│   └── instagram-story/            # 1080×1920 story
│       ├── config.yml
│       └── +page.svelte
│
└── scripts/
    └── capture.spec.ts     # Playwright capture automation
```

---

## Template Config YAML

Each template has a `config.yml` that defines dimensions, brand info, and iframe URLs:

```yaml
template: og-github
format: og
width: 1200
height: 630

brand:
  headline: "Digital team mates"
  subtitle: "For everyone."
  features:
    - "AI for everyday tasks & learning"
    - "Privacy focus"

phone:
  iframe_src: "/?media=1&seed=42&sidebar=closed&inspirations=fixed"
  screen_width: 220
  screen_height: 430
  scale: 0.52

laptop:
  iframe_src: "/?media=1&seed=42&sidebar=open&inspirations=none"
  screen_width: 560
  screen_height: 340
  scale: 0.58
```

### Instagram Carousel Config

Carousels define multiple slides. Device slides use `iframe_src`:

```yaml
slides:
  - type: hero
    headline: "Meet your digital team mates"
    subtitle: "AI for everyone."
    iframe_src: "/?media=1&seed=42&sidebar=closed&inspirations=fixed"
    device: phone

  - type: chat
    headline: "Ask anything"
    iframe_src: "/?media=1&seed=42&sidebar=closed"
    device: phone

  - type: feature            # No device — static content
    headline: "Built different"
    features:
      - "No subscription"
      - "Privacy focus"

  - type: cta
    headline: "Try it free"
    subtitle: "openmates.org"
    cta_text: "Get Started"
```

---

## Reusable Components

### DeviceIframe

Loads the real app inside an iframe at a given URL, scaled via CSS transform.
Watches for `.media-app-ready` class on the iframe's body via MutationObserver
(same-origin) and calls `onready()` when detected.

```svelte
<DeviceIframe
  src="/?media=1&seed=42&sidebar=closed"
  width={220}
  height={430}
  scale={0.52}
  onready={() => { phoneReady = true; }}
/>
```

### MediaCanvas

Universal wrapper that provides exact pixel dimensions, `.media-ready` sentinel
for Playwright, dark gradient background, and center alignment.

```svelte
<MediaCanvas width={1200} height={630} ready={allIframesReady} borderRadius={16}>
  {#snippet content()}
    ...
  {/snippet}
</MediaCanvas>
```

### DevicePhone / DeviceLaptop

CSS-only device frames with content slots:

```svelte
<DevicePhone screenWidth={220} screenHeight={430}>
  {#snippet screen()}
    <DeviceIframe src="/?media=1&seed=42" width={220} height={430} scale={0.52} />
  {/snippet}
</DevicePhone>
```

---

## Creating New Templates

### 1. Create the directory

```bash
mkdir -p src/routes/dev/media/templates/my-template
```

### 2. Add config.yml

```yaml
template: my-template
format: og
width: 1200
height: 630

phone:
  iframe_src: "/?media=1&seed=42&sidebar=closed"
  screen_width: 220
  screen_height: 430
  scale: 0.52
```

### 3. Add +page.svelte

```svelte
<script lang="ts">
  import MediaCanvas from '../../components/MediaCanvas.svelte';
  import DevicePhone from '../../components/DevicePhone.svelte';
  import DeviceIframe from '../../components/DeviceIframe.svelte';
  import { loadTemplateConfig } from '../../data/loader';

  const config = loadTemplateConfig('my-template');
  const phoneConfig = config.phone!;

  let phoneReady = $state(false);
</script>

<MediaCanvas width={config.width} height={config.height} ready={phoneReady}>
  {#snippet content()}
    <DevicePhone screenWidth={phoneConfig.screen_width} screenHeight={phoneConfig.screen_height}>
      {#snippet screen()}
        <DeviceIframe
          src={phoneConfig.iframe_src || '/?media=1&seed=42'}
          width={phoneConfig.screen_width ?? 220}
          height={phoneConfig.screen_height ?? 430}
          scale={phoneConfig.scale ?? 0.52}
          onready={() => { phoneReady = true; }}
        />
      {/snippet}
    </DevicePhone>
  {/snippet}
</MediaCanvas>
```

### 4. Add to capture script

Add your template to the `TEMPLATES` array in `scripts/capture.spec.ts`:

```typescript
{ id: 'my-template', width: 1200, height: 630 },
```

---

## Media Test Account

For screenshots showing a logged-in user (sidebar with real chats), a dedicated
media test account is used. Playwright logs in before capturing, and iframes
inherit the session cookie.

### Setup

```bash
# Create account (slot 20):
docker exec api python /app/scripts/ci/create_test_accounts.py --start 20 --end 20

# Seed with realistic chats:
docker exec api python /app/scripts/ci/seed_media_chats.py

# Set env vars:
export OPENMATES_MEDIA_ACCOUNT_EMAIL=testacct20@test.openmates.org
export OPENMATES_MEDIA_ACCOUNT_PASSWORD=TestAcct!2026pw20
export OPENMATES_MEDIA_ACCOUNT_OTP_KEY=<base32-secret>
```

---

## Screenshot Ready Signal Flow

1. Playwright navigates to `/dev/media/templates/og-github`
2. Template creates `DeviceIframe` components with `/?media=1...` URLs
3. Each iframe loads the real app in media mode
4. App initializes, loads translations, processes deep links, renders content
5. App waits for `document.fonts.ready`, then adds `.media-app-ready` to body
6. `DeviceIframe` detects via `MutationObserver`, calls `onready()`
7. When ALL iframes report ready, template sets `ready=true` on `MediaCanvas`
8. `MediaCanvas` adds `.media-ready` CSS class
9. Playwright detects `.media-ready`, captures screenshot

**Timeout:** 30 seconds (configurable in `capture.spec.ts`).

---

## Canonical Format Dimensions

| Format | Width | Height | Use Case |
|--------|-------|--------|----------|
| `og` | 1200 | 630 | Open Graph (GitHub, Twitter, LinkedIn, Facebook) |
| `instagram-square` | 1080 | 1080 | Instagram post |
| `instagram-story` | 1080 | 1920 | Instagram/TikTok story |
| `twitter-header` | 1500 | 500 | Twitter/X profile header |
| `github-social` | 1280 | 640 | GitHub social preview |
| `linkedin-post` | 1200 | 627 | LinkedIn post image |
| `facebook-cover` | 820 | 312 | Facebook page cover |

---

## Troubleshooting

### Iframe shows login screen instead of app content

**Cause:** No authenticated session. The media test account isn't logged in.

**Fix:** Run the Playwright capture script which logs in via `beforeAll`, or
log in manually in the same browser before visiting the template.

### Playwright capture times out

**Cause:** `.media-ready` sentinel never set — one or more iframes didn't report ready.

**Fix:** Check browser console for errors in the iframe. Ensure the `?media=1`
URL is valid. Try increasing `WAIT_TIMEOUT` in `capture.spec.ts`.

### Suggestion cards show different content each capture

**Cause:** Missing or different `seed` parameter.

**Fix:** Ensure all iframe URLs include `&seed=N` with the same value for
consistent output across captures.

### Sidebar won't open in iframe

**Cause:** Missing `&sidebar=open` parameter, or viewport too small.

**Fix:** Add `&sidebar=open` to the iframe URL. The media mode sidebar
override ignores viewport width.

---

## Design Principles

1. **Pixel-accurate** — Device frames show the actual app, not replicas
2. **Deterministic** — Same URL params = same visual output (seeded PRNG)
3. **Zero maintenance** — UI changes automatically reflected in screenshots
4. **YAML-driven config** — Template dimensions, brand text, iframe URLs in version-controlled YAML
5. **Component reuse** — DevicePhone, DeviceLaptop, BrandHeader shared across templates
6. **Easy extension** — New template = directory with config.yml + page.svelte
