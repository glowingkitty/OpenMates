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
    - Static coins icon (38×38px, white, 0.6 opacity) + "Not enough credits" text (20px, white, static)
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
    /** When true, renders the incognito-specific variant: fixed dark gradient, anonym icon,
     *  and "Incognito Mode" as the title. Overrides all other visual states. */
    isIncognito = false,
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
    isIncognito?: boolean;
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

  /** Gradient background style for the banner. Incognito gets a fixed dark privacy gradient;
   *  loading/credits-error gets the primary gradient; loaded state uses the category gradient.
   *
   *  Also emits --orb-color-a (the "outside" background color) and --orb-color-b (the "inside"
   *  orb color) as CSS custom properties consumed by the living gradient orb animation.
   *  The orbs use radial-gradient(--orb-color-b → transparent) so they glow out of --orb-color-a,
   *  matching the Creative Code Berlin aesthetic: soft light blooms with no hard edges. */
  let bannerStyle = $derived.by(() => {
    if (isIncognito) {
      // Fixed dark privacy-themed gradient for incognito chats
      return [
        'background: linear-gradient(135deg, #1a1a2e 0%, #2d2d44 50%, #1e1e35 100%)',
        '--orb-color-a: #1a1a2e',
        '--orb-color-b: #6b6baa',
      ].join(';');
    }
    if (isLoading || isCreditsError || !category) {
      // Processing state or credits error: use the primary gradient from theme.css
      return [
        'background: var(--color-primary)',
        '--orb-color-a: #4867cd',
        '--orb-color-b: #a0beff',
      ].join(';');
    }
    const colors = getCategoryGradientColors(category);
    if (!colors) {
      return [
        'background: var(--color-primary)',
        '--orb-color-a: #4867cd',
        '--orb-color-b: #a0beff',
      ].join(';');
    }
    return [
      `background: linear-gradient(135deg, ${colors.start}, ${colors.end})`,
      `--orb-color-a: ${colors.start}`,
      `--orb-color-b: ${colors.end}`,
    ].join(';');
  });

  /** Lucide icon component for the category, resolved from icon name + fallback. */
  let IconComponent = $derived.by(() => {
    if (!category) return null;
    const iconName = getValidIconName(icon || '', category);
    return getLucideIcon(iconName);
  });

  /** Whether the loaded state should be shown (transition from processing → loaded).
   *  For incognito chats, this is always true — there's no loading phase. */
  let isLoaded = $derived(isIncognito || (!isLoading && !!title && !!category));

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
  <!-- ── Living gradient orbs (Creative Code aesthetic) ──────────────────────
       Three soft radial-gradient blobs that slowly morph shape and drift
       around the banner. Each uses --orb-color-b as the orb center color and
       fades to transparent at the edges, glowing against --orb-color-a (the
       background). Heavy blur removes all hard edges — you only see the light.
       Prime-number durations (11s / 13s / 17s morph, 19s / 23s / 29s drift)
       ensure the three orbs never synchronise, keeping the motion organic and
       non-repeating within any reasonable viewing window.
       z-index:0 keeps them behind all content (z-index:1+ for content). -->
  <div class="banner-orbs" aria-hidden="true">
    <div class="orb orb-1"></div>
    <div class="orb orb-2"></div>
    <div class="orb orb-3"></div>
  </div>

  <!-- ── Processing state: AI icon + "Creating new chat ..." with shimmer ── -->
  {#if isLoading && !isCreditsError && !isIncognito}
    <div class="processing-content">
      <div class="processing-ai-icon"></div>
      <span class="processing-text">{$text('chat.creating_new_chat')}</span>
    </div>
  {/if}

  <!-- ── Credits error state: static AI icon + "Not enough credits" text ──
       Shown when the first message on a new chat was rejected due to 0 credits.
       Same blue background as the loading state but no shimmer animation.
       Stays visible until the user sends another message or switches chat. -->
  {#if isCreditsError && !isIncognito}
    <div class="processing-content credits-error-content">
      <div class="processing-ai-icon credits-error-icon"></div>
      <span class="credits-error-text">{$text('chat.header.not_enough_credits')}</span>
    </div>
  {/if}

  <!-- ── Incognito state: anonym icon + "Incognito Mode" label ──
       Shown immediately when isIncognito=true. Uses the anonym.svg mask icon and
       a fixed dark privacy gradient (set via bannerStyle). No shimmer, no summary. -->
  {#if isIncognito}
    <!-- Large decorative anonym icons at left and right edges -->
    <div class="deco-icon deco-icon-left incognito-deco-icon"></div>
    <div class="deco-icon deco-icon-right incognito-deco-icon"></div>

    <div class="loaded-content">
      <!-- Anonym icon (38×38px) using CSS mask -->
      <div class="incognito-header-icon"></div>

      <!-- "Incognito Mode" title -->
      <span class="loaded-title">{$text('settings.incognito_mode_active')}</span>
    </div>
  {/if}

  <!-- ── Loaded state: category icon + title + summary + time ── -->
  {#if isLoaded && !isIncognito}
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
      <!-- SECURITY: Use plain text interpolation — chat titles are AI-generated from user input
           and must never be rendered as HTML to prevent stored XSS via prompt injection. -->
      <span class="loaded-title">{title}</span>

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
       Visible in all banner states (loading, credits error, loaded) — once the user has
       sent a message they should be able to switch chats at any time without restriction.
       Use pointer-events:auto to override the banner's pointer-events:none. -->
  {#if navState.hasPrev}
    <button
      class="nav-arrow nav-arrow-left"
      onclick={handlePrevious}
      aria-label={$text('chat.header.previous_chat')}
      type="button"
    >
      <ChevronLeft size={22} color="rgba(255,255,255,0.85)" />
    </button>
  {/if}
  {#if navState.hasNext}
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
    /* Override the AI sparkle mask with the coins icon for a clearer "not enough credits" visual.
       Static white at reduced opacity, no shimmer animation. */
    -webkit-mask-image: url('@openmates/ui/static/icons/coins.svg') !important;
    mask-image: url('@openmates/ui/static/icons/coins.svg') !important;
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

  /* ─── Incognito header icon (38×38px) — uses anonym.svg via CSS mask ─── */

  .incognito-header-icon {
    width: 38px;
    height: 38px;
    flex-shrink: 0;
    -webkit-mask-image: url('@openmates/ui/static/icons/anonym.svg');
    mask-image: url('@openmates/ui/static/icons/anonym.svg');
    -webkit-mask-size: contain;
    mask-size: contain;
    -webkit-mask-repeat: no-repeat;
    mask-repeat: no-repeat;
    -webkit-mask-position: center;
    mask-position: center;
    background-color: rgba(255, 255, 255, 0.9);
  }

  /* ─── Incognito decorative large icons at banner edges (126×126px) ────── */

  .incognito-deco-icon {
    -webkit-mask-image: url('@openmates/ui/static/icons/anonym.svg');
    mask-image: url('@openmates/ui/static/icons/anonym.svg');
    -webkit-mask-size: contain;
    mask-size: contain;
    -webkit-mask-repeat: no-repeat;
    mask-repeat: no-repeat;
    -webkit-mask-position: center;
    mask-position: center;
    background-color: rgba(255, 255, 255, 0.15);
    /* Incognito icons settle at full opacity — override the shared default (0.4) */
    --deco-target-opacity: 1;
    /* Orbital float radius for 126px icons */
    --float-rx: 10px;
    --float-ry: 12px;
    /* Two-phase: entrance → circular orbit loop (keyframes in animations.css) */
    animation:
      decoEnter 0.6s ease-out 0.1s both,
      decoFloat 16s linear 0.7s infinite;
  }

  @media (prefers-reduced-motion: reduce) {
    .incognito-deco-icon {
      animation: decoEnter 0.6s ease-out 0.1s both !important;
    }
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
    /* Orbital float radius for 126px banner icons */
    --float-rx: 10px;
    --float-ry: 12px;
    /* Two-phase: decoEnter (one-shot) → decoFloat (circular orbit, infinite).
       Keyframes defined in animations.css (shared across all three banner components). */
    animation:
      decoEnter 0.6s ease-out 0.1s both,
      decoFloat 16s linear 0.7s infinite;
  }

  .deco-icon-left {
    left: calc(50% - 240px - 106px);
    bottom: -15px;
    --deco-rotate: -15deg;
    /* Left icon starts at 0° of orbit (top) */
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

  /* Reduced-motion: entrance only, no float */
  @media (prefers-reduced-motion: reduce) {
    .deco-icon {
      animation: decoEnter 0.6s ease-out 0.1s both !important;
    }
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

  /* ─── Living gradient orbs ──────────────────────────────────────────────────
     Creative Code Berlin aesthetic: soft radial-gradient light blooms that
     drift and morph slowly. The background is --orb-color-a; each orb is a
     radial gradient from --orb-color-b (center, full) → transparent (edge).
     mix-blend-mode: screen makes overlapping orbs blend additively (light on
     light), which is exactly what produces the rich multi-color glow seen in
     generative art backgrounds.

     Architecture:
       - .banner-orbs: full-bleed absolute container, z-index 0, no pointer events
       - .orb: each orb is position:absolute, sized large (covers ~80% banner),
         border-radius morphs between 4 different organic shapes on a loop,
         translate drifts slowly to a different quadrant and back
       - filter: blur(55px) on each orb removes all shape definition — only the
         color light remains visible
       - The three orbs use prime-number durations to prevent synchronisation

     CSS custom properties set in bannerStyle (TypeScript):
       --orb-color-a  background / outer color  (= gradient start color)
       --orb-color-b  orb center / inner color   (= gradient end color)  */

  .banner-orbs {
    position: absolute;
    inset: 0;
    z-index: 0;
    pointer-events: none;
    overflow: hidden;
  }

  .orb {
    position: absolute;
    /* Large orbs — each covers roughly half the banner so the color fills
       the space and the blur edge stays well inside the boundary */
    width: 480px;
    height: 420px;
    /* Radial gradient: full --orb-color-b at center, holds solid until 40%,
       then fades to transparent by 85%. This wide solid core is what makes
       the color actually visible — the previous 0%→70% was too narrow. */
    background: radial-gradient(
      ellipse at center,
      var(--orb-color-b) 0%,
      var(--orb-color-b) 40%,
      transparent 85%
    );
    /* No mix-blend-mode: screen — it cancels out against gradient backgrounds.
       Normal blend at high opacity gives the rich, saturated color effect. */
    /* Moderate blur — enough to erase hard edges but not so much it kills
       the color intensity. 28px is the sweet spot for a 240px tall banner. */
    filter: blur(28px);
    opacity: 0.55;
    will-change: transform, border-radius;
  }

  /* Orb 1 — left-center area
     Morph: 11s   Drift: 19s   (prime → never sync with others) */
  .orb-1 {
    top: -80px;
    left: -100px;
    animation:
      orbMorph1 11s ease-in-out infinite,
      orbDrift1 19s ease-in-out infinite;
  }

  /* Orb 2 — right-bottom area */
  .orb-2 {
    bottom: -120px;
    right: -120px;
    width: 460px;
    height: 400px;
    animation:
      orbMorph2 13s ease-in-out infinite,
      orbDrift2 23s ease-in-out infinite;
  }

  /* Orb 3 — center roamer, slightly smaller and more transparent
     so it blends the two main orbs rather than dominating */
  .orb-3 {
    top: -20px;
    left: 25%;
    width: 340px;
    height: 300px;
    opacity: 0.38;
    animation:
      orbMorph3 17s ease-in-out infinite,
      orbDrift3 29s ease-in-out infinite;
  }

  /* Orb morph + drift @keyframes are in animations.css (shared globally).
     Reduced-motion: stop all orb animations, keep as static glows. */
  @media (prefers-reduced-motion: reduce) {
    .orb { animation: none !important; }
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
