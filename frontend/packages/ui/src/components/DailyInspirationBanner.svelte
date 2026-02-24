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

  import { onDestroy } from 'svelte';
  import { text } from '@repo/ui';
  import { getCategoryGradientColors } from '../utils/categoryUtils';
  import { dailyInspirationStore, type DailyInspiration } from '../stores/dailyInspirationStore';
  import VideoEmbedPreview from './embeds/videos/VideoEmbedPreview.svelte';

  // ─── Lucide icons ────────────────────────────────────────────────────────────

  import { getLucideIcon } from '../utils/categoryUtils';

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

  // Track which inspiration_ids we have already sent a `viewed` WS event for
  let viewedIds = $state(new Set<string>());

  // ─── Subscribe to store ─────────────────────────────────────────────────────

  const unsubscribe = dailyInspirationStore.subscribe((state) => {
    inspirations = state.inspirations;
    currentIndex = state.currentIndex;
  });

  onDestroy(unsubscribe);

  // ─── Derived values ─────────────────────────────────────────────────────────

  /** Currently displayed inspiration. */
  let current = $derived(inspirations[currentIndex] ?? null);

  /** Background gradient style string for the current card. */
  let gradientStyle = $derived.by(() => {
    if (!current) return '';
    const colors = getCategoryGradientColors(current.category);
    if (!colors) return 'background: linear-gradient(135deg, #1a237e, #3949ab)';
    return `background: linear-gradient(135deg, ${colors.start}, ${colors.end})`;
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
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
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
   * Send `inspiration_viewed` message to backend via WebSocket.
   * Errors are logged but never swallowed silently.
   */
  async function sendViewedEvent(inspirationId: string) {
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
  <!-- Outer wrapper for fade-in animation and full-width layout -->
  <div class="daily-inspiration-wrapper">

    <!--
      Banner card: div[role=button] avoids nested-button HTML validation errors
      since carousel arrow <button> elements live inside the card.
      Fixed height of 240px so the embed is never cut off.
    -->
    <div
      class="daily-inspiration-banner"
      style={gradientStyle}
      onclick={handleStartChat}
      onkeydown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); handleStartChat(e as unknown as MouseEvent); } }}
      role="button"
      tabindex="0"
      aria-label={current.phrase}
    >
      <!-- ── Centered inner content wrapper (max-width 680px) ── -->
      <div class="banner-inner">

        <!-- ── Top label ── -->
        <div class="banner-label">
          <BookOpen size={14} color="rgba(255,255,255,0.85)" />
          <span>{$text('daily_inspiration.label')}</span>
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
    z-index: 100;
  }

  @keyframes inspirationFadeIn {
    from { opacity: 0; transform: translateY(8px); }
    to   { opacity: 1; transform: translateY(0);   }
  }

  /* ── Banner card ──
     Fixed height (240px) so the embed is never cut off.
     position:relative is required for the absolutely-positioned arrows. */
  .daily-inspiration-banner {
    position: relative;
    width: 100%;
    border: none;
    border-radius: 14px;
    height: 240px;
    cursor: pointer;
    overflow: hidden;
    transition: filter 0.15s ease, transform 0.1s ease;
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.25);
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
    gap: 8px;
    /* Stretch to fill the full banner height */
    align-self: stretch;
    min-width: 0;
  }

  /* ── Top label ── */
  .banner-label {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 12px;
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
    gap: 12px;
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
    font-size: 16px;
    font-weight: 600;
    color: white;
    margin: 0;
    line-height: 1.35;
    /* Clamp to 3 lines to keep card compact */
    display: -webkit-box;
    -webkit-line-clamp: 3;
    line-clamp: 3;
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
    gap: 6px;
    font-size: 12px;
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
    border-radius: 10px;
    position: relative;
    cursor: pointer;
    /* Right-align the embed content within the wrapper */
    display: flex;
    justify-content: flex-end;
  }

  /* Make the embed preview card fill the wrapper height and float right */
  .banner-embed-wrapper :global(.embed-preview-container) {
    border-radius: 10px;
    box-shadow: none;
    width: 100%;
    height: calc(100% + 15px + 12px); /* compensate for negative margins */
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
    transition: background-color 0.15s ease;
    z-index: 20;
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
    border-radius: 10px 0 0 10px !important; /* rounded on the left (inner) side */
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
      font-size: 14px;
      -webkit-line-clamp: 2;
      line-clamp: 2;
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
