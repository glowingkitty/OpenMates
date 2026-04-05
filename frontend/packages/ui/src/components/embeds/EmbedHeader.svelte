<!--
  frontend/packages/ui/src/components/embeds/EmbedHeader.svelte

  Gradient banner header for embed fullscreen views.
  Mirrors ChatHeader.svelte in design and dimensions:
    - Desktop: 240px height
    - Mobile (≤730px): 190px height
    - With CTA: 300px / 250px

  Structure:
  - Large decorative icons at left/right edges (126×126px, 0.4 opacity)
  - Center: small icon (38×38px, white) + title + subtitle
  - Optional CTA row at the bottom (embedHeaderCta snippet)
  - Navigation arrows at left/right edges for prev/next embed browsing

  Icon logic:
  - skillIconName set → skill icon (CSS mask-image SVG, flat white, no circle/gradient)
  - Otherwise → app icon (icon_rounded CSS class with colored circle background)
  - showSkillIcon prop is no longer consulted for the center icon (only BasicInfosBar uses it)
-->

<script lang="ts">
  interface Props {
    /** App identifier — used for the gradient background variable and icon class. */
    appId: string;
    /** Skill icon name (e.g. 'search', 'coding'). Uses app icon when empty. */
    skillIconName?: string;
    /** Show the skill icon instead of the app icon. Default true. */
    showSkillIcon?: boolean;

    /** Main title (bold white, centered). */
    title?: string;
    /** Subtitle (smaller, 0.85 opacity). */
    subtitle?: string;
    /** Optional favicon/logo URL shown next to the title text. */
    faviconUrl?: string;
    /** Whether the favicon should be circular (channel thumbnails, profile pics). */
    faviconIsCircular?: boolean;

    /** Whether a CTA snippet is provided (controls extra banner height). */
    hasCta?: boolean;
    /** Optional snippet rendered at the bottom of the banner (CTA buttons, badges). */
    embedHeaderCta?: import('svelte').Snippet;

    /** Whether there is a previous embed to navigate to. */
    hasPreviousEmbed?: boolean;
    /** Whether there is a next embed to navigate to. */
    hasNextEmbed?: boolean;
    onNavigatePrevious?: () => void;
    onNavigateNext?: () => void;
    /** Optional handler: clicking the center icon deep-links to settings. */
    onHeaderIconClick?: () => void;
  }

  let {
    appId,
    skillIconName = '',
    showSkillIcon = true,
    title = '',
    subtitle = '',
    faviconUrl,
    faviconIsCircular = false,
    hasCta = false,
    embedHeaderCta,
    hasPreviousEmbed = false,
    hasNextEmbed = false,
    onNavigatePrevious,
    onNavigateNext,
    onHeaderIconClick,
  }: Props = $props();

  /**
   * Use skill icon in center header when skillIconName is provided.
   * Always prefer the skill icon (flat white mask, no circle/gradient) over the
   * icon_rounded app icon. showSkillIcon is no longer considered here because it
   * was designed for BasicInfosBar (preview cards), not the fullscreen header.
   * Without this, embeds that set showSkillIcon={false} (e.g. SheetEmbedFullscreen)
   * would fall back to the icon_rounded class, which renders a circle with a colored
   * gradient background — not the intended flat icon.
   */
  // Always use the skill icon when skillIconName is available, regardless of showSkillIcon.
  // showSkillIcon is accepted as a prop for API compatibility but intentionally ignored
  // in EmbedHeader — it was designed for BasicInfosBar (preview cards), not the fullscreen
  // gradient header. We reference it inside $derived to satisfy Svelte's reactive tracking.
  let useSkillIcon = $derived((void showSkillIcon, !!skillIconName));

  /**
   * Use skill icon for decorative side icons when skillIconName is provided.
   * Decorative icons always use the plain skill icon (no gradient) when available,
   * regardless of showSkillIcon (which is now only used by BasicInfosBar).
   * This prevents the full app icon (with gradient background) from appearing in the banner.
   */
  let useDecoSkillIcon = $derived(!!skillIconName);

  import { handleImageError } from '../../utils/offlineImageHandler';
  import { proxyImage, MAX_WIDTH_FAVICON } from '../../utils/imageProxy';

  // SECURITY: Defense-in-depth — ensure favicon URLs are always proxied even if
  // the caller forgot. Prevents user IP leaks to external favicon hosts.
  let safeFaviconUrl = $derived(
    faviconUrl ? proxyImage(faviconUrl, MAX_WIDTH_FAVICON) : undefined
  );

  function hideFavicon(e: Event) {
    handleImageError(e.target as HTMLImageElement);
  }
</script>

<!--
  .embed-header: outer wrapper — fixed height, overflow: visible so the CTA
  can poke out below. position: relative so the CTA can be absolute-positioned.

  .header-inner: inner wrapper — carries the gradient background and clips
  decorative elements with overflow: hidden. Fills 100% of .embed-header.

  .header-cta-area: absolutely positioned on .embed-header, centered on the
  bottom edge via bottom: 0 + transform: translateY(50%). Lives outside
  .header-inner so it is not clipped.
-->
<div
  class="embed-header"
  class:has-cta={hasCta}
>
  <!-- Inner banner: gradient + orbs + decorative icons + center content + nav arrows.
       overflow: hidden clips the large decorative icons and orb blobs at the edges. -->
  <div
    class="header-inner"
    style="background: var(--color-app-{appId}); --orb-color-a: var(--color-app-{appId}-start); --orb-color-b: var(--color-app-{appId}-end);"
  >
    <!-- Living gradient orbs — three morphing radial-gradient blobs that drift
         and change shape slowly, creating a living color effect where orb-color-b
         blooms from the center against the orb-color-a background. -->
    <div class="embed-header-orbs" aria-hidden="true">
      <div class="orb orb-1"></div>
      <div class="orb orb-2"></div>
      <div class="orb orb-3"></div>
    </div>

    <!-- Large decorative icons at left/right edges (126×126px, 0.4 opacity) -->
    <!-- Always use skill icon when skillIconName is provided — avoids the full gradient
         app icon appearing in the banner. showSkillIcon only governs the center icon. -->
    <div class="deco-icon deco-icon-left">
      {#if useDecoSkillIcon}
        <div class="deco-skill-icon" data-skill-icon={skillIconName}></div>
      {:else}
        <div class="deco-app-icon icon_rounded {appId}"></div>
      {/if}
    </div>
    <div class="deco-icon deco-icon-right">
      {#if useDecoSkillIcon}
        <div class="deco-skill-icon" data-skill-icon={skillIconName}></div>
      {:else}
        <div class="deco-app-icon icon_rounded {appId}"></div>
      {/if}
    </div>

    <!-- Center content: small icon + title + subtitle -->
    <div class="header-center">
      {#if onHeaderIconClick}
        <button
          type="button"
          class="header-icon header-icon-button"
          onclick={onHeaderIconClick}
          aria-label="Open skill settings"
        >
          {#if useSkillIcon}
            <div class="header-skill-icon" data-skill-icon={skillIconName}></div>
          {:else}
            <div class="header-app-icon icon_rounded {appId}"></div>
          {/if}
        </button>
      {:else}
        <div class="header-icon">
          {#if useSkillIcon}
            <div class="header-skill-icon" data-skill-icon={skillIconName}></div>
          {:else}
            <div class="header-app-icon icon_rounded {appId}"></div>
          {/if}
        </div>
      {/if}

      {#if title}
        <div class="header-title">
          {#if safeFaviconUrl}
            <img
              src={safeFaviconUrl}
              alt=""
              class="header-favicon"
              class:circular={faviconIsCircular}
              crossorigin="anonymous"
              onerror={hideFavicon}
            />
          {/if}
          <span class="header-title-text">{title}</span>
        </div>
      {/if}

      {#if subtitle}
        <div class="header-subtitle">{subtitle}</div>
      {/if}
    </div>

    <!-- Navigation arrows (prev/next embed) — inside inner so they clip correctly -->
    {#if hasPreviousEmbed && onNavigatePrevious}
      <button
        class="nav-arrow nav-arrow-left"
        onclick={onNavigatePrevious}
        aria-label="Previous embed"
        type="button"
      >
        <span class="nav-chevron nav-chevron-left"></span>
      </button>
    {/if}
    {#if hasNextEmbed && onNavigateNext}
      <button
        class="nav-arrow nav-arrow-right"
        onclick={onNavigateNext}
        aria-label="Next embed"
        type="button"
      >
        <span class="nav-chevron nav-chevron-right"></span>
      </button>
    {/if}
  </div>

  <!-- CTA row — lives outside header-inner so it is NOT clipped by overflow:hidden.
       Centered on the bottom edge of the banner: translateY(50%) shifts it downward
       so its vertical midpoint aligns with the header's bottom edge, making it
       peek ~(height/2) px below. The content area adds padding-top to avoid overlap. -->
  {#if embedHeaderCta}
    <div class="header-cta-area">
      {@render embedHeaderCta()}
    </div>
  {/if}
</div>

<style>
  /* ==========================================================
     Banner container
     Matches ChatHeader.svelte dimensions exactly.
     Part of the normal scroll flow — scrolls with content.
     ========================================================== */

  /* Outer wrapper: fixed height, overflow: visible so the CTA area can
     poke out below the banner without being clipped.
     flex-shrink: 0 prevents collapse inside the flex content-area. */
  .embed-header {
    position: relative;
    width: 100%;
    height: 240px;
    /* flex-shrink: 0 prevents this banner from collapsing when it is a flex
       item inside .content-area (a flex column with overflow-y: auto).
       Without it the browser may compute height: 0px. Matches ChatHeader. */
    flex-shrink: 0;
    /* overflow: visible so the CTA area can extend beyond the bottom edge */
    overflow: visible;
    pointer-events: none;
    user-select: none;
  }

  /* Inner banner: carries gradient + clips decorative overflow icons.
     Fills 100% of the outer wrapper. */
  .header-inner {
    position: absolute;
    inset: 0;
    /* Bottom corners rounded; top corners flush with overlay border-radius */
    border-radius: 0 0 14px 14px;
    overflow: hidden;
    display: flex;
    align-items: center;
    justify-content: center;
    box-shadow: var(--shadow-xl);
    pointer-events: none;
  }

  /* Height is always fixed — the CTA overflows the bottom, never grows the banner. */

  /* ==========================================================
     Living gradient orbs — three morphing blobs
     Shared keyframes (orbMorph1/2/3, orbDrift1/2/3) live in animations.css.
     ========================================================== */

  .embed-header-orbs {
    position: absolute;
    inset: 0;
    z-index: var(--z-index-base);
    pointer-events: none;
    overflow: hidden;
  }

  .orb {
    position: absolute;
    width: 220px;
    height: 220px;
    opacity: 0.55;
    filter: blur(28px);
    /* Promote each orb to its own compositor layer so the drift + morph
       animations run off the main thread. On iOS/iPadOS, animating
       border-radius on a blurred element forces per-frame rasterization
       unless the element is already composited. Promoting here ensures
       the three orbs don't compete with the fullscreen slide-in for GPU
       budget. */
    will-change: transform;
  }

  /* Orb 1 — color-b (end), top-left anchor */
  .orb-1 {
    top: -60px;
    left: -40px;
    background: radial-gradient(
      ellipse at center,
      var(--orb-color-b, #fff) 0%,
      var(--orb-color-b, #fff) 40%,
      transparent 85%
    );
    animation:
      orbMorph1 11s ease-in-out infinite,
      orbDrift1 19s ease-in-out infinite;
  }

  /* Orb 2 — color-a (start), bottom-right anchor */
  .orb-2 {
    bottom: -60px;
    right: -40px;
    background: radial-gradient(
      ellipse at center,
      var(--orb-color-a, #fff) 0%,
      var(--orb-color-a, #fff) 40%,
      transparent 85%
    );
    animation:
      orbMorph2 13s ease-in-out infinite,
      orbDrift2 23s ease-in-out infinite;
  }

  /* Orb 3 — color-b (end), center anchor for depth */
  .orb-3 {
    top: 20px;
    right: 20%;
    background: radial-gradient(
      ellipse at center,
      var(--orb-color-b, #fff) 0%,
      var(--orb-color-b, #fff) 40%,
      transparent 85%
    );
    animation:
      orbMorph3 17s ease-in-out infinite,
      orbDrift3 29s ease-in-out infinite;
  }

  /* ==========================================================
     Decorative large icons (126×126px) at banner edges
     Two-phase animation: decoEnter (one-shot entrance) → decoFloat (orbital).
     Shared keyframes (decoEnter, decoFloat) live in animations.css.
     ========================================================== */

  .deco-icon {
    position: absolute;
    width: 126px;
    height: 126px;
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: var(--z-index-raised);
    pointer-events: none;
    --float-rx: 10px;
    --float-ry: 12px;
    animation:
      decoEnter 0.6s ease-out 0.1s both,
      decoFloat 16s linear 0.7s infinite;
  }

  .deco-icon-left {
    left: calc(50% - 240px - 106px);
    bottom: -15px;
    --deco-rotate: -15deg;
    /* Left icon starts at 0° of its orbit (0.7s = entrance duration) */
    animation-delay: 0.1s, 0.7s;
  }

  .deco-icon-right {
    right: calc(50% - 240px - 106px);
    bottom: -15px;
    --deco-rotate: 15deg;
    /* Negative delay: start as if 8s have already elapsed (half-cycle offset).
       Positive delay would freeze the icon for 8.7s then snap — use negative
       to begin mid-orbit immediately with no wait or jump. */
    animation-delay: 0.1s, -8s;
  }

  /* Decorative skill icon: CSS mask-image, white fill */
  .deco-skill-icon {
    width: 126px;
    height: 126px;
    background-color: white;
    -webkit-mask-position: center;
    mask-position: center;
    -webkit-mask-repeat: no-repeat;
    mask-repeat: no-repeat;
    -webkit-mask-size: contain;
    mask-size: contain;
  }

  /* Decorative app icon: uses icon_rounded system */
  .deco-app-icon {
    width: 80px;
    height: 80px;
    position: relative;
    bottom: auto;
    left: auto;
    z-index: auto;
  }

  /* Force app icon to render white inside the gradient banner */
  .deco-app-icon::after {
    filter: brightness(0) invert(1) !important;
    background-size: 60px 60px !important;
  }

  /* ==========================================================
     Center content
     ========================================================== */

  .header-center {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: var(--spacing-2);
    z-index: var(--z-index-raised-2);
    padding: var(--spacing-8) var(--spacing-12);
    max-width: 480px;
    width: 100%;
    animation: fadeIn 0.35s ease-out;
  }

  @keyframes fadeIn {
    from { opacity: 0; }
    to   { opacity: 1; }
  }

  /* Small icon (38×38px) */
  .header-icon {
    width: 38px;
    height: 38px;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
  }

  .header-icon-button {
    pointer-events: auto;
    cursor: pointer;
    border: none;
    background: transparent;
    padding: 0;
    border-radius: var(--radius-4);
    transition: background-color var(--duration-fast) var(--easing-default);
  }

  .header-icon-button:hover {
    background-color: rgba(255, 255, 255, 0.15);
  }

  .header-icon-button:focus-visible {
    outline: 2px solid rgba(255, 255, 255, 0.9);
    outline-offset: 2px;
  }

  /* Small skill icon (38×38px white) */
  .header-skill-icon {
    width: 38px;
    height: 38px;
    background-color: white;
    -webkit-mask-position: center;
    mask-position: center;
    -webkit-mask-repeat: no-repeat;
    mask-repeat: no-repeat;
    -webkit-mask-size: contain;
    mask-size: contain;
  }

  /* Small app icon (white) */
  .header-app-icon {
    width: 30px;
    height: 30px;
    position: relative;
    bottom: auto;
    left: auto;
    z-index: auto;
  }

  .header-app-icon::after {
    filter: brightness(0) invert(1) !important;
    background-size: 20px 20px !important;
  }

  /* Title row: optional favicon + text */
  .header-title {
    display: flex;
    align-items: center;
    gap: var(--spacing-4);
    max-width: 100%;
    margin-top: var(--spacing-1);
  }

  .header-favicon {
    width: 20px;
    height: 20px;
    border-radius: var(--radius-1);
    flex-shrink: 0;
    object-fit: cover;
  }

  .header-favicon.circular {
    width: 26px;
    height: 26px;
    border-radius: 50%;
  }

  .header-title-text {
    font-size: var(--font-size-h3);
    font-weight: 700;
    color: var(--color-grey-0);
    text-align: center;
    line-height: 1.3;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }

  /* Subtitle */
  .header-subtitle {
    font-size: var(--font-size-small);
    font-weight: 500;
    color: rgba(255, 255, 255, 0.85);
    text-align: center;
    margin-top: var(--spacing-1);
    animation: fadeIn 0.4s ease-out 0.15s both;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }

  /* CTA area — absolutely positioned on the outer .embed-header (overflow: visible).
     bottom: 0 aligns its top edge with the header's bottom.
     transform: translateY(50%) shifts it down by half its own height, so its
     vertical center sits on the header's bottom edge, creating the "peeking out"
     effect. The content area needs matching padding-top so content starts below. */
  .header-cta-area {
    position: absolute;
    bottom: 0;
    left: 0;
    right: 0;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: center;
    gap: var(--spacing-4);
    padding: 0 20px;
    z-index: var(--z-index-dropdown-1);
    pointer-events: auto;
    animation: fadeIn 0.4s ease-out 0.2s both;
    /* Center the CTA on the header's bottom edge */
    transform: translateY(50%);
  }

  /* ==========================================================
     Navigation arrows (prev/next embed)
     Identical to ChatHeader nav-arrow style.
     ========================================================== */

  .nav-arrow {
    position: absolute;
    top: 50%;
    transform: translateY(-50%);
    padding: 0 !important;
    min-width: unset !important;
    width: 36px !important;
    height: 36px !important;
    border-radius: 50% !important;
    background-color: var(--color-grey-50) !important;
    opacity: 0.5;
    filter: none !important;
    margin: 0 !important;
    border: none;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    transition: opacity var(--duration-fast) var(--easing-default);
    z-index: var(--z-index-dropdown-2);
    pointer-events: auto;
    flex-shrink: 0;
  }

  .nav-arrow:hover {
    opacity: 0.75;
    scale: none !important;
  }

  .nav-arrow:active {
    opacity: 0.9;
    scale: none !important;
    filter: none !important;
  }

  .nav-arrow-left {
    left: 8px;
  }

  .nav-arrow-right {
    right: 8px;
  }

  /* CSS-triangle chevrons for nav arrows */
  .nav-chevron {
    display: block;
    width: 10px;
    height: 10px;
    border-top: 2.5px solid rgba(255, 255, 255, 0.85);
    border-right: 2.5px solid rgba(255, 255, 255, 0.85);
    flex-shrink: 0;
  }

  .nav-chevron-left {
    transform: rotate(-135deg);
    margin-left: var(--spacing-2);
  }

  .nav-chevron-right {
    transform: rotate(45deg);
    margin-right: var(--spacing-2);
  }

  /* ==========================================================
     Skill icon mask-images (same set as BasicInfosBar)
     Applied via data-skill-icon attribute.
     ========================================================== */

  :global([data-skill-icon="search"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/search.svg');
    mask-image: url('@openmates/ui/static/icons/search.svg');
  }
  :global([data-skill-icon="videos"]),
  :global([data-skill-icon="video"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/videos.svg');
    mask-image: url('@openmates/ui/static/icons/videos.svg');
  }
  :global([data-skill-icon="book"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/book.svg');
    mask-image: url('@openmates/ui/static/icons/book.svg');
  }
  :global([data-skill-icon="visible"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/visible.svg');
    mask-image: url('@openmates/ui/static/icons/visible.svg');
  }
  :global([data-skill-icon="reminder"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/reminder.svg');
    mask-image: url('@openmates/ui/static/icons/reminder.svg');
  }
  :global([data-skill-icon="image"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/image.svg');
    mask-image: url('@openmates/ui/static/icons/image.svg');
  }
  :global([data-skill-icon="ai"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/ai.svg');
    mask-image: url('@openmates/ui/static/icons/ai.svg');
  }
  :global([data-skill-icon="focus"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/insight.svg');
    mask-image: url('@openmates/ui/static/icons/insight.svg');
  }
  :global([data-skill-icon="pin"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/pin.svg');
    mask-image: url('@openmates/ui/static/icons/pin.svg');
  }
  :global([data-skill-icon="text"]),
  :global([data-skill-icon="transcript"]),
  :global([data-skill-icon="docs"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/docs.svg');
    mask-image: url('@openmates/ui/static/icons/docs.svg');
  }
  :global([data-skill-icon="website"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/web.svg');
    mask-image: url('@openmates/ui/static/icons/web.svg');
  }
  :global([data-skill-icon="coding"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/coding.svg');
    mask-image: url('@openmates/ui/static/icons/coding.svg');
  }
  :global([data-skill-icon="travel"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/travel.svg');
    mask-image: url('@openmates/ui/static/icons/travel.svg');
  }
  :global([data-skill-icon="table"]),
  :global([data-skill-icon="sheet"]),
  :global([data-skill-icon="sheets"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/sheets.svg');
    mask-image: url('@openmates/ui/static/icons/sheets.svg');
  }
  :global([data-skill-icon="event"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/event.svg');
    mask-image: url('@openmates/ui/static/icons/event.svg');
  }
  :global([data-skill-icon="health"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/heart.svg');
    mask-image: url('@openmates/ui/static/icons/heart.svg');
  }
  :global([data-skill-icon="math"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/math.svg');
    mask-image: url('@openmates/ui/static/icons/math.svg');
  }
  :global([data-skill-icon="mail"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/mail.svg');
    mask-image: url('@openmates/ui/static/icons/mail.svg');
  }
  :global([data-skill-icon="home"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/home.svg');
    mask-image: url('@openmates/ui/static/icons/home.svg');
  }
  :global([data-skill-icon="nutrition"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/nutrition.svg');
    mask-image: url('@openmates/ui/static/icons/nutrition.svg');
  }

  /* ==========================================================
     Mobile adjustments (≤730px) — matches ChatHeader.svelte
     ========================================================== */

  @media (max-width: 730px) {
    .embed-header {
      height: 190px;
      /* has-cta: height stays 190px — CTA overflows, never grows the banner */
    }

    .header-center {
      padding: var(--spacing-6) var(--spacing-10);
      max-width: 360px;
    }

    .header-icon {
      width: 32px;
      height: 32px;
    }

    .header-skill-icon {
      width: 32px;
      height: 32px;
    }

    .header-title-text {
      font-size: var(--font-size-lg);
    }

    .header-subtitle {
      font-size: var(--font-size-xs);
    }

    .deco-icon {
      width: 90px;
      height: 90px;
    }

    .deco-skill-icon {
      width: 90px;
      height: 90px;
    }

    .deco-icon-left {
      left: calc(50% - 180px - 70px);
    }

    .deco-icon-right {
      right: calc(50% - 180px - 70px);
    }
  }

  /* ==========================================================
     Accessibility: disable all animations for users who prefer
     reduced motion (vestibular disorders, focus preference).
     ========================================================== */

  @media (prefers-reduced-motion: reduce) {
    .orb {
      animation: none;
    }

    .deco-icon {
      animation: none;
      opacity: 0.4;
    }
  }
</style>
