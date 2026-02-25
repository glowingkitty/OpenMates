<!--
  ChatHeader.svelte

  Full-width gradient banner displayed at the top of the active chat history.
  Shown only for new chats where the server generates title/category/icon.
  Scrolls with the chat content (scrolls out of view as user scrolls down).

  Three visual states with smooth transitions:

  State A — Processing (isLoading=true, isCreditsError=false):
    - Background: var(--color-primary) gradient
    - Centered AI icon (38×38px, white) + "Creating new chat ..." text (20px, white)
    - Both icon and text have a left-to-right shimmer animation
    - No decorative side icons

  State A2 — Credits Error (isLoading=false, isCreditsError=true):
    - Background: var(--color-primary) gradient (same blue, no shimmer)
    - Static AI icon (38×38px, white, 0.5 opacity) + "Not enough credits" text (20px, white, static)
    - Replaces the shimmer with a calm, non-animated error state
    - Stays visible until user sends another message or switches chat

  State B — Loaded (isLoading=false, isCreditsError=false, title+category present):
    - Background: category gradient (from getCategoryGradientColors)
    - AI icon/text fade out, replaced by:
      - Category icon (38×38px, white) centered
      - Title (20px, white, bold) centered below icon
      - Summary (14px, white) — fades in with max-height animation when available
      - Creation time (14px, white, 0.7 opacity) — relative formatting
    - Large decorative icons (126×126px) at left and right edges:
      - 0.4 opacity, entrance animation: fade up from +50px Y offset
      - overflow: hidden clips them at the banner edges

  Dimensions match DailyInspirationBanner:
    - Desktop: 240px height, 14px border-radius
    - Mobile (≤730px): 190px height

  Props:
    title          - decrypted/plaintext chat title
    category       - category string (e.g. "technology", "science")
    icon           - icon name string (e.g. "cpu")
    summary        - decrypted chat summary (2-3 sentences)
    isLoading      - true while title/category/icon are not yet received (State A)
    isCreditsError - true when message was rejected due to insufficient credits (State A2)
    chatCreatedAt  - Unix timestamp in seconds of chat creation
-->
<script lang="ts">
  import { onDestroy } from 'svelte';
  import { getCategoryGradientColors, getValidIconName, getLucideIcon } from '../utils/categoryUtils';
  import { text } from '@repo/ui';
  import { chatNavigationStore, navigatePrev, navigateNext } from '../stores/chatNavigationStore';

  // ─── Props ─────────────────────────────────────────────────────────────────

  let {
    title = '',
    category = null,
    icon = null,
    summary = null,
    isLoading = false,
    isCreditsError = false,
    chatCreatedAt = null,
  }: {
    title?: string;
    category?: string | null;
    icon?: string | null;
    summary?: string | null;
    isLoading?: boolean;
    /** True when the first message on this new chat was rejected due to insufficient credits.
     *  Replaces the "Creating new chat..." shimmer with a static "Not enough credits" state. */
    isCreditsError?: boolean;
    chatCreatedAt?: number | null;
  } = $props();

  // ─── Relative-time ticker ──────────────────────────────────────────────────
  //
  // `now` is updated every minute while the chat is within the 10-minute
  // relative-time window ("X min ago"). Once the chat ages past 10 minutes the
  // interval is cleared so we don't keep a timer running for old chats.
  // The interval is also cleared on component destroy via onDestroy.

  let now = $state(Date.now());
  let _tickerInterval: ReturnType<typeof setInterval> | null = null;

  /**
   * Start the per-minute ticker if the chat is still within the relative window.
   * Called once on mount via $effect and whenever chatCreatedAt changes.
   */
  function startTickerIfNeeded() {
    if (_tickerInterval !== null) return; // already running
    if (!chatCreatedAt) return;

    const createdMs = chatCreatedAt * 1000;
    const diffMinutes = (Date.now() - createdMs) / 60000;

    // Only schedule if we're currently in the relative window (0–10 min)
    if (diffMinutes <= 10) {
      _tickerInterval = setInterval(() => {
        now = Date.now();

        // Stop the ticker once we exit the relative window
        if (!chatCreatedAt) return;
        const elapsed = (now - chatCreatedAt * 1000) / 60000;
        if (elapsed > 10 && _tickerInterval !== null) {
          clearInterval(_tickerInterval);
          _tickerInterval = null;
        }
      }, 60_000); // tick every minute
    }
  }

  // Start (or restart) ticker whenever chatCreatedAt changes
  $effect(() => {
    // Re-read chatCreatedAt so the effect re-runs when it changes
    // eslint-disable-next-line @typescript-eslint/no-unused-expressions
    chatCreatedAt;
    now = Date.now(); // immediately refresh the display
    if (_tickerInterval !== null) {
      clearInterval(_tickerInterval);
      _tickerInterval = null;
    }
    startTickerIfNeeded();
  });

  onDestroy(() => {
    if (_tickerInterval !== null) {
      clearInterval(_tickerInterval);
      _tickerInterval = null;
    }
  });

  // ─── Navigation arrows ─────────────────────────────────────────────────────

  /** Navigation state from Chats.svelte via the shared store. */
  let navState = $derived($chatNavigationStore);

  /** Lucide chevron icons for prev/next arrows. */
  const ChevronLeft = getLucideIcon('chevron-left');
  const ChevronRight = getLucideIcon('chevron-right');

  /**
   * Navigate to the previous chat in the list.
   * Calls the store's navigate method directly — works even when the sidebar
   * (Chats.svelte) is closed/unmounted because the store holds the chat list.
   */
  function handlePrevious(e: MouseEvent) {
    e.stopPropagation();
    navigatePrev();
  }

  /**
   * Navigate to the next chat in the list.
   * Calls the store's navigate method directly — works even when the sidebar
   * (Chats.svelte) is closed/unmounted because the store holds the chat list.
   */
  function handleNext(e: MouseEvent) {
    e.stopPropagation();
    navigateNext();
  }

  // ─── Derived state ─────────────────────────────────────────────────────────

  /** Gradient background style for the banner. Uses primary gradient while loading or
   *  showing a credits error; category gradient once fully loaded. */
  let bannerStyle = $derived.by(() => {
    if (isLoading || isCreditsError || !category) {
      // Processing state or credits error: use the primary gradient from theme.css
      return 'background: var(--color-primary)';
    }
    const colors = getCategoryGradientColors(category);
    if (!colors) return 'background: var(--color-primary)';
    return `background: linear-gradient(135deg, ${colors.start}, ${colors.end})`;
  });

  /** Lucide icon component for the category, resolved from icon name + fallback. */
  let IconComponent = $derived.by(() => {
    if (!category) return null;
    const iconName = getValidIconName(icon || '', category);
    return getLucideIcon(iconName);
  });

  /** Whether the loaded state should be shown (transition from processing → loaded). */
  let isLoaded = $derived(!isLoading && !!title && !!category);

  /** Whether to show the summary with its expand animation. */
  let showSummary = $derived(isLoaded && !!summary);

  // ─── Creation time formatting ──────────────────────────────────────────────

  /**
   * Format the chat creation time as a relative/absolute string.
   *
   * Rules (from spec):
   *   - < 1 minute ago     → "Just now"
   *   - 1–10 minutes ago   → "{count} min ago"
   *   - Today (>10 min)    → "Started today, HH:MM"
   *   - Yesterday           → "Started yesterday, HH:MM"
   *   - Older               → "Started YYYY/MM/DD, HH:MM"
   *
   * chatCreatedAt is a Unix timestamp in **seconds** (consistent with Chat.created_at).
   */
  let formattedTime = $derived.by(() => {
    if (!chatCreatedAt) return '';

    const createdMs = chatCreatedAt * 1000; // Convert seconds → milliseconds
    // `now` is a reactive $state that is updated every minute while the chat
    // is within the 10-minute relative window. Reading it here ensures
    // formattedTime re-derives automatically when the ticker fires.
    const diffMs = now - createdMs;
    const diffMinutes = Math.floor(diffMs / 60000);

    const createdDate = new Date(createdMs);
    const todayDate = new Date(now);

    // Format HH:MM with zero-padded hours and minutes
    const timeStr = `${String(createdDate.getHours()).padStart(2, '0')}:${String(createdDate.getMinutes()).padStart(2, '0')}`;

    // Less than 1 minute ago
    if (diffMinutes < 1) {
      return $text('chat.header.just_now');
    }

    // 1–10 minutes ago: relative
    if (diffMinutes <= 10) {
      return $text('chat.header.minutes_ago', { values: { count: diffMinutes } });
    }

    // Same calendar day: "Started today, HH:MM"
    if (
      createdDate.getFullYear() === todayDate.getFullYear() &&
      createdDate.getMonth() === todayDate.getMonth() &&
      createdDate.getDate() === todayDate.getDate()
    ) {
      return $text('chat.header.started_today', { values: { time: timeStr } });
    }

    // Yesterday: compare with calendar date minus 1 day
    const yesterdayDate = new Date(now);
    yesterdayDate.setDate(yesterdayDate.getDate() - 1);
    if (
      createdDate.getFullYear() === yesterdayDate.getFullYear() &&
      createdDate.getMonth() === yesterdayDate.getMonth() &&
      createdDate.getDate() === yesterdayDate.getDate()
    ) {
      return $text('chat.header.started_yesterday', { values: { time: timeStr } });
    }

    // Older: "Started YYYY/MM/DD, HH:MM"
    const dateStr = `${createdDate.getFullYear()}/${String(createdDate.getMonth() + 1).padStart(2, '0')}/${String(createdDate.getDate()).padStart(2, '0')}`;
    return $text('chat.header.started_date', { values: { date: dateStr, time: timeStr } });
  });

  /** Whether to show the creation time line. Only shown once we have a title+category. */
  let showTime = $derived(isLoaded && !!formattedTime);
</script>

<!-- Banner container: always rendered when either loading or loaded.
     Smooth background-color transition from primary → category gradient.
     position:relative is required for the absolutely-positioned arrow buttons. -->
<div
  class="chat-header-banner"
  class:is-loaded={isLoaded}
  style={bannerStyle}
>
  <!-- ── Processing state: AI icon + "Creating new chat ..." with shimmer ── -->
  {#if isLoading && !isCreditsError}
    <div class="processing-content">
      <div class="processing-ai-icon"></div>
      <span class="processing-text">{$text('chat.creating_new_chat')}</span>
    </div>
  {/if}

  <!-- ── Credits error state: static AI icon + "Not enough credits" text ──
       Shown when the first message on a new chat was rejected due to 0 credits.
       Same blue background as the loading state but no shimmer animation.
       Stays visible until the user sends another message or switches chat. -->
  {#if isCreditsError}
    <div class="processing-content credits-error-content">
      <div class="processing-ai-icon credits-error-icon"></div>
      <span class="credits-error-text">{$text('chat.header.not_enough_credits')}</span>
    </div>
  {/if}

  <!-- ── Loaded state: category icon + title + summary + time ── -->
  {#if isLoaded}
    <!-- Large decorative icons at left and right edges (126×126px, 0.4 opacity).
         Animate in from below: translateY(50px) → translateY(0), opacity 0 → 0.4. -->
    {#if IconComponent}
      <div class="deco-icon deco-icon-left">
        <IconComponent size={126} color="white" />
      </div>
      <div class="deco-icon deco-icon-right">
        <IconComponent size={126} color="white" />
      </div>
    {/if}

    <div class="loaded-content">
      <!-- Category icon (38×38px) -->
      {#if IconComponent}
        <div class="loaded-icon">
          <IconComponent size={38} color="white" />
        </div>
      {/if}

      <!-- Title (20px, white, bold) -->
      <!-- eslint-disable-next-line svelte/no-at-html-tags -->
      <span class="loaded-title">{@html title}</span>

      <!-- Summary: fades in with max-height expand when available -->
      {#if showSummary}
        <p class="loaded-summary">{summary}</p>
      {/if}

      <!-- Creation time -->
      {#if showTime}
        <span class="loaded-time">{formattedTime}</span>
      {/if}
    </div>
  {/if}

  <!-- ── Chat navigation arrows ──
       Shown at the left and right edges when there are adjacent chats to navigate to.
       Only rendered in the loaded state (not while the title is still generating).
       Use pointer-events:auto to override the banner's pointer-events:none. -->
  {#if isLoaded && navState.hasPrev}
    <button
      class="nav-arrow nav-arrow-left"
      onclick={handlePrevious}
      aria-label={$text('chat.header.previous_chat')}
      type="button"
    >
      <ChevronLeft size={22} color="rgba(255,255,255,0.85)" />
    </button>
  {/if}
  {#if isLoaded && navState.hasNext}
    <button
      class="nav-arrow nav-arrow-right"
      onclick={handleNext}
      aria-label={$text('chat.header.next_chat')}
      type="button"
    >
      <ChevronRight size={22} color="rgba(255,255,255,0.85)" />
    </button>
  {/if}
</div>

<style>
  /* ─── Banner container ──────────────────────────────────────────────────── */

  .chat-header-banner {
    position: relative;
    width: 100%;
    height: 240px;
    /* Top corners are flush with the top of the scroll area — no top radius.
       Only bottom corners are rounded to separate the banner from messages below. */
    border-radius: 0 0 14px 14px;
    overflow: hidden;
    display: flex;
    align-items: center;
    justify-content: center;
    /* Smooth background transition when switching from primary → category gradient */
    transition: background 0.5s ease;
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.25);
    /* Decorative content is non-interactive; arrows override with pointer-events:auto below. */
    pointer-events: none;
    user-select: none;
  }

  /* ─── Processing state ──────────────────────────────────────────────────── */

  .processing-content {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 12px;
    z-index: 2;
    animation: fadeIn 0.2s ease-out;
  }

  /* AI icon (38×38px, white) with left-to-right shimmer */
  .processing-ai-icon {
    width: 38px;
    height: 38px;
    flex-shrink: 0;
    -webkit-mask-image: url('@openmates/ui/static/icons/ai.svg');
    mask-image: url('@openmates/ui/static/icons/ai.svg');
    -webkit-mask-size: contain;
    mask-size: contain;
    -webkit-mask-repeat: no-repeat;
    mask-repeat: no-repeat;
    -webkit-mask-position: center;
    mask-position: center;
    /* White base with a brighter sweep for shimmer */
    background: linear-gradient(
      90deg,
      rgba(255, 255, 255, 1) 0%,
      rgba(255, 255, 255, 1) 35%,
      rgba(255, 255, 255, 0.5) 50%,
      rgba(255, 255, 255, 1) 65%,
      rgba(255, 255, 255, 1) 100%
    );
    background-size: 200% 100%;
    animation: headerShimmer 1.8s infinite linear;
  }

  /* "Creating new chat ..." text (20px, white) with shimmer */
  .processing-text {
    font-size: 20px;
    font-weight: 600;
    color: white;
    text-align: center;
    /* Shimmer on text via background-clip */
    background: linear-gradient(
      90deg,
      rgba(255, 255, 255, 1) 0%,
      rgba(255, 255, 255, 1) 35%,
      rgba(255, 255, 255, 0.5) 50%,
      rgba(255, 255, 255, 1) 65%,
      rgba(255, 255, 255, 1) 100%
    );
    background-size: 200% 100%;
    background-clip: text;
    -webkit-background-clip: text;
    color: transparent;
    animation: headerShimmer 1.8s infinite linear;
  }

  @keyframes headerShimmer {
    0%   { background-position: 200% 0; }
    100% { background-position: -200% 0; }
  }

  /* ─── Credits error state ────────────────────────────────────────────────
     Same layout as processing-content but with no shimmer animation.
     The icon and text are static and dimmed (0.6 opacity) to indicate
     an error state without being alarming. */

  .credits-error-content {
    animation: fadeIn 0.3s ease-out;
  }

  .credits-error-icon {
    /* Same mask as processing-ai-icon but static white at reduced opacity */
    background: rgba(255, 255, 255, 0.6) !important;
    background-size: 100% 100% !important;
    animation: none !important;
  }

  .credits-error-text {
    font-size: 20px;
    font-weight: 600;
    color: rgba(255, 255, 255, 0.75);
    text-align: center;
  }

  /* ─── Loaded state ──────────────────────────────────────────────────────── */

  .loaded-content {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 4px;
    z-index: 2;
    padding: 16px 24px;
    /* Narrow text block so it doesn't stretch the full banner width */
    max-width: 480px;
    width: 100%;
    animation: fadeIn 0.35s ease-out;
  }

  @keyframes fadeIn {
    from { opacity: 0; }
    to   { opacity: 1; }
  }

  /* Category icon (38×38px, centered) */
  .loaded-icon {
    width: 38px;
    height: 38px;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
  }

  /* Title: 20px, white, bold, centered, truncated to 2 lines */
  .loaded-title {
    display: block;
    font-size: 20px;
    font-weight: 700;
    color: #ffffff;
    text-align: center;
    line-height: 1.3;
    max-width: 100%;
    /* Clamp to 2 lines */
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }

  /* Summary: 14px, white, centered. Animates height from 0. */
  .loaded-summary {
    margin: 2px 0 0;
    font-size: 14px;
    font-weight: 500;
    color: #ffffff;
    line-height: 1.45;
    text-align: center;
    /* Clamp to 3 lines */
    display: -webkit-box;
    -webkit-line-clamp: 3;
    line-clamp: 3;
    -webkit-box-orient: vertical;
    overflow: hidden;
    /* Smooth expand animation using max-height */
    animation: summaryExpand 0.5s ease-out;
  }

  @keyframes summaryExpand {
    from {
      opacity: 0;
      max-height: 0;
      margin-top: 0;
    }
    to {
      opacity: 1;
      max-height: 100px; /* enough for 3 lines */
      margin-top: 2px;
    }
  }

  /* Creation time: 14px, white at 0.7 opacity */
  .loaded-time {
    font-size: 14px;
    font-weight: 500;
    color: rgba(255, 255, 255, 0.85);
    text-align: center;
    margin-top: 2px;
    animation: fadeIn 0.4s ease-out 0.15s both;
  }

  /* ─── Large decorative icons (126×126px) at banner edges ─────────────── */

  .deco-icon {
    position: absolute;
    width: 126px;
    height: 126px;
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 1;
    pointer-events: none;
    /* Entrance animation: fade up from +50px below to actual position */
    animation: decoIconEnter 0.6s ease-out 0.1s both;
  }

  .deco-icon-left {
    /* Anchored just outside the center content block (max-width 480px, half=240px).
       Offset inward by 20px extra so the icon sits close to the content, not the edge. */
    left: calc(50% - 240px - 106px);
    bottom: -15px;
    transform: rotate(-15deg);
  }

  .deco-icon-right {
    /* Mirror of deco-icon-left */
    right: calc(50% - 240px - 106px);
    bottom: -15px;
    transform: rotate(15deg);
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

  /* Apply rotation via custom properties so the animation preserves it */
  .deco-icon-left {
    --deco-rotate: -15deg;
  }

  .deco-icon-right {
    --deco-rotate: 15deg;
  }

  /* ─── Chat navigation arrows ─────────────────────────────────────────────
     Positioned at the left and right edges of the banner (identical layout to
     DailyInspirationBanner's .carousel-arrow). pointer-events:auto overrides
     the banner-level pointer-events:none so only the arrows are interactive.
     ALL global button{} rules from buttons.css are overridden with !important. */
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
    pointer-events: auto; /* Re-enable interactivity for arrows despite banner pointer-events:none */
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

  /* Position arrows at the outer edges, rounded on the inner edge only */
  .nav-arrow-left {
    left: 0;
    border-radius: 0 10px 10px 0 !important; /* rounded on the right (inner) side */
  }

  .nav-arrow-right {
    right: 0;
    border-radius: 10px 0 0 10px !important; /* rounded on the left (inner) side */
  }

  /* ─── Mobile adjustments (≤730px) ───────────────────────────────────────── */

  @media (max-width: 730px) {
    .chat-header-banner {
      height: 190px;
    }

    .processing-ai-icon {
      width: 32px;
      height: 32px;
    }

    .processing-text {
      font-size: 17px;
    }

    .credits-error-text {
      font-size: 17px;
    }

    .loaded-content {
      padding: 12px 20px;
      max-width: 360px;
    }

    .loaded-icon {
      width: 32px;
      height: 32px;
    }

    .loaded-icon :global(svg) {
      width: 32px !important;
      height: 32px !important;
    }

    .loaded-title {
      font-size: 17px;
    }

    .loaded-summary {
      font-size: 13px;
      -webkit-line-clamp: 2;
      line-clamp: 2;
    }

    /* Smaller decorative icons on mobile, closer to edges */
    .deco-icon {
      width: 90px;
      height: 90px;
    }

    .deco-icon :global(svg) {
      width: 90px !important;
      height: 90px !important;
    }

    .deco-icon-left {
      /* On mobile: content max-width 360px (half=180px), icon 90px */
      left: calc(50% - 180px - 70px);
    }

    .deco-icon-right {
      right: calc(50% - 180px - 70px);
    }
  }
</style>
