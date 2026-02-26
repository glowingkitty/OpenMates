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
  - skillIconName set AND showSkillIcon true → skill icon (CSS mask-image SVG)
  - Otherwise → app icon (icon_rounded CSS class)
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
  }: Props = $props();

  /** Use skill icon when skillIconName is set and showSkillIcon is true. */
  let useSkillIcon = $derived(showSkillIcon && !!skillIconName);

  function hideFavicon(e: Event) {
    (e.target as HTMLImageElement).style.display = 'none';
  }
</script>

<div
  class="embed-header"
  class:has-cta={hasCta}
  style="background: var(--color-app-{appId});"
>
  <!-- Large decorative icons at left/right edges (126×126px, 0.4 opacity) -->
  <div class="deco-icon deco-icon-left">
    {#if useSkillIcon}
      <div class="deco-skill-icon" data-skill-icon={skillIconName}></div>
    {:else}
      <div class="deco-app-icon icon_rounded {appId}"></div>
    {/if}
  </div>
  <div class="deco-icon deco-icon-right">
    {#if useSkillIcon}
      <div class="deco-skill-icon" data-skill-icon={skillIconName}></div>
    {:else}
      <div class="deco-app-icon icon_rounded {appId}"></div>
    {/if}
  </div>

  <!-- Center content: small icon + title + subtitle -->
  <div class="header-center">
    <div class="header-icon">
      {#if useSkillIcon}
        <div class="header-skill-icon" data-skill-icon={skillIconName}></div>
      {:else}
        <div class="header-app-icon icon_rounded {appId}"></div>
      {/if}
    </div>

    {#if title}
      <div class="header-title">
        {#if faviconUrl}
          <img
            src={faviconUrl}
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

  <!-- Optional CTA row at the bottom of the banner -->
  {#if embedHeaderCta}
    <div class="header-cta-area">
      {@render embedHeaderCta()}
    </div>
  {/if}

  <!-- Navigation arrows (prev/next embed) -->
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

<style>
  /* ==========================================================
     Banner container
     Matches ChatHeader.svelte dimensions exactly.
     Part of the normal scroll flow — scrolls with content.
     ========================================================== */

  .embed-header {
    position: relative;
    width: 100%;
    height: 240px;
    /* Bottom corners rounded; top corners flush with the overlay border-radius */
    border-radius: 0 0 14px 14px;
    overflow: hidden;
    display: flex;
    align-items: center;
    justify-content: center;
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.25);
    /* Decorative elements are non-interactive; arrows re-enable with pointer-events:auto */
    pointer-events: none;
    user-select: none;
  }

  /* Taller banner when a CTA button row is present */
  .embed-header.has-cta {
    height: 300px;
  }

  /* ==========================================================
     Decorative large icons (126×126px) at banner edges
     Same animation as ChatHeader: fade up from +50px below.
     ========================================================== */

  .deco-icon {
    position: absolute;
    width: 126px;
    height: 126px;
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 1;
    pointer-events: none;
    animation: decoIconEnter 0.6s ease-out 0.1s both;
  }

  .deco-icon-left {
    left: calc(50% - 240px - 106px);
    bottom: -15px;
    transform: rotate(-15deg);
    --deco-rotate: -15deg;
  }

  .deco-icon-right {
    right: calc(50% - 240px - 106px);
    bottom: -15px;
    transform: rotate(15deg);
    --deco-rotate: 15deg;
  }

  @keyframes decoIconEnter {
    from {
      opacity: 0;
      transform: translateY(50px) rotate(var(--deco-rotate, 0deg));
    }
    to {
      opacity: 0.4;
      transform: translateY(0) rotate(var(--deco-rotate, 0deg));
    }
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
    gap: 4px;
    z-index: 2;
    padding: 16px 24px;
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
    gap: 8px;
    max-width: 100%;
    margin-top: 2px;
  }

  .header-favicon {
    width: 20px;
    height: 20px;
    border-radius: 4px;
    flex-shrink: 0;
    object-fit: cover;
  }

  .header-favicon.circular {
    width: 26px;
    height: 26px;
    border-radius: 50%;
  }

  .header-title-text {
    font-size: 20px;
    font-weight: 700;
    color: #ffffff;
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
    font-size: 14px;
    font-weight: 500;
    color: rgba(255, 255, 255, 0.85);
    text-align: center;
    margin-top: 2px;
    animation: fadeIn 0.4s ease-out 0.15s both;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }

  /* CTA area — absolute, bottom-center of the banner */
  .header-cta-area {
    position: absolute;
    bottom: 16px;
    left: 0;
    right: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    padding: 0 20px;
    z-index: 10;
    pointer-events: auto;
    animation: fadeIn 0.4s ease-out 0.2s both;
  }

  /* ==========================================================
     Navigation arrows (prev/next embed)
     Identical to ChatHeader nav-arrow style.
     ========================================================== */

  .nav-arrow {
    position: absolute;
    top: 0;
    bottom: 0;
    padding: 0 !important;
    min-width: unset !important;
    width: 40px !important;
    height: 100% !important;
    border-radius: 0 !important;
    background-color: transparent !important;
    filter: none !important;
    margin: 0 !important;
    border: none;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    transition: background-color 0.15s ease;
    z-index: 20;
    pointer-events: auto;
    flex-shrink: 0;
  }

  .nav-arrow:hover {
    background-color: rgba(255, 255, 255, 0.1) !important;
    scale: none !important;
  }

  .nav-arrow:active {
    background-color: rgba(255, 255, 255, 0.18) !important;
    scale: none !important;
    filter: none !important;
  }

  .nav-arrow-left {
    left: 0;
    border-radius: 0 10px 10px 0 !important;
  }

  .nav-arrow-right {
    right: 0;
    border-radius: 10px 0 0 10px !important;
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
    margin-left: 4px;
  }

  .nav-chevron-right {
    transform: rotate(45deg);
    margin-right: 4px;
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

  /* ==========================================================
     Mobile adjustments (≤730px) — matches ChatHeader.svelte
     ========================================================== */

  @media (max-width: 730px) {
    .embed-header {
      height: 190px;
    }

    .embed-header.has-cta {
      height: 250px;
    }

    .header-center {
      padding: 12px 20px;
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
      font-size: 17px;
    }

    .header-subtitle {
      font-size: 13px;
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
</style>
