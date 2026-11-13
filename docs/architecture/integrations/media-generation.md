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
claims:
- id: arch-integrations-media-generation-behavior
  type: unit
  claim: Media Generation is grounded in current source-of-truth files that parse or resolve successfully.
  source:
  - frontend/apps/web_app/src/routes/dev/media/+page.svelte
  - frontend/apps/web_app/src/routes/dev/media/components/MediaCanvas.svelte
  - frontend/apps/web_app/src/routes/dev/media/components/DeviceIframe.svelte
  - frontend/apps/web_app/src/routes/dev/media/components/DevicePhone.svelte
  - frontend/apps/web_app/src/routes/dev/media/components/DeviceLaptop.svelte
  test:
    file: scripts/tests/test_architecture_behavioral_claims.py
    command: python3 -m pytest scripts/tests/test_architecture_behavioral_claims.py
    assertion: arch-integrations-media-generation-behavior
  verified: '2026-06-11'
- id: arch-integrations-media-generation-source-1
  type: static
  file: scripts/tests/test_architecture_static_claims.py
  assertion: arch-integrations-media-generation-source-1
  anchors:
  - type: file_exists
    path: frontend/apps/web_app/src/routes/dev/media/+page.svelte
- id: arch-integrations-media-generation-source-2
  type: static
  file: scripts/tests/test_architecture_static_claims.py
  assertion: arch-integrations-media-generation-source-2
  anchors:
  - type: file_exists
    path: frontend/apps/web_app/src/routes/dev/media/components/BrandHeader.svelte
- id: arch-integrations-media-generation-source-3
  type: static
  file: scripts/tests/test_architecture_static_claims.py
  assertion: arch-integrations-media-generation-source-3
  anchors:
  - type: file_exists
    path: frontend/apps/web_app/src/routes/dev/media/components/DeviceIframe.svelte
---

# Media Generation

> System for generating OG images, social graphics, and Instagram content using real app screenshots via device-framed iframes and Playwright capture.

## Design Source Of Truth

All generated media must follow the root [`DESIGN.md`](../../../DESIGN.md). This applies to screenshot templates, social graphics, product videos, and any future Remotion compositions.

Agents working on video or media generation must check `DESIGN.md` before creating visual output and must update it when introducing reusable video, Remotion, social, or print design rules.

## In-Chat Video Generation

`videos.generate` makes short videos from natural-language `instructions`, optionally with up to 12 pictures of the chat. A request is either a generative clip (Gemini Omni `gemini-omni-1.2-flash`, Google Gemini API, delivered inline with `store: false`) or a composed, code-rendered video; `mode` defaults to auto. Contract: `specifications/features/app-skills/videos-generate/specification.yml`.

### Changing a video (versions)

A request with `source_video` (the embed_ref of an earlier result) and `change` (`edit`, `extend_start`, `extend_end`) makes version N+1 of the same result embed instead of a new embed. Code: `backend/apps/videos/tasks/generate_change.py` (make), `change_delivery.py` (store, charge, publish), `change_edits.py` (structured trims). It uses the shared revision mechanism in `backend/shared/python_utils/media_revision.py`, the same one `images.generate` uses, and is gated by the env flag `IMAGE_EDIT_AS_EMBED_VERSION`. Without the flag, a chat and message id, or for external API requests, the change fails with `change_not_available` and nothing is charged.

Before any work the video must be a generated video of this chat (otherwise `invalid_input`) and have a kept record (otherwise `change_unavailable`). A change that is lost to a concurrent version bump fails with `version_changed` before upload or charge. A failed change publishes nothing, so the video keeps its current version.

### Kept store

Each version stores a kept record at `{user}/videos_kept/{embed}/v{N}.json` in the chat-files bucket, encrypted with the user's Vault key (`video_kept.py`). It holds the version, `made_by`, aspect ratio, resolution, size, the stored final video, and either the composition source plus its input pictures (composed videos) or the ordered list of generated clips with per-clip trims and labels (clip videos). Newly generated clips are stored beside the version (`clip-new`). The record's file keys are added to the embed's key union across all versions.

### Change kinds

- `extend_end`: only for videos made of generated clips. The last frame of the current video is the first frame of one new Gemini Omni clip (3 to `EXTEND_MAX_SECONDS` s), which is joined after the existing clips.
- `extend_start`: the first frame is turned into an opening still with the image model (`gemini-nano-banana-2.1`); an Omni clip is then generated from that still to the video's first frame and joined before the existing clips. The joined video may last at most 60 s.
- `edit` of a clip video: if every line of the instructions is a structured trim or removal (the timeline's `Apply these edits to this video:` format: shorten a part at start or end, remove a part, trim the whole video), the new clip list is computed by code and rendered as a clip join, with no author-model call. Edits that would remove everything are rejected. Any other wording goes to the author model, with the clip join as its starting composition and the clips as `video_clip` inputs.
- `edit` of a composed video: the author model gets the kept composition and the kept original pictures and renders again.

Joins and composed renders run in the E2B sandbox. Safety is checked on the prompt (extends) and on the first, middle and last frame of the result before storing.

### Billing

A change is charged once under the event id `{embed_id}:v{N}:{change_id}` for what it used: added Omni clip seconds at the resolution price, the opening still, author-model tokens and sandbox render minutes. Credit headroom is checked before work starts. If the server refuses to seal the new version, the charge is refunded.

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
