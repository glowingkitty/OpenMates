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

  Dimensions:
    - Desktop: 50vh height (min 240px), 14px border-radius
    - Mobile (≤730px): 50vh height (min 190px)
    - When settings panel is open or embed fullscreen is side-by-side: reverts to fixed 240px / 190px

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
  import { onMount, onDestroy } from 'svelte';
  import { browser } from '$app/environment';
  import { getCategoryGradientColors, getValidIconName, getLucideIcon } from '../utils/categoryUtils';
  import { text } from '@repo/ui';
  import { chatNavigationStore, navigatePrev, navigateNext } from '../stores/chatNavigationStore';
  import { resolveHeaderSwipeNavigation } from './headerSwipeNavigation';

  // ─── Props ─────────────────────────────────────────────────────────────────

  let {
    title = '',
    currentChatId = null,
    category = null,
    icon = null,
    summary = null,
    isLoading = false,
    isCreditsError = false,
    chatCreatedAt = null,
    /** When true, renders the incognito-specific variant: fixed dark gradient, anonym icon,
     *  and "Incognito Mode" as the title. Overrides all other visual states. */
    isIncognito = false,
    /** When true, shows an "Example chat" badge/pill in the loaded header state. */
    isExampleChat = false,
    /** MP4 URL for the in-place video player. On play-button click the video element
     *  is mounted inside the media frame and native browser fullscreen is requested.
     *  No video is loaded before the user clicks play. */
    videoMp4Url = null,
    /** Tiny silent preview video that can autoplay safely before the full video is clicked. */
    videoTeaserUrl = null,
    /** MP4 fallback for browsers that cannot play the WebM teaser. */
    videoTeaserMp4Url = null,
    /** WebP poster/fallback for the silent teaser. */
    videoTeaserWebpUrl = null,
    /** List of image URLs rendered as a crossfading Ken-Burns slideshow inside the
     *  16:9 media frame. Used when no compact teaser video is configured. */
    backgroundFrames = null,
    /** Aggregated highlight counts across all messages in this chat. When
     *  `highlights > 0`, a yellow pill is rendered below the summary. Clicking
     *  the pill fires `onHighlightJump` so the parent can scroll to the first
     *  highlight and activate the navigation overlay. */
    highlightStats = null,
    /** Called when the user clicks the highlights pill. */
    onHighlightJump = undefined,
    autoplayVideo = false,
    /** When true, shows a large Sign Up CTA below the title inside the banner.
     *  Only used for intro chats shown to non-authenticated users. */
    showSignupCta = false,
  }: {
    title?: string;
    currentChatId?: string | null;
    category?: string | null;
    icon?: string | null;
    summary?: string | null;
    isLoading?: boolean;
    /** True when the first message on this new chat was rejected due to insufficient credits.
     *  Replaces the "Creating new chat..." shimmer with a static "Not enough credits" state. */
    isCreditsError?: boolean;
    chatCreatedAt?: number | null;
    isIncognito?: boolean;
    /** True when this chat is a pre-made example chat (shown to non-authenticated users).
     *  Displays an "Example chat" badge in the loaded header state. */
    isExampleChat?: boolean;
    /** MP4 URL — gates the play button in the media frame. The video is only
     *  loaded by the fullscreen embed after the user clicks play. */
    videoMp4Url?: string | null;
    /** Tiny silent preview video that can autoplay safely before the full video is clicked. */
    videoTeaserUrl?: string | null;
    /** MP4 fallback for browsers that cannot play the WebM teaser. */
    videoTeaserMp4Url?: string | null;
    /** WebP poster/fallback for the silent teaser. */
    videoTeaserWebpUrl?: string | null;
    /** Image URLs for the crossfading Ken-Burns slideshow inside the media frame. */
    backgroundFrames?: string[] | null;
    /** Aggregated highlight counts across all messages in this chat. */
    highlightStats?: { highlights: number; comments: number } | null;
    /** Click handler for the highlights pill. */
    onHighlightJump?: (() => void) | undefined;
    /** When true, auto-starts video playback on mount (used by &autoplay-video deep link). */
    autoplayVideo?: boolean;
    /** When true, shows a large Sign Up CTA below the title inside the banner. */
    showSignupCta?: boolean;
  } = $props();

  /** True when the static-image slideshow should render inside the media frame. */
  const useTeaser = $derived(!!videoTeaserUrl || !!videoTeaserMp4Url || !!videoTeaserWebpUrl);
  const useSlideshow = $derived(!useTeaser && Array.isArray(backgroundFrames) && backgroundFrames.length > 0);
  /** True when the header should render the 16:9 media frame at all. */
  const hasHeaderMedia = $derived(useTeaser || useSlideshow || !!videoMp4Url);
  const introTeaserCopyLines = ['AI team mates.', 'For everyday tasks & learning.', 'With privacy & safety by design.'];
  const isIntroTeaserChat = $derived(currentChatId === 'demo-for-everyone');
  const teaserCopyLines = $derived(isIntroTeaserChat ? introTeaserCopyLines : [title]);

  // ─── In-place video player ────────────────────────────────────────────────
  //
  // Clicking the play button mounts a <video> element inside the media frame
  // and immediately requests native browser fullscreen. No video is fetched
  // before the user clicks. When fullscreen exits the video is unmounted.

  let videoEl = $state<HTMLVideoElement | null>(null);
  let isVideoActive = $state(false);
  let touchStartX = $state(0);
  let touchStartY = $state(0);
  let touchSwipeHandled = $state(false);
  let teaserVideoBoxEl = $state<HTMLElement | null>(null);
  let isTeaserVideoHovering = $state(false);
  let teaserMouseX = $state(0);
  let teaserMouseY = $state(0);

  const TEASER_TILT_MAX_ANGLE = 3;
  const TEASER_TILT_PERSPECTIVE = 800;
  const TEASER_TILT_SCALE = 0.985;

  let teaserTiltTransform = $derived.by(() => {
    if (!isTeaserVideoHovering) return '';
    const rotateY = teaserMouseX * TEASER_TILT_MAX_ANGLE;
    const rotateX = -teaserMouseY * TEASER_TILT_MAX_ANGLE;
    return `perspective(${TEASER_TILT_PERSPECTIVE}px) rotateX(${rotateX}deg) rotateY(${rotateY}deg) scale(${TEASER_TILT_SCALE})`;
  });

  function handlePlayClick(e: MouseEvent) {
    e.stopPropagation();
    isVideoActive = true;
  }

  function handleTeaserPreviewClick(e: MouseEvent) {
    e.stopPropagation();
    if (!videoMp4Url) return;
    isVideoActive = true;
  }

  function handleTeaserPreviewKeydown(e: KeyboardEvent) {
    if (e.key !== 'Enter' && e.key !== ' ') return;
    e.preventDefault();
    e.stopPropagation();
    if (!videoMp4Url) return;
    isVideoActive = true;
  }

  function handleTeaserMouseEnter(e: MouseEvent) {
    isTeaserVideoHovering = true;
    updateTeaserMousePosition(e);
  }

  function handleTeaserMouseMove(e: MouseEvent) {
    if (!isTeaserVideoHovering || !teaserVideoBoxEl) return;
    updateTeaserMousePosition(e);
  }

  function handleTeaserMouseLeave() {
    isTeaserVideoHovering = false;
    teaserMouseX = 0;
    teaserMouseY = 0;
  }

  function updateTeaserMousePosition(e: MouseEvent) {
    if (!teaserVideoBoxEl) return;
    const rect = teaserVideoBoxEl.getBoundingClientRect();
    teaserMouseX = ((e.clientX - rect.left) / rect.width - 0.5) * 2;
    teaserMouseY = ((e.clientY - rect.top) / rect.height - 0.5) * 2;
  }

  // Once the video element is bound after isVideoActive flips, autoplay and
  // request fullscreen. The effect re-runs whenever videoEl changes (i.e. on
  // mount after the {#if} renders the element).
  $effect(() => {
    if (!videoEl) return;
    videoEl.play().catch(() => {});
    videoEl.requestFullscreen?.().catch(() => {});
  });

  function handleFullscreenChange() {
    if (!document.fullscreenElement && isVideoActive) {
      videoEl?.pause();
      isVideoActive = false;
    }
  }

  onMount(() => {
    if (browser) document.addEventListener('fullscreenchange', handleFullscreenChange);
    if (autoplayVideo && videoMp4Url) {
      isVideoActive = true;
    }
  });

  onDestroy(() => {
    if (browser) document.removeEventListener('fullscreenchange', handleFullscreenChange);
  });

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
  function handlePrevious(e?: MouseEvent) {
    e?.stopPropagation();
    navigatePrev();
  }

  /**
   * Navigate to the next chat in the list.
   * Calls the store's navigate method directly — works even when the sidebar
   * (Chats.svelte) is closed/unmounted because the store holds the chat list.
   */
  function handleNext(e?: MouseEvent) {
    e?.stopPropagation();
    navigateNext();
  }

  function handleHeaderTouchStart(e: TouchEvent) {
    if (e.touches.length !== 1) return;

    const touch = e.touches[0];
    touchStartX = touch.clientX;
    touchStartY = touch.clientY;
    touchSwipeHandled = false;
  }

  function handleHeaderTouchMove(e: TouchEvent) {
    if (touchSwipeHandled || e.touches.length !== 1) return;

    const touch = e.touches[0];
    const deltaX = touch.clientX - touchStartX;
    const deltaY = touch.clientY - touchStartY;
    const navigation = resolveHeaderSwipeNavigation({
      deltaX,
      deltaY,
      // Chat lists are newest-first. A right-to-left gesture should move to the
      // previous recent chat, which is the store's "next" item in sorted order.
      hasPrevious: navState.hasNext,
      hasNext: navState.hasPrev,
    });

    if (navigation === 'previous') {
      e.preventDefault();
      touchSwipeHandled = true;
      navigateNext();
      return;
    }

    if (navigation === 'next') {
      e.preventDefault();
      touchSwipeHandled = true;
      navigatePrev();
    }
  }

  function handleHeaderTouchEnd() {
    touchStartX = 0;
    touchStartY = 0;
    touchSwipeHandled = false;
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
      return $text('common.just_now');
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

  // ─── Highlights pill ───────────────────────────────────────────────────────
  /** True when at least one highlight exists in the chat — render the yellow pill. */
  let showHighlightPill = $derived(
    isLoaded && !!highlightStats && highlightStats.highlights > 0,
  );
  /** Pill label: "3 highlights" or "3 highlights, 2 comments". Picks the
   *  comments variant only when at least one comment actually exists. */
  let highlightPillLabel = $derived.by(() => {
    if (!highlightStats || highlightStats.highlights <= 0) return '';
    if (highlightStats.comments > 0) {
      return $text('chat.header.highlights_with_comments', {
        values: {
          count: highlightStats.highlights,
          comments: highlightStats.comments,
        },
      });
    }
    return $text('chat.header.highlights', {
      values: { count: highlightStats.highlights },
    });
  });
  function handleHighlightPillClick(e: MouseEvent) {
    e.stopPropagation();
    onHighlightJump?.();
  }
</script>

<!-- Banner container: always rendered when either loading or loaded.
     Smooth background-color transition from primary → category gradient.
     position:relative is required for the absolutely-positioned arrow buttons. -->
<div
  class="chat-header-banner"
  class:is-loaded={isLoaded}
  style={bannerStyle}
  role="presentation"
  ontouchstart={handleHeaderTouchStart}
  ontouchmove={handleHeaderTouchMove}
  ontouchend={handleHeaderTouchEnd}
  ontouchcancel={handleHeaderTouchEnd}
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
      <span class="loaded-title" data-testid="chat-header-title">{$text('settings.incognito_mode_active')}</span>
    </div>
  {/if}

  <!-- ── Loaded state: category icon + title + summary + time ── -->
  {#if isLoaded && !isIncognito}
    {#if useTeaser}
      <!-- ── Teaser split layout: text left + video right ──
           Mirrors the DailyInspirationBanner split: orbs provide the gradient
           backdrop, text on the left, teaser video in a rounded contained box
           on the right. The full MP4 is still mounted only after play click. -->
      <div class="teaser-split-layout">

        <!-- Left column: fixed intro teaser copy -->
        <div class="teaser-split-left">
          {#if IconComponent}
            <div class="loaded-icon" data-testid="chat-header-icon">
              <IconComponent size={38} color="white" />
            </div>
          {/if}

          <div class="teaser-copy" aria-label={teaserCopyLines.join(' ')}>
            {#each teaserCopyLines as line, index}
              <span
                class="loaded-title teaser-title teaser-copy-line"
                data-testid={index === 0 ? 'chat-header-title' : undefined}
              >{line}</span>
            {/each}
          </div>

          {#if isExampleChat}
            <span class="example-chat-badge" data-testid="example-chat-badge">{$text('chat.header.example_chat')}</span>
          {/if}

          {#if !isIntroTeaserChat && showSummary}
            <p class="loaded-summary teaser-summary" data-testid="chat-header-summary">{summary}</p>
          {/if}

          {#if showSignupCta}
            <button
              class="banner-signup-button"
              data-testid="banner-signup-button"
              onclick={() => window.dispatchEvent(new CustomEvent('openSignupInterface'))}
            >
              {$text('signup.sign_up')} / {$text('login.login')}
            </button>
          {/if}
        </div>

        <!-- Right column: teaser video in a rounded, contained box -->
        <div class="teaser-split-right">
          <div
            bind:this={teaserVideoBoxEl}
            class="teaser-video-box"
            class:hovering={isTeaserVideoHovering}
            class:clickable={!!videoMp4Url}
            role="button"
            tabindex="0"
            aria-label={videoMp4Url ? 'Play video' : undefined}
            data-testid="chat-header-teaser-video-box"
            style={teaserTiltTransform ? `transform: ${teaserTiltTransform};` : ''}
            onclick={handleTeaserPreviewClick}
            onkeydown={handleTeaserPreviewKeydown}
            onmouseenter={handleTeaserMouseEnter}
            onmousemove={handleTeaserMouseMove}
            onmouseleave={handleTeaserMouseLeave}
          >
            {#if videoTeaserUrl || videoTeaserMp4Url}
              <video
                class="teaser-video-preview"
                poster={videoTeaserWebpUrl ?? undefined}
                autoplay
                muted
                loop
                playsinline
                preload="metadata"
              >
                {#if videoTeaserUrl}
                  <source src={videoTeaserUrl} type="video/webm" />
                {/if}
                {#if videoTeaserMp4Url}
                  <source src={videoTeaserMp4Url} type="video/mp4" />
                {/if}
              </video>
            {:else if videoTeaserWebpUrl}
              <img class="teaser-video-preview" src={videoTeaserWebpUrl} alt="" loading="eager" decoding="async" />
            {/if}

            {#if videoMp4Url && !isVideoActive}
              <div
                class="video-play-btn teaser-video-play-affordance"
                data-testid="chat-header-play-btn"
                aria-hidden="true"
              >
                <div class="video-play-icon" aria-hidden="true"></div>
              </div>
            {/if}

            {#if isVideoActive && videoMp4Url}
              <video
                bind:this={videoEl}
                class="media-video"
                data-testid="chat-header-video"
                src={videoMp4Url}
                autoplay
                controls
                playsinline
                preload="auto"
              >
                <track kind="captions" />
              </video>
            {/if}
          </div>
        </div>
      </div>
    {:else}
      <!-- ── Standard layout: decorative icons + media frame or icon/title/summary ── -->

      <!-- Large decorative icons at left and right edges (126×126px, 0.4 opacity). -->
      {#if IconComponent}
        <div class="deco-icon deco-icon-left">
          <IconComponent size={126} color="white" />
        </div>
        <div class="deco-icon deco-icon-right">
          <IconComponent size={126} color="white" />
        </div>
      {/if}

      {#if hasHeaderMedia}
        <div class="media-center-group">
          <!-- Title rendered above the media frame -->
          {#if !showSignupCta}
            <div class="loaded-content">
              <!-- SECURITY: plain text only — chat titles are AI-generated from user input,
                   never render as HTML to prevent stored XSS via prompt injection. -->
              <span class="loaded-title" data-testid="chat-header-title">{title}</span>

              {#if isExampleChat}
                <span class="example-chat-badge" data-testid="example-chat-badge">{$text('chat.header.example_chat')}</span>
              {/if}
            </div>
          {/if}

          {#if useSlideshow}
            <!-- svelte-ignore a11y_click_events_have_key_events -->
            <!-- svelte-ignore a11y_no_static_element_interactions -->
            <div class="media-frame" data-testid="chat-header-media-frame" onclick={handlePlayClick}>
              <div class="header-slideshow" aria-hidden="true">
                {#each backgroundFrames as frameUrl, i (frameUrl)}
                  <img
                    class="header-slide"
                    src={frameUrl}
                    alt=""
                    loading={i === 0 ? 'eager' : 'lazy'}
                    decoding="async"
                    style="--slide-index: {i}; --slide-count: {backgroundFrames.length};"
                  />
                {/each}
              </div>

              {#if videoMp4Url && !isVideoActive}
                <button
                  class="video-play-btn"
                  onclick={handlePlayClick}
                  type="button"
                  aria-label="Play video"
                  data-testid="chat-header-play-btn"
                >
                  <div class="video-play-icon" aria-hidden="true"></div>
                </button>
              {/if}

              {#if isVideoActive && videoMp4Url}
                <!-- Mounted only after user clicks play. requestFullscreen is called
                     via $effect once the element is bound. Unmounted when fullscreen exits. -->
                <video
                  bind:this={videoEl}
                  class="media-video"
                  data-testid="chat-header-video"
                  src={videoMp4Url}
                  autoplay
                  controls
                  playsinline
                  preload="auto"
                >
                  <track kind="captions" />
                </video>
              {/if}
            </div>
          {:else}
            {#if videoMp4Url && !isVideoActive}
              <button
                class="video-play-btn"
                onclick={handlePlayClick}
                type="button"
                aria-label="Play video"
                data-testid="chat-header-play-btn"
              >
                <div class="video-play-icon" aria-hidden="true"></div>
              </button>
            {/if}

            {#if isVideoActive && videoMp4Url}
              <!-- Mounted only after user clicks play. requestFullscreen is called
                   via $effect once the element is bound. Unmounted when fullscreen exits. -->
              <video
                bind:this={videoEl}
                class="media-video"
                data-testid="chat-header-video"
                src={videoMp4Url}
                autoplay
                controls
                playsinline
                preload="auto"
              >
                <track kind="captions" />
              </video>
            {/if}
          {/if}

          <!-- Signup CTA rendered below the preview/play affordance for non-auth intro chats. -->
          {#if showSignupCta}
            <button
              class="banner-signup-button"
              data-testid="banner-signup-button"
              onclick={() => window.dispatchEvent(new CustomEvent('openSignupInterface'))}
            >
              {$text('signup.sign_up')} / {$text('login.login')}
            </button>
          {/if}
        </div>
      {:else}
        <div class="loaded-content">
          <!-- Category icon: only shown when no header media (video or slideshow) -->
          {#if IconComponent}
            <div class="loaded-icon" data-testid="chat-header-icon">
              <IconComponent size={38} color="white" />
            </div>
          {/if}

          <!-- SECURITY: plain text only — chat titles are AI-generated from user input,
               never render as HTML to prevent stored XSS via prompt injection. -->
          <span class="loaded-title" data-testid="chat-header-title">{title}</span>

          {#if isExampleChat}
            <span class="example-chat-badge" data-testid="example-chat-badge">{$text('chat.header.example_chat')}</span>
          {/if}

          <!-- Summary: fades in with max-height expand when available -->
          {#if showSummary}
            <p class="loaded-summary" data-testid="chat-header-summary">{summary}</p>
          {/if}

          <!-- Highlights pill: yellow annotation-layer count. Clickable when an
               onHighlightJump handler is wired; falls back to a static badge
               otherwise so the count is still visible in read-only contexts
               (e.g. shared-chat preview rendered without the nav overlay). -->
          {#if showHighlightPill}
            <button
              class="highlight-count-pill"
              type="button"
              data-testid="chat-header-highlight-count"
              onclick={handleHighlightPillClick}
              disabled={!onHighlightJump}
            >{highlightPillLabel}</button>
          {/if}

          <!-- Creation time -->
          {#if showTime}
            <span class="loaded-time">{formattedTime}</span>
          {/if}
        </div>
      {/if}
    {/if}
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
      data-testid="chat-header-next"
      aria-label={$text('chat.header.next_chat')}
      type="button"
    >
      <ChevronLeft size={22} color="rgba(255,255,255,0.85)" />
    </button>
  {/if}
  {#if navState.hasNext}
    <button
      class="nav-arrow nav-arrow-right"
      onclick={handleNext}
      data-testid="chat-header-previous"
      aria-label={$text('chat.header.previous_chat')}
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
    height: 35vh;
    min-height: 240px;
    /* Top corners are flush with the top of the scroll area — no top radius.
       Only bottom corners are rounded to separate the banner from messages below. */
    border-radius: 0 0 14px 14px;
    overflow: hidden;
    display: flex;
    align-items: center;
    justify-content: center;
    /* Create an independent stacking + paint context for the banner. Without
       `isolation: isolate`, the blurred orbs (filter:blur(28px), mix with
       animated gradient) share a compositor layer with the outer page, and
       Chrome can leave that layer in a stale state after a neighbouring
       layout disturbance (closing a fullscreen embed while the banner is
       scrolled off-screen) — the symptom is title/summary/icon rendered in
       the DOM but invisible until scroll/resize forces a recomposite. */
    isolation: isolate;
    transition: background 0.5s ease, height 0.3s ease, min-height 0.3s ease;
    box-shadow: var(--shadow-xl);
    pointer-events: auto;
    user-select: none;
  }

  /* When settings panel is open or embed fullscreen is side-by-side, revert to
     fixed height so the chat header matches the settings/embed header height.
     .menu-open is set on .chat-container by +page.svelte when settings is open.
     .side-by-side-active is set on .active-chat-container by ActiveChat.svelte. */
  :global(.menu-open) .chat-header-banner,
  :global(.side-by-side-active) .chat-header-banner {
    height: 240px;
    min-height: unset;
  }

  /* ─── Processing state ──────────────────────────────────────────────────── */

  .processing-content {
    /* position:relative is REQUIRED for z-index to apply — without it the text
       content paints in the default stacking layer and the blurred orbs (which
       are position:absolute with z-index:0) can composite over the top of it
       after a layout disturbance (e.g. closing a fullscreen embed), leaving
       title/summary/time invisible until a scroll/resize forces a recomposite. */
    position: relative;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: var(--spacing-6);
    z-index: var(--z-index-raised-2);
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
    font-size: var(--font-size-h3);
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
    font-size: var(--font-size-h3);
    font-weight: 600;
    color: rgba(255, 255, 255, 0.75);
    text-align: center;
  }

  /* ─── Loaded state ──────────────────────────────────────────────────────── */

  .loaded-content {
    /* position:relative is REQUIRED for z-index to apply — without it the
       content paints in the default stacking layer and the blurred orbs
       (which are position:absolute with z-index:0) composite over the top of
       it. Normally the orbs are semi-transparent enough for text to show
       through, but after a compositor disturbance (e.g. the layout change
       when closing a fullscreen embed while the header is scrolled
       off-screen) the orb layer goes opaque over the text region and stays
       that way until a scroll/resize forces a full recomposite. */
    position: relative;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: var(--spacing-2);
    z-index: var(--z-index-raised-2);
    padding: var(--spacing-8) var(--spacing-12);
    /* Narrow text block so it doesn't stretch the full banner width */
    max-width: 480px;
    width: 100%;
    opacity: 1;
    /* Promote .loaded-content to its own GPU compositor layer so its paint is
       independent of the banner's shared layer. translateZ(0) is a
       well-established hint that forces own-layer promotion without changing
       layout. Combined with the banner's `isolation: isolate` above, this
       guarantees title / summary / icon / time stay painted regardless of
       offscreen compositor optimizations that Chrome applies to the shared
       banner layer after closing a fullscreen embed. */
    transform: translateZ(0);
    /* `contain: layout paint` tells the browser that this element's layout
       and paint cannot affect anything outside of it — a strong hint that
       its paint must be kept fresh when its own size/contents change, rather
       than being cached at a stale position. */
    contain: layout paint;
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

  /* Title: 20px, white, bold, centered, truncated to 2 lines.
     Always white regardless of theme — sits on the branded gradient header. */
  .loaded-title {
    display: block;
    font-size: var(--font-size-h3);
    font-weight: 700;
    color: var(--color-font-button);
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

  /* "Example chat" badge: semi-transparent pill below the title.
     Helps unauthenticated users distinguish example chats from real ones. */
  .example-chat-badge {
    display: inline-block;
    margin-top: 6px;
    padding: 3px 12px;
    font-size: var(--font-size-xs);
    font-weight: 600;
    color: var(--color-font-button);
    background: rgba(255, 255, 255, 0.2);
    border-radius: 20px;
    letter-spacing: 0.02em;
  }

  /* Highlights pill: yellow chip showing "N highlights" or "N highlights, M
     comments". Sits below the summary inside .loaded-content. Dark text on the
     yellow token so it stays legible against any category gradient. When the
     parent wires onHighlightJump it becomes clickable with a subtle hover. */
  .highlight-count-pill {
    all: unset;
    display: inline-block;
    margin-top: var(--spacing-4);
    padding: 3px 12px;
    font-size: var(--font-size-xs);
    font-weight: 600;
    color: var(--color-grey-100, #000);
    background: var(--color-highlight-yellow, rgba(255, 213, 0, 0.4));
    border-radius: 20px;
    letter-spacing: 0.02em;
    cursor: pointer;
    /* Pill sits on top of banner media / orbs; re-enable pointer events
       (banner container uses pointer-events:none for decorative content). */
    pointer-events: auto;
    transition: background-color var(--duration-fast) var(--easing-default),
                transform var(--duration-fast) var(--easing-default);
  }

  .highlight-count-pill:hover {
    background: var(--color-highlight-yellow-solid, #ffd500);
  }

  .highlight-count-pill:active {
    transform: scale(0.97);
  }

  .highlight-count-pill:disabled {
    cursor: default;
    opacity: 0.85;
  }

  /* Summary: 14px, white, centered. Always white regardless of theme — sits on
     the branded gradient header. No entrance animation: the previous
     `summaryExpand` keyframe (opacity + max-height 0 → 1 / 100px) could get
     stuck at the 0% keyframe when the header mounted while scrolled out of view
     (e.g. right after closing a fullscreen embed), leaving the summary
     collapsed and invisible until a scroll forced a recomposite. */
  .loaded-summary {
    margin: calc(var(--spacing-1) + 2px) 0 0;
    font-size: var(--font-size-small);
    font-weight: 500;
    color: var(--color-font-button);
    line-height: 1.45;
    text-align: center;
    /* Clamp to 3 lines */
    display: -webkit-box;
    -webkit-line-clamp: 3;
    line-clamp: 3;
    -webkit-box-orient: vertical;
    overflow: hidden;
    opacity: 1;
    max-height: 100px; /* enough for 3 lines */
  }

  /* Creation time: 14px, white at 0.7 opacity.
     No entrance animation — see note on .loaded-content above for why offscreen
     CSS animations were causing title/summary/time to render invisibly. */
  .loaded-time {
    font-size: var(--font-size-small);
    font-weight: 500;
    color: rgba(255, 255, 255, 0.85);
    text-align: center;
    margin-top: var(--spacing-1);
    opacity: 1;
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
    z-index: var(--z-index-raised);
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
    transition: background-color var(--duration-fast) var(--easing-default);
    z-index: var(--z-index-dropdown-2);
    pointer-events: auto; /* Re-enable interactivity for arrows despite banner pointer-events:none */
    flex-shrink: 0;
  }

  .nav-arrow:hover {
    background-color: rgba(255, 255, 255, 0.1) !important;
    scale: none !important;
  }

  /* Pressed — scale the chevron container in slightly + deepen background
     to confirm the tap on the full-height transparent hit target. */
  .nav-arrow:active {
    background-color: rgba(0, 0, 0, 0.18) !important;
    box-shadow: inset 0 2px 6px rgba(0, 0, 0, 0.22) !important;
    scale: none !important;
    filter: none !important;
    transition: background-color 60ms var(--easing-default),
                box-shadow 60ms var(--easing-default) !important;
  }

  .nav-arrow:active :global(svg) {
    transform: scale(0.88);
    transition: transform 60ms var(--easing-default);
  }

  /* Position arrows at the outer edges, rounded on the inner edge only */
  .nav-arrow-left {
    left: 0;
    border-radius: 0 10px 10px 0 !important; /* rounded on the right (inner) side */
  }

  .nav-arrow-right {
    right: 0;
    border-radius: var(--radius-4) 0 0 10px !important; /* rounded on the left (inner) side */
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
    z-index: var(--z-index-base);
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
      height: 35vh;
      min-height: 230px;
    }

    :global(.menu-open) .chat-header-banner,
    :global(.side-by-side-active) .chat-header-banner {
      height: 230px;
      min-height: unset;
    }

    .processing-ai-icon {
      width: 32px;
      height: 32px;
    }

    .processing-text {
      font-size: var(--font-size-lg);
    }

    .credits-error-text {
      font-size: var(--font-size-lg);
    }

    .loaded-content {
      padding: var(--spacing-6) var(--spacing-10);
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
      font-size: var(--font-size-lg);
    }

    .loaded-summary {
      font-size: var(--font-size-xs);
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

    .video-play-btn {
      width: 56px !important;
      height: 56px !important;
    }

    .video-play-icon {
      border-top: 10px solid transparent;
      border-bottom: 10px solid transparent;
      border-left: 17px solid rgba(255, 255, 255, 0.95);
      margin-left: 3px;
    }
  }

  /* ─── Teaser split layout (text left + video right) ────────────────────────
     Mirrors DailyInspirationBanner's split: orbs are the gradient backdrop,
     text column on the left, teaser video in a rounded 16:9 box on the right.
     On narrow mobile, text and video alternate because both cannot fit at once. */

  .teaser-split-layout {
    position: relative;
    z-index: var(--z-index-raised-2);
    display: flex;
    align-items: center;
    gap: 28px;
    width: 100%;
    max-width: 1050px;
    padding: 14px 40px 12px;
    height: 100%;
    box-sizing: border-box;
    transform: translateZ(0);
    contain: layout paint;
  }

  .teaser-split-left {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    justify-content: center;
    gap: var(--spacing-2);
  }

  .teaser-copy {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  .teaser-copy-line {
    display: block;
  }

  /* Left-align and uncap text lines in the split layout */
  .teaser-title {
    text-align: left !important;
    -webkit-line-clamp: 1 !important;
    line-clamp: 1 !important;
  }

  .teaser-summary {
    text-align: left !important;
    -webkit-line-clamp: 3 !important;
    line-clamp: 3 !important;
  }

  .teaser-split-right {
    flex-shrink: 0;
    width: min(420px, 48%);
    align-self: center;
    display: flex;
    align-items: center;
    justify-content: flex-end;
  }

  .teaser-video-box {
    position: relative;
    width: 100%;
    aspect-ratio: 16 / 9;
    border-radius: var(--radius-4);
    overflow: hidden;
    background: #1a1a1a;
    box-shadow: var(--shadow-lg);
    transition: transform var(--duration-fast) var(--easing-default),
                box-shadow var(--duration-fast) var(--easing-default);
    transform-style: preserve-3d;
  }

  .teaser-video-box.clickable {
    cursor: pointer;
    pointer-events: auto;
  }

  .teaser-video-box.hovering {
    box-shadow:
      0 4px 12px rgba(0, 0, 0, 0.12),
      0 1px 3px rgba(0, 0, 0, 0.08);
  }

  .teaser-video-box.clickable:active {
    transform: scale(0.96) !important;
    transition: transform 0.05s ease-out;
  }

  .teaser-video-play-affordance {
    pointer-events: none;
  }

  .teaser-video-preview {
    width: 100%;
    height: 100%;
    object-fit: cover;
    object-position: center;
    display: block;
  }

  @media (max-width: 520px) {
    .teaser-split-layout {
      display: block;
      max-width: 100%;
      padding: 16px 48px;
    }

    .teaser-split-left,
    .teaser-split-right {
      position: absolute;
      inset: 16px 48px;
      width: auto;
      margin: 0;
      display: flex;
      align-items: center;
      justify-content: center;
    }

    .teaser-split-left {
      animation: mobileTeaserTextCycle 8s infinite ease-in-out;
    }

    .teaser-split-right {
      opacity: 0;
      animation: mobileTeaserVideoCycle 8s infinite ease-in-out;
    }

    .teaser-copy {
      align-items: flex-start;
      max-width: 280px;
    }

    .teaser-title {
      font-size: var(--font-size-lg);
    }

    .teaser-video-box {
      width: min(100%, 280px);
    }

    .teaser-video-box.hovering {
      transform: none !important;
    }
  }

  @keyframes mobileTeaserTextCycle {
    0%, 45% { opacity: 1; transform: translateY(0); }
    55%, 90% { opacity: 0; transform: translateY(-8px); }
    100% { opacity: 1; transform: translateY(0); }
  }

  @keyframes mobileTeaserVideoCycle {
    0%, 45% { opacity: 0; transform: translateY(8px); }
    55%, 90% { opacity: 1; transform: translateY(0); }
    100% { opacity: 0; transform: translateY(8px); }
  }

  @media (max-width: 520px) and (prefers-reduced-motion: reduce) {
    .teaser-split-layout {
      display: flex;
      flex-direction: column;
      justify-content: center;
      gap: var(--spacing-4);
    }

    .teaser-split-left,
    .teaser-split-right {
      position: static;
      inset: auto;
      animation: none !important;
      opacity: 1;
    }
  }

  /* ─── Background slideshow (static-image Ken Burns) ─────────────────────────
     Renders the intro frames inside the 16:9 .media-frame container. All N
     frames share the same fade keyframe; each frame's start is offset by a
     negative animation-delay so they sequence in. Per-frame Ken Burns
     keyframes (headerSlideKB0–12) give each frame a unique pan/zoom direction.
     Frame 0 is a locale-specific title card (zoom out). Dark #1a1a1a
     background prevents gradient bleed during crossfades. Pure CSS — no JS
     timers, no IntersectionObserver needed.

     Crossfade design (13 frames, slot = 7.692% of 104s cycle):
       • Incoming frame uses z-index 2 (on top) while fading in → old frame stays
         fully opaque below it, so the background is never visible during transition.
       • Old frame drops z-index to 1 once successor is fading in over it, then
         becomes opacity 0 after successor is fully covering it at 9.49%.
       • At the wrap-around (frame 11 → frame 0), frame 0 fades in with z-index 2
         on top of frame 11 (z-index 1) — same seamless result. */
  .header-slideshow {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    overflow: hidden;
    z-index: 0;
    /* Dark fallback so the parent frame background never peeks through during crossfades */
    background: #1a1a1a;
  }

  .header-slide {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    object-fit: cover;
    opacity: 0;
    /* Each frame occupies an 8s slot. Negative delay staggers across the full cycle.
       Per-frame Ken Burns keyframes are assigned via nth-child selectors below. */
    animation: headerSlideFade calc(var(--slide-count) * 8s) infinite linear,
               headerSlideKB1 calc(var(--slide-count) * 8s) infinite ease-in-out;
    animation-delay: calc(var(--slide-index) * -8s), calc(var(--slide-index) * -8s);
    will-change: opacity, transform;
  }

  /* Timing based on 13 frames (slot = 7.692% of cycle, fade-in window = 1.8%).
     Incoming frame holds z-index: 2 while fading in over the still-opaque outgoing
     frame (z-index: 1). Outgoing drops to opacity 0 only after successor fully covers
     it at 9.49% — background is never peeking through.
       0%      → opacity 0, z-index 2  (about to appear on top)
       1.8%    → opacity 1, z-index 2  (fully in, ~1.87s)
       7.692%  → opacity 1, z-index 2  (hold; successor now starting its fade-in below)
       7.693%  → opacity 1, z-index 1  (drop below incoming successor)
       9.49%   → opacity 1, z-index 1  (successor now fully opaque above)
       9.50%   → opacity 0, z-index 0  (gone; covered by successor)
       100%    → opacity 0, z-index 0 */
  @keyframes headerSlideFade {
    0%      { opacity: 0; z-index: 2; }
    1.8%    { opacity: 1; z-index: 2; }
    7.692%  { opacity: 1; z-index: 2; }
    7.693%  { opacity: 1; z-index: 1; }
    9.49%   { opacity: 1; z-index: 1; }
    9.50%   { opacity: 0; z-index: 0; }
    100%    { opacity: 0; z-index: 0; }
  }

  /* Ken-Burns motion — per-frame directional variants assigned via nth-child.
     Scale moves from ~1.05 to ~1.3, giving extra image area to pan through.
     Large translations reveal portions hidden at rest.
     Each variant covers the full visible window (0% → 9.49%). */

  /* Frame 0 (title frame): zoom out, stay centered */
  @keyframes headerSlideKB0 {
    0%      { transform: scale(1.3) translate3d(0, 0, 0); }
    9.49%  { transform: scale(1.05) translate3d(0, 0, 0); }
    100%    { transform: scale(1.05) translate3d(0, 0, 0); }
  }

  /* Frame 1: pan right → left */
  @keyframes headerSlideKB1 {
    0%      { transform: scale(1.15) translate3d(8%, 0, 0); }
    9.49%  { transform: scale(1.15) translate3d(-8%, 0, 0); }
    100%    { transform: scale(1.15) translate3d(-8%, 0, 0); }
  }

  /* Frame 2: zoom out, stay centered */
  @keyframes headerSlideKB2 {
    0%      { transform: scale(1.3) translate3d(0, 0, 0); }
    9.49%  { transform: scale(1.05) translate3d(0, 0, 0); }
    100%    { transform: scale(1.05) translate3d(0, 0, 0); }
  }

  /* Frame 3: pan bottom → top */
  @keyframes headerSlideKB3 {
    0%      { transform: scale(1.12) translate3d(0, 12%, 0); }
    9.49%  { transform: scale(1.12) translate3d(0, -12%, 0); }
    100%    { transform: scale(1.12) translate3d(0, -12%, 0); }
  }

  /* Frame 4: pan top-right → bottom-left */
  @keyframes headerSlideKB4 {
    0%      { transform: scale(1.12) translate3d(6%, -10%, 0); }
    9.49%  { transform: scale(1.28) translate3d(-6%, 10%, 0); }
    100%    { transform: scale(1.28) translate3d(-6%, 10%, 0); }
  }

  /* Frame 5: pan bottom → top (default A) */
  @keyframes headerSlideKB5 {
    0%      { transform: scale(1.1) translate3d(0, 12%, 0); }
    9.49%  { transform: scale(1.28) translate3d(0, -12%, 0); }
    100%    { transform: scale(1.28) translate3d(0, -12%, 0); }
  }

  /* Frame 6: pan left → right */
  @keyframes headerSlideKB6 {
    0%      { transform: scale(1.15) translate3d(-8%, 0, 0); }
    9.49%  { transform: scale(1.15) translate3d(8%, 0, 0); }
    100%    { transform: scale(1.15) translate3d(8%, 0, 0); }
  }

  /* Frame 7: pan top → bottom */
  @keyframes headerSlideKB7 {
    0%      { transform: scale(1.12) translate3d(0, -12%, 0); }
    9.49%  { transform: scale(1.28) translate3d(0, 12%, 0); }
    100%    { transform: scale(1.28) translate3d(0, 12%, 0); }
  }

  /* Frame 8: pan bottom-left → top-right */
  @keyframes headerSlideKB8 {
    0%      { transform: scale(1.12) translate3d(-6%, 10%, 0); }
    9.49%  { transform: scale(1.28) translate3d(6%, -10%, 0); }
    100%    { transform: scale(1.28) translate3d(6%, -10%, 0); }
  }

  /* Frame 9: zoom out from bottom (content at bottom of image) */
  @keyframes headerSlideKB9 {
    0%      { transform: scale(1.3) translate3d(0, 12%, 0); }
    9.49%  { transform: scale(1.05) translate3d(0, 0, 0); }
    100%    { transform: scale(1.05) translate3d(0, 0, 0); }
  }

  /* Frame 10: pan top-right → bottom-left */
  @keyframes headerSlideKB10 {
    0%      { transform: scale(1.12) translate3d(6%, -10%, 0); }
    9.49%  { transform: scale(1.28) translate3d(-6%, 10%, 0); }
    100%    { transform: scale(1.28) translate3d(-6%, 10%, 0); }
  }

  /* Frame 11: show top part, pan down to bottom */
  @keyframes headerSlideKB11 {
    0%      { transform: scale(1.15) translate3d(0, -12%, 0); }
    9.49%  { transform: scale(1.15) translate3d(0, 12%, 0); }
    100%    { transform: scale(1.15) translate3d(0, 12%, 0); }
  }

  /* Frame 12: focus on right side, zoom out from there */
  @keyframes headerSlideKB12 {
    0%      { transform: scale(1.3) translate3d(10%, 0, 0); }
    9.49%  { transform: scale(1.05) translate3d(0, 0, 0); }
    100%    { transform: scale(1.05) translate3d(0, 0, 0); }
  }

  /* Per-frame Ken Burns assignment — frame 0 is the locale-specific title frame (zoom out) */
  .header-slide:nth-child(1)  { animation-name: headerSlideFade, headerSlideKB0; }
  .header-slide:nth-child(2)  { animation-name: headerSlideFade, headerSlideKB1; }
  .header-slide:nth-child(3)  { animation-name: headerSlideFade, headerSlideKB2; }
  .header-slide:nth-child(4)  { animation-name: headerSlideFade, headerSlideKB3; }
  .header-slide:nth-child(5)  { animation-name: headerSlideFade, headerSlideKB4; }
  .header-slide:nth-child(6)  { animation-name: headerSlideFade, headerSlideKB5; }
  .header-slide:nth-child(7)  { animation-name: headerSlideFade, headerSlideKB6; }
  .header-slide:nth-child(8)  { animation-name: headerSlideFade, headerSlideKB7; }
  .header-slide:nth-child(9)  { animation-name: headerSlideFade, headerSlideKB8; }
  .header-slide:nth-child(10) { animation-name: headerSlideFade, headerSlideKB9; }
  .header-slide:nth-child(11) { animation-name: headerSlideFade, headerSlideKB10; }
  .header-slide:nth-child(12) { animation-name: headerSlideFade, headerSlideKB11; }
  .header-slide:nth-child(13) { animation-name: headerSlideFade, headerSlideKB12; }

  @media (prefers-reduced-motion: reduce) {
    .header-slide,
    .header-slide:nth-child(n) {
      animation: headerSlideFade calc(var(--slide-count) * 8s) infinite linear !important;
      animation-delay: calc(var(--slide-index) * -8s) !important;
    }
  }

  /* ─── Play button ──────────────────────────────────────────────────────── */

  /* Centered absolutely inside .media-frame. The transform combines the
     centering offset with the hover/active scale so both compose cleanly. */
  .video-play-btn {
    position: absolute;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    display: flex;
    align-items: center;
    justify-content: center;
    width: 72px !important;
    height: 72px !important;
    min-width: unset !important;
    border-radius: 50% !important;
    background: rgba(255, 255, 255, 0.22) !important;
    backdrop-filter: blur(8px);
    -webkit-backdrop-filter: blur(8px);
    border: 2px solid rgba(255, 255, 255, 0.55) !important;
    cursor: pointer;
    pointer-events: auto;
    transition: background var(--duration-fast) var(--easing-default),
                transform var(--duration-fast) var(--easing-default);
    flex-shrink: 0;
    padding: 0 !important;
    margin: 0 !important;
    filter: none !important;
    z-index: 3;
  }

  .video-play-btn:hover {
    background: rgba(255, 255, 255, 0.35) !important;
    transform: translate(-50%, -50%) scale(1.06);
    filter: none !important;
    scale: none !important;
  }

  .video-play-btn:active {
    background: rgba(255, 255, 255, 0.45) !important;
    transform: translate(-50%, -50%) scale(0.97);
    filter: none !important;
    scale: none !important;
  }

  /* Triangle play icon via CSS border trick */
  .video-play-icon {
    width: 0;
    height: 0;
    border-top: 13px solid transparent;
    border-bottom: 13px solid transparent;
    border-left: 22px solid rgba(255, 255, 255, 0.95);
    margin-left: 4px; /* optical centering */
  }

  /* In-place video player — mounted after play click, fills the media frame.
     requestFullscreen is called via $effect; unmounted when fullscreen exits. */
  .media-video {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    object-fit: cover;
    z-index: 4;
    background: #000;
  }

  /* ─── Media header: 16:9 framed slideshow + title below ──────────────────
     The slideshow frames live inside a 16:9 rounded container with the play
     button centered on top. The chat title is rendered below the frame so it
     is always readable — the frames stay visually contained rather than
     filling the entire banner. */

  .media-center-group {
    position: relative;
    z-index: 2;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: var(--spacing-5);
    pointer-events: auto;
    padding: var(--spacing-4) var(--spacing-8) var(--spacing-5);
    width: 100%;
    height: 100%;
    box-sizing: border-box;
  }

  /* 16:9 rounded container that hosts the slideshow + play button. Height is
     driven by the banner size so the frame scales responsively; aspect-ratio
     keeps the 16:9 ratio, and max-width prevents collision with the nav arrows. */
  .media-frame {
    position: relative;
    flex-shrink: 0;
    aspect-ratio: 16 / 9;
    height: 72%;
    max-height: 1080px;
    max-width: calc(100% - 100px);
    border-radius: 14px;
    overflow: hidden;
    background: #1a1a1a;
    box-shadow: var(--shadow-lg);
    cursor: pointer;
    pointer-events: auto;
  }

  /* Scoped override: inside the media group, loaded-content is inline (not
     absolutely positioned) and inherits the group's centering. No entrance
     animation — see .loaded-content rule above for rationale. */
  .media-center-group .loaded-content {
    position: static;
    padding: 0;
    opacity: 1;
  }

  /* Tablet and below (≤900px): push content below the absolute-positioned
     new-chat/report-issue buttons (≈50px from top) and keep 16:9 ratio.
     height:min() provides a definite value so width:auto (inherited from base)
     can derive the correct width via aspect-ratio:16/9 — no ratio-breaking
     width:100% is needed. 46px = title(30) + gap(16). */
  @media (max-width: 900px) {
    .media-center-group {
      padding-top: 55px;
      justify-content: flex-start;
    }
    .media-frame {
      height: min(72%, calc(100% - 46px));
      max-height: unset;
    }
  }

  /* Mobile (≤730px): same height-driven sizing as ≤900px (inherited).
     Relax max-width so the frame can be slightly wider on narrow screens. */
  @media (max-width: 730px) {
    .media-frame {
      max-width: calc(100% - 40px);
    }
  }

  /* Sign-up CTA rendered inside the banner below the title, for non-auth intro chats. */
  .banner-signup-button {
    all: unset;
    margin-top: var(--spacing-2);
    padding: var(--spacing-5) var(--spacing-10);
    border-radius: var(--radius-3);
    background-color: var(--color-button-primary);
    color: white;
    cursor: pointer;
    font-size: var(--font-size-lg);
    font-weight: 700;
    white-space: nowrap;
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.25);
    transition: transform var(--duration-normal) var(--easing-default), box-shadow var(--duration-normal) var(--easing-default);
    pointer-events: auto;
  }

  .banner-signup-button:hover {
    transform: scale(1.03);
    box-shadow: 0 6px 20px rgba(0, 0, 0, 0.3);
  }

  .banner-signup-button:active {
    background-color: var(--color-button-primary-pressed);
    transform: scale(0.97);
    box-shadow: none;
  }
</style>
