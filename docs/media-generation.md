# Media Generation System

Deterministic, YAML-driven system for generating OG images, social media graphics,
Instagram carousels/stories, and (future) video/animation captures.

**Location:** `frontend/apps/web_app/src/routes/dev/media/`
**Access:** Dev environments only (`/dev/` routes are gated by hostname check)
**Technology:** SvelteKit routes + Playwright screenshots

---

## Quick Start

### 1. Browse templates

Open the gallery in your browser:
```
https://app.dev.openmates.org/dev/media
```

### 2. Capture a single template

```bash
# From the web_app directory:
cd frontend/apps/web_app

# Capture all templates at once:
npx playwright test src/routes/dev/media/scripts/capture.spec.ts

# Capture a specific template:
npx playwright test --grep "og-github" src/routes/dev/media/scripts/capture.spec.ts

# Output to a custom directory:
OUTPUT_DIR=./marketing npx playwright test src/routes/dev/media/scripts/capture.spec.ts

# Use a different chat scenario:
SCENARIO=code-review-chat npx playwright test --grep "og-github" src/routes/dev/media/scripts/capture.spec.ts

# Record video (for animated templates):
RECORD_VIDEO=1 npx playwright test --grep "instagram-story" src/routes/dev/media/scripts/capture.spec.ts
```

Output goes to `media-output/` by default.

### 3. Use a custom base URL

```bash
MEDIA_BASE_URL=http://localhost:5173 npx playwright test src/routes/dev/media/scripts/capture.spec.ts
```

---

## Architecture

```
src/routes/dev/media/
├── +layout.ts              # ssr=false, prerender=false
├── +page.svelte            # Gallery index — lists all templates with previews
│
├── components/             # Reusable media components
│   ├── MediaCanvas.svelte          # Wrapper: exact pixel dimensions + .media-ready sentinel
│   ├── ThemeScope.svelte           # Forces dark/light CSS variables in a scoped container
│   ├── DevicePhone.svelte          # Phone frame with screen content slot
│   ├── DeviceLaptop.svelte         # Laptop frame with browser chrome + screen slot
│   ├── MockChatFeed.svelte         # Renders ChatMessageStatic list at a given scale
│   ├── ChatMessageStatic.svelte    # Lightweight message renderer (zero store deps)
│   └── BrandHeader.svelte          # Logo + headline + feature bullet points
│
├── data/                   # Data loading and types
│   ├── types.ts                    # TypeScript interfaces for scenarios, configs
│   └── loader.ts                   # YAML loader (Vite glob import)
│
├── scenarios/              # YAML chat scenarios (the "content")
│   ├── cuttlefish-chat.yml
│   ├── code-review-chat.yml
│   └── cooking-chat.yml
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

## YAML Scenario Files

Scenarios define the chat content shown in device mockups. They are loaded at
runtime from `scenarios/*.yml` using Vite's `import.meta.glob`.

### Format

```yaml
# scenarios/my-scenario.yml
name: My Scenario
description: A description of what this shows

messages:
  - role: user
    content: "User's question here"

  - role: assistant
    category: general_knowledge    # Determines the mate profile image
    mate_name: George              # Optional: override display name
    content: |
      Assistant response with **markdown** support.

      - Bullet points work
      - **Bold** and *italic* too
      - `code` and ```code blocks```

embeds:                            # Optional: for future embed card support
  - type: web
    title: "Example"
    url: "https://example.com"
```

### Available categories (mate profile images)

Each `category` maps to a mate profile avatar image:

| Category | Mate Name |
|----------|-----------|
| `general_knowledge` | George |
| `software_development` | Dev |
| `cooking_food` | Chef |
| `science` | Sci |
| `design` | Design |
| `finance` | Fin |
| `legal_law` | Legal |
| `medical_health` | Med |
| `life_coach_psychology` | Coach |
| `history` | History |
| `marketing_sales` | Marketing |
| `business_development` | Biz |
| `movies_tv` | Movies |
| `maker_prototyping` | Maker |
| `activism` | Activist |
| `electrical_engineering` | EE |
| `onboarding_support` | Support |

### Overriding scenarios at capture time

Use query parameters or environment variables:

```bash
# Via query parameter (in browser):
/dev/media/templates/og-github?scenario=code-review-chat

# Via environment variable (Playwright):
SCENARIO=code-review-chat npx playwright test --grep "og-github" ...

# Different scenarios for phone and laptop (og-social template):
/dev/media/templates/og-social?phone-scenario=cooking-chat&laptop-scenario=code-review-chat
```

---

## Template Config YAML

Each template has a `config.yml` that defines its dimensions, layout, and which
scenarios to use:

```yaml
# templates/og-github/config.yml
template: og-github
format: og                    # Matches FORMAT_DIMENSIONS in types.ts
width: 1200
height: 630

brand:
  headline: "Digital team mates"
  subtitle: "For everyone."
  features:
    - "AI for everyday tasks & learning"
    - "Privacy focus"

phone:
  scenario: cuttlefish-chat   # References scenarios/cuttlefish-chat.yml
  screen_width: 220
  screen_height: 430
  scale: 0.52                 # CSS transform scale for chat messages

laptop:
  scenario: cuttlefish-chat
  screen_width: 560
  screen_height: 340
  scale: 0.58
```

### Instagram Carousel Config

Carousels define multiple slides, each with its own type and content:

```yaml
slides:
  - type: hero               # Logo + headline + device mockup
    headline: "Meet your digital team mates"
    subtitle: "AI for everyone."
    scenario: cuttlefish-chat
    device: phone

  - type: chat               # Full-screen device showing chat
    headline: "Ask anything"
    scenario: cuttlefish-chat
    device: phone

  - type: feature             # Feature bullet points (no device)
    headline: "Built different"
    features:
      - "No subscription"
      - "Privacy focus"

  - type: cta                 # Call-to-action with logo and button
    headline: "Try it free"
    subtitle: "openmates.org"
    cta_text: "Get Started"
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
format: og                    # Use a predefined format or custom width/height
width: 1200
height: 630
# ... template-specific config
```

### 3. Add +page.svelte

```svelte
<script lang="ts">
  import { onMount } from 'svelte';
  import { browser } from '$app/environment';
  import MediaCanvas from '../../components/MediaCanvas.svelte';
  import { loadScenario, loadTemplateConfig } from '../../data/loader';
  import type { MediaMessage } from '../../data/types';

  const config = loadTemplateConfig('my-template');
  let messages = $state<MediaMessage[]>([]);
  let ready = $state(false);

  onMount(() => {
    if (!browser) return;
    messages = loadScenario('cuttlefish-chat').messages;
    ready = true;
  });
</script>

<MediaCanvas width={config.width} height={config.height} {ready}>
  {#snippet content()}
    <!-- Your template layout here -->
  {/snippet}
</MediaCanvas>
```

### 4. Add to capture script

Add your template to the `TEMPLATES` array in `scripts/capture.spec.ts`:

```typescript
{ id: 'my-template', width: 1200, height: 630 },
```

### 5. Create a new scenario (optional)

```yaml
# scenarios/my-scenario.yml
name: My Scenario
description: What this scenario shows
messages:
  - role: user
    content: "..."
  - role: assistant
    category: general_knowledge
    content: "..."
```

---

## Creating New Scenarios

Scenarios are pure data — no code changes needed. Just add a `.yml` file to
`scenarios/` and it's immediately available:

1. Create `scenarios/my-scenario.yml` following the format above
2. Reference it in a template config: `scenario: my-scenario`
3. Or override at capture time: `SCENARIO=my-scenario npx playwright test ...`

---

## Reusable Components

### MediaCanvas

Universal wrapper that provides:
- Exact pixel dimensions
- `.media-ready` CSS sentinel for Playwright
- Dark gradient background with decorative glows
- Center-aligned in viewport for browser preview

```svelte
<MediaCanvas width={1200} height={630} ready={isLoaded} borderRadius={16}>
  {#snippet content()}
    ...
  {/snippet}
</MediaCanvas>
```

### ThemeScope

Forces dark or light CSS variable values in a scoped container. Solves the
problem of child components inheriting the wrong theme from the page:

```svelte
<ThemeScope theme="dark">
  <!-- All var(--color-*) resolve to dark theme values here -->
  <ChatMessageStatic ... />
</ThemeScope>
```

### DevicePhone / DeviceLaptop

CSS-only device frames with content slots:

```svelte
<DevicePhone screenWidth={220} screenHeight={430}>
  {#snippet screen()}
    <MockChatFeed messages={data} scale={0.52} containerWidth={220} />
  {/snippet}
</DevicePhone>

<DeviceLaptop screenWidth={560} screenHeight={340} addressUrl="openmates.org">
  {#snippet screen()}
    <MockChatFeed messages={data} scale={0.58} containerWidth={560} />
  {/snippet}
</DeviceLaptop>
```

### ChatMessageStatic

Lightweight chat message bubble that renders markdown via `markdown-it`.
Zero store dependencies — safe to use outside the app context:

```svelte
<ChatMessageStatic
  role="assistant"
  content="Response with **markdown**"
  category="general_knowledge"
  containerWidth={400}
/>
```

### MockChatFeed

Renders a list of messages at a given CSS scale, wrapped in ThemeScope:

```svelte
<MockChatFeed messages={scenarioMessages} scale={0.52} containerWidth={220} theme="dark" />
```

---

## Video / Animation Capture

### CSS Animation Approach (Current)

For simple animated templates (typing effects, reveal transitions):

1. Use CSS animations or Svelte transitions in your template
2. Capture with Playwright video recording:

```bash
RECORD_VIDEO=1 npx playwright test --grep "instagram-story" src/routes/dev/media/scripts/capture.spec.ts
```

Playwright records a WebM video of the page during the test execution.

### Animated Template Pattern

```svelte
<script>
  let showMessage1 = $state(false);
  let showMessage2 = $state(false);

  onMount(() => {
    setTimeout(() => showMessage1 = true, 500);
    setTimeout(() => showMessage2 = true, 2000);
    // Signal animation complete for Playwright
    setTimeout(() => animationComplete = true, 4000);
  });
</script>

{#if showMessage1}
  <div class="animate-in">
    <ChatMessageStatic ... />
  </div>
{/if}

<style>
  .animate-in {
    animation: slideIn 0.4s ease-out;
  }
  @keyframes slideIn {
    from { opacity: 0; transform: translateY(20px); }
    to { opacity: 1; transform: translateY(0); }
  }
</style>
```

### Future: Remotion Integration

For complex multi-scene videos with cuts, music, and sophisticated transitions,
a Remotion-based setup would live as a separate tool (React-based, not SvelteKit).
The device frame components could be ported to React components for Remotion use.

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

### Chat messages show as blank/invisible in device mockups

**Cause:** Theme mismatch — the page is in light mode but device backgrounds
are dark. Chat message text renders as black on dark background.

**Fix:** Ensure `ThemeScope` wraps all chat content with `theme="dark"`,
or force `document.documentElement.setAttribute('data-theme', 'dark')` in `onMount`.

### Mate profile images not loading

**Cause:** The `@openmates/ui/static/images/mates/` path must be resolvable by Vite.

**Fix:** Ensure the `category` prop matches a valid category name (see table above).

### Playwright capture times out

**Cause:** The `.media-ready` sentinel is never set.

**Fix:** Check that `ready` is set to `true` in your template's `onMount`.
Ensure the template loads scenarios without errors.

### YAML scenario not found

**Cause:** The scenario ID doesn't match any file in `scenarios/`.

**Fix:** Check available scenarios: `listScenarios()` or browse `/dev/media`.

---

## Design Principles

1. **Deterministic output** — Same YAML input = same visual output, every time
2. **Zero app dependencies** — Templates never import stores, services, or DB modules
3. **YAML-driven content** — All text, messages, and config lives in version-controlled YAML
4. **Component reuse** — DevicePhone, DeviceLaptop, BrandHeader are shared across templates
5. **Easy extension** — Add a new template by creating a directory with config.yml + page.svelte
6. **Video-ready** — Templates can include CSS animations; Playwright records video natively
