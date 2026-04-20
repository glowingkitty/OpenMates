<script lang="ts">
  /**
   * DailyInspirationBanner.svelte
   *
   * Displays up to 3 daily inspiration banners in a carousel at the top of the
   * new chat screen (welcome screen). Each banner shows:
   *   - A gradient background (category colour from getCategoryGradientColors)
   *   - A "Daily inspiration" label with a BookOpen icon (top-left)
   *   - The mate profile image (category-specific, with AI badge) left of the text
   *   - The inspiration phrase (main text)
   *   - A "Click to start chat" CTA (text + create icon, no pill background)
   *   - A VideoEmbedPreview card (right side, if video attached) — full height
   *   - Left/right carousel arrows when there are multiple inspirations
   *
   * Interaction model:
   *   - Click on the video thumbnail → opens the video in fullscreen (via onEmbedFullscreen)
   *   - Click anywhere else → creates a local-only chat from this inspiration (via onStartChat)
   *   - Left/right arrow buttons → navigate the carousel
   *
   * Layout:
   *   - Banner is fixed-height: 240px on desktop, 190px on mobile (≤730px)
   *   - Inner content is max-width 680px, centered
   *   - Embed card is shown at full banner height on the right, not cut off
   *
   * Architecture note: The store (dailyInspirationStore) is a Svelte 4 writable.
   * This component uses Svelte 5 runes exclusively for its own state.
   */

  import { onMount, onDestroy } from 'svelte';
  import { get } from 'svelte/store';
  import { text } from '@repo/ui';
  import { getCategoryGradientColors } from '../utils/categoryUtils';
  import { dailyInspirationStore, type DailyInspiration } from '../stores/dailyInspirationStore';
  import { loadDefaultInspirations } from '../demo_chats/loadDefaultInspirations';
  import { authStore } from '../stores/authStore';
  import VideoEmbedPreview from './embeds/videos/VideoEmbedPreview.svelte';

  // ─── Lucide icons ────────────────────────────────────────────────────────────

  import { getLucideIcon, getValidIconName } from '../utils/categoryUtils';

  const BookOpen = getLucideIcon('book-open');
  const ChevronLeft = getLucideIcon('chevron-left');
  const ChevronRight = getLucideIcon('chevron-right');

  // ─── Component props ────────────────────────────────────────────────────────

  interface Props {
    /** Called when the user clicks the banner to start a chat from this inspiration. */
    onStartChat: (inspiration: DailyInspiration) => void;
    /**
     * Called when the user clicks the video thumbnail area.
     * Should open the video in fullscreen without creating a chat yet.
     */
    onEmbedFullscreen?: (inspiration: DailyInspiration) => void;
    /**
     * The actual pixel width of the container holding this banner.
     * Used to hide the video embed when there isn't enough horizontal space
     * to display both the text and the embed side-by-side.
     * Below 520px the embed is hidden so the text never gets squeezed.
     * Defaults to 0 (embed hidden until width is known).
     */
    containerWidth?: number;
  }

  let { onStartChat, onEmbedFullscreen, containerWidth = 0 }: Props = $props();

  // ─── Local state (Svelte 5 runes) ──────────────────────────────────────────

  // Mirror of the store – updated via subscription below
  let inspirations = $state<DailyInspiration[]>([]);
  let currentIndex = $state(0);

  // Track which inspiration_ids we have already sent a `viewed` WS event for.
  // An entry is added as soon as the banner is visible in the viewport AND the
  // inspiration is the currently displayed carousel slide — this ensures each
  // unique inspiration is counted toward tomorrow's replacement quota even if
  // the user never clicks it (passive view tracking).
  let viewedIds = $state(new Set<string>());

  // Whether the banner wrapper is currently intersecting the viewport.
  // Set by the IntersectionObserver mounted in onMount.
  let isBannerVisible = $state(false);

  // Reference to the outer wrapper element — used as the IntersectionObserver target.
  let bannerWrapperEl = $state<HTMLElement | null>(null);

  // ─── Crossfade when data source changes ─────────────────────────────────────
  // When hardcoded inspirations are replaced by real data (IndexedDB / server /
  // WS), the banner crossfades: the old content fades out, then the new content
  // fades in. This avoids a jarring instant swap.
  const HARDCODED_ID_PREFIX = "hardcoded-";
  let isCrossfading = $state(false);

  // ─── Subscribe to store ─────────────────────────────────────────────────────

  const unsubscribe = dailyInspirationStore.subscribe((state) => {
    const wasHardcoded = inspirations.length > 0 &&
      inspirations.every((i) => i.inspiration_id.startsWith(HARDCODED_ID_PREFIX));
    const isNowReal = state.inspirations.length > 0 &&
      !state.inspirations.every((i) => i.inspiration_id.startsWith(HARDCODED_ID_PREFIX));

    if (wasHardcoded && isNowReal) {
      // Trigger crossfade: fade out, swap data, fade in
      isCrossfading = true;
      setTimeout(() => {
        inspirations = state.inspirations;
        currentIndex = state.currentIndex;
        // Allow a frame for the DOM to update with new data before fading in
        requestAnimationFrame(() => {
          isCrossfading = false;
        });
      }, 200); // Match the CSS fade-out duration
    } else {
      inspirations = state.inspirations;
      currentIndex = state.currentIndex;
    }
  });

  onDestroy(unsubscribe);

  // ─── Reload inspirations on language change ─────────────────────────────────
  // Default (non-personalized) inspirations are fetched from the server with a
  // lang parameter. When the user switches language, we clear the store and
  // re-fetch so the inspiration phrases match the new locale.
  // Personalized inspirations (from WS/IndexedDB) are AI-generated content in the
  // user's language at creation time — they cannot be retranslated, so we skip.
  onMount(() => {
    const handleLanguageChange = () => {
      const state = get(dailyInspirationStore);
      if (!state.isPersonalized) {
        dailyInspirationStore.reset();
        loadDefaultInspirations({ allowIndexedDB: false }).catch((err) => {
          console.error('[DailyInspirationBanner] Failed to reload inspirations after language change:', err);
        });
      }
    };
    // Use 'language-changed-complete' (fires 50ms after locale.set + waitLocale)
    // to ensure the svelte-i18n locale store is fully settled before re-fetching.
    window.addEventListener('language-changed-complete', handleLanguageChange);
    return () => window.removeEventListener('language-changed-complete', handleLanguageChange);
  });

  // ─── Passive view tracking via IntersectionObserver ─────────────────────────
  //
  // Goal: mark an inspiration as "viewed" as soon as the user can actually see
  // it — regardless of whether they click it.  This feeds the daily generation
  // job's "how many new ones to create tomorrow" counter.
  //
  // Approach:
  //   1. An IntersectionObserver watches the outer wrapper element. When it
  //      enters the viewport (≥50 % visible), isBannerVisible becomes true.
  //   2. A reactive $effect watches (isBannerVisible + current). Whenever both
  //      are truthy and the current inspiration hasn't been reported yet, it
  //      sends the `inspiration_viewed` WS event and records the ID in viewedIds.
  //   3. Carousel navigation: currentIndex changes → current changes → the effect
  //      re-runs → the newly-shown inspiration is reported (if the banner is
  //      still in view).

  // Attach / detach the IntersectionObserver whenever the wrapper element is
  // mounted or unmounted (Svelte 5 $effect re-runs when bannerWrapperEl changes).
  $effect(() => {
    if (typeof IntersectionObserver === 'undefined') return;
    if (!bannerWrapperEl) return;

    const observer = new IntersectionObserver(
      (entries) => {
        const entry = entries[0];
        isBannerVisible = entry?.isIntersecting ?? false;
      },
      { threshold: 0.5 },
    );

    observer.observe(bannerWrapperEl);
    return () => observer.disconnect();
  });

  // Fire `inspiration_viewed` whenever the current inspiration becomes visible.
  $effect(() => {
    if (!isBannerVisible) return;
    if (!current) return;
    const id = current.inspiration_id;
    if (viewedIds.has(id)) return;

    // Mark before sending to prevent duplicate sends if the effect re-runs quickly
    viewedIds = new Set([...viewedIds, id]);
    sendViewedEvent(id);
  });

  // ─── Derived values ─────────────────────────────────────────────────────────

  /** Currently displayed inspiration. */
  let current = $derived(inspirations[currentIndex] ?? null);

  /** Background gradient style string for the current card.
   *  Also emits --orb-color-a (start/outer) and --orb-color-b (end/inner) as
   *  CSS custom properties consumed by the living gradient orb animation — same
   *  technique as ChatHeader.svelte. */
  let gradientStyle = $derived.by(() => {
    if (!current) return '';
    const colors = getCategoryGradientColors(current.category);
    if (!colors) {
      return [
        'background: linear-gradient(135deg, #1a237e, #3949ab)',
        '--orb-color-a: #1a237e',
        '--orb-color-b: #3949ab',
      ].join(';');
    }
    return [
      `background: linear-gradient(135deg, ${colors.start}, ${colors.end})`,
      `--orb-color-a: ${colors.start}`,
      `--orb-color-b: ${colors.end}`,
    ].join(';');
  });

  /** Whether multiple inspirations are available (show arrows). */
  let hasMultiple = $derived(inspirations.length > 1);

  /**
   * Whether to show a video embed for the current inspiration.
   * True when a video object is present (has a youtube_id) AND there is enough
   * horizontal space in the container to display both the text and the embed
   * side-by-side without squeezing either.  We require at least 520px: ~220px
   * for the embed card, ~200px for the text, plus padding/gap overhead.
   * When containerWidth is 0 (unknown) we default to hiding the embed to avoid
   * a layout flash.
   */
  let hasVideo = $derived(!!current?.video?.youtube_id && containerWidth >= 520);

  /**
   * The embed_id to use for VideoEmbedPreview.
   * Uses embed_id from the inspiration if already stored, otherwise generates a
   * deterministic one from the youtube_id for preview purposes.
   */
  let embedPreviewId = $derived.by(() => {
    if (!current) return '';
    if (current.embed_id) return current.embed_id;
    return current.video?.youtube_id ? `youtube-${current.video.youtube_id}` : '';
  });

  /**
   * Lucide icon component for the current inspiration's category.
   * Used for the large decorative icons at the left and right edges of the banner,
   * mirroring the same visual treatment as ChatHeader.svelte's deco-icon elements.
   */
  let CategoryIconComponent = $derived.by(() => {
    if (!current) return null;
    const iconName = getValidIconName('', current.category);
    return getLucideIcon(iconName);
  });

  /**
   * YouTube URL for the embed preview.
   */
  let videoUrl = $derived(
    current?.video?.youtube_id
      ? `https://www.youtube.com/watch?v=${current.video.youtube_id}`
      : ''
  );

  // ─── Event handlers ─────────────────────────────────────────────────────────

  /**
   * Navigate to the previous inspiration in the carousel.
   * stopPropagation prevents the banner's onclick from firing.
   */
  function handlePrevious(e: MouseEvent) {
    e.stopPropagation();
    e.preventDefault();
    dailyInspirationStore.previous();
  }

  /**
   * Navigate to the next inspiration in the carousel.
   * stopPropagation prevents the banner's onclick from firing.
   */
  function handleNext(e: MouseEvent) {
    e.stopPropagation();
    e.preventDefault();
    dailyInspirationStore.next();
  }

  /**
   * Handle clicking on the banner body — start a chat from this inspiration.
   * Also marks the inspiration as viewed via WebSocket.
   */
  function handleStartChat(_e: MouseEvent) {
    if (!current) return;

    // Send viewed event if not already sent
    if (!viewedIds.has(current.inspiration_id)) {
      viewedIds = new Set([...viewedIds, current.inspiration_id]);
      sendViewedEvent(current.inspiration_id);
    }

    onStartChat(current);
  }

  /**
   * Handle clicking on the video embed area — open video in fullscreen.
   * Does NOT start a chat. stopPropagation prevents handleStartChat from firing.
   *
   * NOTE: This handler is kept for the wrapper div's onclick, but UnifiedEmbedPreview
   * calls e.stopPropagation() before its own onFullscreen, so clicks never bubble up
   * to this wrapper. The actual fullscreen open happens via handleVideoEmbedFullscreen
   * passed directly as onFullscreen to VideoEmbedPreview.
   */
  function handleEmbedClick(e: MouseEvent) {
    e.stopPropagation();
    e.preventDefault();
    if (!current) return;

    if (onEmbedFullscreen) {
      onEmbedFullscreen(current);
    } else {
      // Fallback: start chat (same as clicking the banner)
      handleStartChat(e);
    }
  }

  /**
   * Passed directly as onFullscreen to VideoEmbedPreview.
   * UnifiedEmbedPreview calls e.stopPropagation() before invoking onFullscreen,
   * so the click never bubbles up to the banner-embed-wrapper div — this is the
   * only reliable way to intercept the fullscreen intent from the embed.
   * We ignore the VideoMetadata parameter; the parent (ActiveChat) will re-load
   * the data from the embed store or from the inspiration object.
   */
  function handleVideoEmbedFullscreen() {
    if (!current) return;
    if (onEmbedFullscreen) {
      onEmbedFullscreen(current);
    } else {
      // Fallback: synthesise a mouse event so handleStartChat receives a MouseEvent
      handleStartChat(new MouseEvent('click'));
    }
  }

  /**
   * Send `inspiration_viewed` message to backend via WebSocket.
   * Only sent for authenticated users — guests have no WebSocket connection
   * and there is nothing to track server-side for them.
   * Errors are logged but never swallowed silently.
   */
  async function sendViewedEvent(inspirationId: string) {
    if (!get(authStore).isAuthenticated) return;
    try {
      const { webSocketService } = await import('../services/websocketService');
      await webSocketService.sendMessage('inspiration_viewed', {
        inspiration_id: inspirationId,
      });
      console.debug('[DailyInspirationBanner] Sent inspiration_viewed:', inspirationId);
    } catch (err) {
      console.error('[DailyInspirationBanner] Failed to send inspiration_viewed:', err);
    }
  }
</script>

{#if inspirations.length > 0 && current}
  <!-- Outer wrapper for fade-in animation and full-width layout.
       bind:this lets the IntersectionObserver target this element to detect
       when the banner enters the viewport for passive view tracking. -->
  <div class="daily-inspiration-wrapper" class:crossfading={isCrossfading} bind:this={bannerWrapperEl}>

    <!--
      Banner card: div[role=button] avoids nested-button HTML validation errors
      since carousel arrow <button> elements live inside the card.
      Fixed height of 240px so the embed is never cut off.
    -->
    <div
      class="daily-inspiration-banner"
      data-testid="daily-inspiration-banner"
      style={gradientStyle}
      onclick={handleStartChat}
      onkeydown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); handleStartChat(e as unknown as MouseEvent); } }}
      role="button"
      tabindex="0"
      aria-label={current.phrase}
    >
      <!-- ── Living gradient orbs — same Creative Code technique as ChatHeader.svelte.
           Three soft radial-gradient blobs morph shape and drift behind all content.
           --orb-color-b blooms from each orb center, fading to transparent against
           the --orb-color-a background. Heavy blur + no blend mode = visible color glow.
           Prime durations keep the three orbs permanently out of sync. ── -->
      <div class="banner-orbs" aria-hidden="true">
        <div class="orb orb-1"></div>
        <div class="orb orb-2"></div>
        <div class="orb orb-3"></div>
      </div>

      <!-- ── Large decorative category icons at left and right edges (126×126px, 0.4 opacity).
           These sit outside .banner-inner so they are not constrained by the 680px inner width.
           On smaller viewports they will be partially clipped by overflow:hidden — intentional. ── -->
      {#if CategoryIconComponent}
        <div class="deco-icon deco-icon-left">
          <CategoryIconComponent size={126} color="white" />
        </div>
        <div class="deco-icon deco-icon-right">
          <CategoryIconComponent size={126} color="white" />
        </div>
      {/if}

      <!-- ── Centered inner content wrapper (max-width 680px) ── -->
      <div class="banner-inner">

        <!-- ── Top label ── -->
        <div class="banner-label">
          <BookOpen size={14} color="rgba(255,255,255,0.85)" />
          <span data-testid="daily-inspiration-label">{$text('daily_inspiration.label')}</span>
        </div>

        <!-- ── Main content row: left (mate + text + CTA) + right (embed) ── -->
        <div class="banner-content">

          <!-- Left column: mate profile (left) + phrase (right), CTA pinned to bottom -->
          <div class="banner-left">
            <!-- Row: mate profile image + inspiration phrase side-by-side, vertically centered -->
            <div class="banner-phrase-row">
              <!-- Mate profile image with AI badge (uses global mates.css classes) -->
              <div class="mate-profile banner-mate-profile {current.category}"></div>

              <!-- Inspiration phrase -->
              <p class="banner-phrase">{current.phrase}</p>
            </div>

            <!-- CTA: plain text + create icon — pinned to bottom of banner-left.
                 Shows "Open chat" if user already started a chat from this inspiration,
                 otherwise "Click to start chat". -->
            <div class="banner-cta">
              <span class="clickable-icon icon_create banner-cta-icon"></span>
              <span class="banner-cta-text">
                {current.is_opened && current.opened_chat_id
                  ? $text('daily_inspiration.open_chat')
                  : $text('daily_inspiration.click_to_start_chat')}
              </span>
            </div>
          </div>

          <!-- Right column: VideoEmbedPreview (if video attached).
               Click on this area opens the video fullscreen, NOT a new chat.
               We wrap with a transparent overlay button to capture clicks cleanly
               and prevent the banner's onclick from firing. -->
          {#if hasVideo && embedPreviewId}
            <div
              class="banner-embed-wrapper"
              onclick={handleEmbedClick}
              onkeydown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); handleEmbedClick(e as unknown as MouseEvent); } }}
              role="button"
              tabindex="-1"
              aria-label={$text('daily_inspiration.watch_video')}
            >
              <VideoEmbedPreview
                id={embedPreviewId}
                url={videoUrl}
                title={current.video?.title ?? undefined}
                status="finished"
                channelName={current.video?.channel_name ?? undefined}
                thumbnail={current.video?.thumbnail_url ?? undefined}
                durationSeconds={current.video?.duration_seconds ?? undefined}
                viewCount={current.video?.view_count ?? undefined}
                publishedAt={current.video?.published_at ?? undefined}
                videoId={current.video?.youtube_id}
                isMobile={false}
                onFullscreen={handleVideoEmbedFullscreen}
              />
            </div>
          {/if}
        </div>
      </div><!-- /.banner-inner -->

      <!-- ── Carousel navigation arrows ──
           These are real <button> elements with explicit stopPropagation.
           They are positioned outside .banner-inner so they sit at the edges
           of the full-width card, not constrained by the 680px inner width.
           z-index: 20 ensures they are always on top of the embed wrapper. -->
      {#if hasMultiple}
        <button
          class="carousel-arrow carousel-arrow-left"
          onclick={handlePrevious}
          aria-label={$text('daily_inspiration.previous')}
          type="button"
        >
          <ChevronLeft size={22} color="rgba(255,255,255,0.85)" />
        </button>

        <button
          class="carousel-arrow carousel-arrow-right"
          onclick={handleNext}
          aria-label={$text('daily_inspiration.next')}
          type="button"
        >
          <ChevronRight size={22} color="rgba(255,255,255,0.85)" />
        </button>
      {/if}
    </div><!-- /.daily-inspiration-banner -->
  </div>
{/if}

<style>
  /* ── Wrapper ── */
  .daily-inspiration-wrapper {
    animation: inspirationFadeIn 300ms ease-out;
    width: 100%;
    /* Must be above other chat-side elements so the banner is clickable */
    position: relative;
    z-index: var(--z-index-dropdown);
  }

  @keyframes inspirationFadeIn {
    from { opacity: 0; transform: translateY(8px); }
    to   { opacity: 1; transform: translateY(0);   }
  }

  /* Crossfade transition: when hardcoded data is replaced by real data,
     the banner fades out (200ms), data swaps, then fades back in (300ms). */
  .daily-inspiration-wrapper {
    transition: opacity 300ms ease-in;
  }

  .daily-inspiration-wrapper.crossfading {
    opacity: 0;
    transition: opacity 200ms ease-out;
  }

  /* ── Banner card ──
     Fixed height (240px) so the embed is never cut off.
     position:relative is required for the absolutely-positioned arrows. */
  .daily-inspiration-banner {
    position: relative;
    width: 100%;
    border: none;
    border-radius: var(--radius-6);
    height: 35vh;
    min-height: 240px;
    cursor: pointer;
    overflow: hidden;
    transition: filter 0.15s ease, transform 0.1s ease;
    box-shadow: var(--shadow-xl);
    /* Reset browser button defaults */
    font: inherit;
    color: white;
    display: flex;
    align-items: stretch;
  }

  .daily-inspiration-banner:hover {
    filter: brightness(1.07);
  }

  .daily-inspiration-banner:active {
    transform: scale(0.995);
  }

  /* ── Inner content wrapper: max-width 680px, centered ── */
  .banner-inner {
    width: 100%;
    max-width: 680px;
    margin: 0 auto;
    padding: 14px 40px 12px;  /* 40px sides to leave room for carousel arrows */
    display: flex;
    flex-direction: column;
    gap: var(--spacing-4);
    /* Stretch to fill the full banner height */
    align-self: stretch;
    min-width: 0;
    /* Sit above the decorative deco-icon elements (z-index: 1) */
    position: relative;
    z-index: var(--z-index-dropdown-1);
  }

  /* ── Top label ── */
  .banner-label {
    display: flex;
    align-items: center;
    gap: var(--spacing-3);
    font-size: var(--font-size-xxs);
    font-weight: 500;
    color: rgba(255, 255, 255, 0.85);
    letter-spacing: 0.3px;
    text-transform: uppercase;
    flex-shrink: 0;
  }

  /* ── Main content row ── */
  .banner-content {
    display: flex;
    align-items: stretch;
    gap: 14px;
    flex: 1;
    min-height: 0;
  }

  /* ── Left column ──
     position:relative so CTA can be pinned to the bottom absolutely. */
  .banner-left {
    display: flex;
    flex-direction: column;
    flex: 1;
    min-width: 0;
    position: relative;
    /* Vertical padding to give CTA room at the bottom */
    padding-bottom: 28px;
  }

  /* ── Phrase row: mate profile (left) + phrase (right), vertically centered ── */
  .banner-phrase-row {
    display: flex;
    flex-direction: row;
    align-items: center;
    gap: var(--spacing-6);
    flex: 1;
    min-width: 0;
    /* Vertically center the row within the available column space */
    justify-content: flex-start;
  }

  /* ── Mate profile image ──
     Uses global .mate-profile class from mates.css which provides:
     - 60×60px circle with category background image
     - ::after white circle badge (24px)
     - ::before AI sparkle icon (16px)
     We override to a smaller size to fit the banner layout. */
  .banner-mate-profile {
    /* Override the default 60px size from mates.css for banner context */
    width: 44px !important;
    height: 44px !important;
    margin: 0 !important;
    flex-shrink: 0;
  }

  /* Scale down the AI badge pseudo-elements proportionally */
  .banner-mate-profile::after {
    bottom: -5px !important;
    right: -5px !important;
    width: 18px !important;
    height: 18px !important;
  }

  .banner-mate-profile::before {
    bottom: -3px !important;
    right: -3px !important;
    width: 12px !important;
    height: 12px !important;
  }

  /* ── Inspiration phrase ── */
  .banner-phrase {
    font-size: var(--font-size-p);
    font-weight: 600;
    color: white;
    margin: 0;
    line-height: 1.35;
    /* Clamp to 4 lines to more reliably show the full text */
    display: -webkit-box;
    -webkit-line-clamp: 4;
    line-clamp: 4;
    -webkit-box-orient: vertical;
    overflow: hidden;
    min-width: 0;
  }

  /* ── CTA: plain text + create icon — pinned to bottom of banner-left ── */
  .banner-cta {
    position: absolute;
    bottom: 10px;
    left: 0;
    display: inline-flex;
    align-items: center;
    gap: var(--spacing-3);
    font-size: var(--font-size-xxs);
    font-weight: 500;
    color: rgba(255, 255, 255, 0.85);
    letter-spacing: 0.2px;
    width: fit-content;
  }

  /* create.svg icon — use the same icon class as the "New chat" button.
     The global .icon_create uses a CSS mask + background shorthand.
     We override background (not background-color) so the mask color is applied. */
  .banner-cta-icon {
    background: rgba(255, 255, 255, 0.85) !important;
    width: 13px !important;
    height: 13px !important;
    flex-shrink: 0;
    /* Disable any filter effects from the icon class */
    filter: none !important;
    /* Ensure no cursor override from clickable-icon */
    cursor: default !important;
  }

  .banner-cta-text {
    color: rgba(255, 255, 255, 0.85);
  }

  /* ── Right column: embed preview card ──
     flex: 1 gives it exactly the same width as banner-left (50/50 split).
     margin-top: -15px pulls the embed flush with the top of the banner (past
     the banner-inner top padding) so it fills the full gradient height.
     overflow: visible so the embed card is never clipped.
     align-items: flex-end on .banner-content ensures the embed card aligns right. */
  .banner-embed-wrapper {
    flex: 1;
    min-width: 0;
    align-self: stretch;
    margin-top: -15px;
    margin-bottom: -12px;
    overflow: visible;
    border-radius: var(--radius-4);
    position: relative;
    cursor: pointer;
    /* Right-align the embed content within the wrapper */
    display: flex;
    justify-content: flex-end;
    /* Center embed card vertically so it doesn't pin to the top on tall banners */
    align-items: center;
  }

  /* Make the embed preview card fill the wrapper height and float right.
     Cap at 252px so the card doesn't over-stretch on tall (35vh) banners — at
     240px min-height the cap is never hit; on taller banners the card is
     centered by the parent align-items:center rule above. */
  .banner-embed-wrapper :global(.embed-preview-container) {
    border-radius: var(--radius-4);
    box-shadow: none;
    width: 100%;
    height: min(calc(100% + 15px + 12px), 252px);
    max-width: 220px;
    margin-left: auto; /* push card to the right */
  }

  /* Force the embed to fill the wrapper height */
  .banner-embed-wrapper :global(.unified-embed-preview) {
    height: 100%;
  }

  /* ── Carousel arrows ──
     Full-height invisible touch surfaces (40px wide) at each edge of the
     banner. No visible circle — just a subtle white translucent background
     on hover. Rounded on the inner edge (toward center) only, flush with
     the banner edge on the outer side. Larger icon (22px) for easy tapping.
     ALL global button{} rules from buttons.css are overridden with !important.
  */
  .carousel-arrow {
    position: absolute;
    top: 0;
    bottom: 0;
    /* Reset every property set by the global button{} rule */
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
    pointer-events: auto;
    flex-shrink: 0;
  }

  .carousel-arrow:hover {
    background-color: rgba(255, 255, 255, 0.1) !important;
    scale: none !important;
  }

  .carousel-arrow:active {
    background-color: rgba(255, 255, 255, 0.18) !important;
    scale: none !important;
    filter: none !important;
  }

  /* Position arrows at the outer edges, rounded on the inner edge only */
  .carousel-arrow-left {
    left: 0;
    border-radius: 0 10px 10px 0 !important; /* rounded on the right (inner) side */
  }

  .carousel-arrow-right {
    right: 0;
    border-radius: var(--radius-4) 0 0 10px !important; /* rounded on the left (inner) side */
  }

  /* ── Living gradient orbs ─────────────────────────────────────────────────
     Identical technique to ChatHeader.svelte — see that file for full design
     rationale. CSS custom properties --orb-color-a / --orb-color-b are set
     by the gradientStyle derived value in the script block above. */

  .banner-orbs {
    position: absolute;
    inset: 0;
    z-index: var(--z-index-base);
    pointer-events: none;
    overflow: hidden;
  }

  .orb {
    position: absolute;
    width: 480px;
    height: 420px;
    background: radial-gradient(
      ellipse at center,
      var(--orb-color-b) 0%,
      var(--orb-color-b) 40%,
      transparent 85%
    );
    filter: blur(28px);
    opacity: 0.55;
    will-change: transform, border-radius;
  }

  .orb-1 {
    top: -80px;
    left: -100px;
    animation:
      orbMorph1 11s ease-in-out infinite,
      orbDrift1 19s ease-in-out infinite;
  }

  .orb-2 {
    bottom: -120px;
    right: -120px;
    width: 460px;
    height: 400px;
    animation:
      orbMorph2 13s ease-in-out infinite,
      orbDrift2 23s ease-in-out infinite;
  }

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

  /* Orb morph + drift @keyframes are in animations.css (shared globally). */
  @media (prefers-reduced-motion: reduce) {
    .orb { animation: none !important; }
  }

  /* ── Large decorative icons at banner edges ────────────────────────────────
     Two-phase: decoEnter (one-shot) → decoFloat (16s circular orbit, infinite).
     All @keyframes are in animations.css. CSS vars control the orbit radius and
     base rotation. Right icon starts half a cycle ahead for opposing phase. */
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
    left: calc(50% - 340px - 106px);
    bottom: -15px;
    --deco-rotate: -15deg;
  }

  .deco-icon-right {
    right: calc(50% - 340px - 106px);
    bottom: -15px;
    --deco-rotate: 15deg;
    /* Negative delay: start as if 8s have already elapsed (half-cycle offset).
       Positive delay would freeze the icon for 8.7s then snap — use negative
       to begin mid-orbit immediately with no wait or jump. */
    animation-delay: 0.1s, -8s;
  }

  @media (prefers-reduced-motion: reduce) {
    .deco-icon {
      animation: decoEnter 0.6s ease-out 0.1s both !important;
    }
  }

  /* ── Mobile adjustments (≤730px) ── */
  @media (max-width: 730px) {
    .daily-inspiration-banner {
      height: 190px;
    }

    .banner-inner {
      padding: 12px 38px 10px;
    }

    .banner-phrase {
      font-size: var(--font-size-small);
      -webkit-line-clamp: 4;
      line-clamp: 4;
    }

    .banner-embed-wrapper {
      width: 140px;
    }

    .banner-mate-profile {
      width: 36px !important;
      height: 36px !important;
    }

    .banner-mate-profile::after {
      width: 15px !important;
      height: 15px !important;
      bottom: -4px !important;
      right: -4px !important;
    }

    .banner-mate-profile::before {
      width: 10px !important;
      height: 10px !important;
      bottom: -2px !important;
      right: -2px !important;
    }
  }

  /* Note: embed visibility at narrow widths is handled in JS via the containerWidth prop
     (hasVideo derived value), so no CSS media query is needed here. */
</style>
