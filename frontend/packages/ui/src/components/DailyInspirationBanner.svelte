<script lang="ts">
  /**
   * DailyInspirationBanner.svelte
   *
   * Displays up to 3 daily inspiration banners in a carousel at the top of the
   * new chat screen (welcome screen). Each banner shows:
   *   - A gradient background (category colour from getCategoryGradientColors)
   *   - A "Daily inspiration" label with a BookOpen icon (top-left)
   *   - A category circle with the category icon (left side)
   *   - The inspiration phrase (main text)
   *   - A "Click to start chat" CTA button (bottom-left)
   *   - A VideoEmbedPreview card (right side, if video or embed_id attached)
   *   - Left/right carousel arrows when there are multiple inspirations
   *
   * Clicking the banner or the CTA button:
   *   - Creates a local-only chat (no LLM request yet) with the phrase as the
   *     title and a first assistant message containing the phrase
   *   - Navigates to the newly created chat
   *   - Dispatches an `inspiration_viewed` message to the server via WebSocket
   *     so the backend can track engagement
   *
   * Visibility: shown when the parent passes `showWelcome && !hideWelcomeForKeyboard`.
   * The component self-hides when the store has no inspirations.
   *
   * Architecture note: The store (dailyInspirationStore) is a Svelte 4 writable.
   * This component uses Svelte 5 runes exclusively for its own state.
   *
   * Video display: Uses VideoEmbedPreview for consistent embed card rendering.
   * When a video is available (inspiration.video != null), it renders the full
   * VideoEmbedPreview. When video is null but embed_id is set, we attempt to
   * load it from embedStore so the embed survives page reloads.
   */

  import { onDestroy } from 'svelte';
  import { text } from '@repo/ui';
  import { getLucideIcon, getCategoryGradientColors, getValidIconName } from '../utils/categoryUtils';
  import { dailyInspirationStore, type DailyInspiration } from '../stores/dailyInspirationStore';
  import VideoEmbedPreview from './embeds/videos/VideoEmbedPreview.svelte';

  // ─── Component props ────────────────────────────────────────────────────────

  interface Props {
    /** Called when the user clicks a banner to start a chat from this inspiration. */
    onStartChat: (inspiration: DailyInspiration) => void;
  }

  let { onStartChat }: Props = $props();

  // ─── Local state (Svelte 5 runes) ──────────────────────────────────────────

  // Mirror of the store – updated via subscription below
  let inspirations = $state<DailyInspiration[]>([]);
  let currentIndex = $state(0);

  // Track which inspiration_ids we have already sent a `viewed` WS event for
  // so we don't spam the server on every re-render.
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

  /** Category circle gradient (same as resume-chat card, slightly darker). */
  let circleStyle = $derived.by(() => {
    if (!current) return '';
    const colors = getCategoryGradientColors(current.category);
    if (!colors) return 'background: rgba(255,255,255,0.2)';
    return `background: linear-gradient(135deg, ${colors.start}aa, ${colors.end}aa)`;
  });

  /** Whether multiple inspirations are available (show arrows). */
  let hasMultiple = $derived(inspirations.length > 1);

  /** Category icon component for the current inspiration. */
  let CategoryIcon = $derived.by(() => {
    if (!current) return getLucideIcon('help-circle');
    const iconName = getValidIconName([], current.category);
    return getLucideIcon(iconName);
  });

  /**
   * Whether to show a video embed for the current inspiration.
   * True when a video object is present (has a youtube_id).
   */
  let hasVideo = $derived(!!current?.video?.youtube_id);

  /**
   * The embed_id to use for VideoEmbedPreview.
   * Uses embed_id from the inspiration if already stored, otherwise generates a
   * deterministic one from the youtube_id for preview purposes.
   */
  let embedPreviewId = $derived.by(() => {
    if (!current) return '';
    if (current.embed_id) return current.embed_id;
    // Use youtube_id as a stable fallback ID for display (non-persisted)
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

  // ─── Icon resolution ────────────────────────────────────────────────────────

  // Lucide icons used by the banner
  const BookOpen = getLucideIcon('book-open');
  const ChevronLeft = getLucideIcon('chevron-left');
  const ChevronRight = getLucideIcon('chevron-right');

  // ─── Event handlers ─────────────────────────────────────────────────────────

  /**
   * Navigate to the previous inspiration in the carousel.
   */
  function handlePrevious(e: MouseEvent) {
    e.stopPropagation();
    e.preventDefault();
    dailyInspirationStore.previous();
  }

  /**
   * Navigate to the next inspiration in the carousel.
   */
  function handleNext(e: MouseEvent) {
    e.stopPropagation();
    e.preventDefault();
    dailyInspirationStore.next();
  }

  /**
   * Handle clicking on the banner or CTA — start a chat from this inspiration.
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
  <!-- Outer wrapper for fade-in animation -->
  <div class="daily-inspiration-wrapper">

    <!-- Banner card: div with role=button avoids nested-button HTML validation errors
         (carousel arrows live inside the card). -->
    <div
      class="daily-inspiration-banner"
      style={gradientStyle}
      onclick={handleStartChat}
      onkeydown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); handleStartChat(e as unknown as MouseEvent); } }}
      role="button"
      tabindex="0"
      aria-label={current.phrase}
    >
      <!-- ── Top label ── -->
      <div class="banner-label">
        <BookOpen size={14} color="rgba(255,255,255,0.85)" />
        <span>{$text('daily_inspiration.label')}</span>
      </div>

      <!-- ── Main content row ── -->
      <div class="banner-content">

        <!-- Left column: category icon + text + CTA -->
        <div class="banner-left">
          <!-- Category icon circle (icon resolved as $derived in script) -->
          <div class="category-circle" style={circleStyle}>
            <CategoryIcon size={20} color="white" />
          </div>

          <!-- Inspiration phrase -->
          <p class="banner-phrase">{current.phrase}</p>

          <!-- CTA button -->
          <div class="banner-cta">
            <span>{$text('daily_inspiration.click_to_start_chat')}</span>
          </div>
        </div>

        <!-- Right column: VideoEmbedPreview (if video attached) -->
        {#if hasVideo && embedPreviewId}
          <!-- Wrapper stops click events from reaching the banner (embed has its own click handlers) -->
          <!-- svelte-ignore a11y_click_events_have_key_events -->
          <!-- svelte-ignore a11y_no_static_element_interactions -->
          <div
            class="banner-embed-wrapper"
            onclick={(e) => {
              // Prevent the banner's handleStartChat from firing when clicking the embed area;
              // the user intention is to view the video, not start a new chat immediately.
              e.stopPropagation();
              // Then actually start the chat (opening the embed belongs in the chat view)
              handleStartChat(e);
            }}
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

      <!-- ── Carousel navigation ── -->
      {#if hasMultiple}
        <!-- Previous arrow — stopPropagation prevents the banner's onclick from firing -->
        <button
          class="carousel-arrow carousel-arrow-left"
          onclick={handlePrevious}
          aria-label={$text('daily_inspiration.previous')}
          type="button"
        >
          <ChevronLeft size={18} color="rgba(255,255,255,0.9)" />
        </button>

        <!-- Next arrow -->
        <button
          class="carousel-arrow carousel-arrow-right"
          onclick={handleNext}
          aria-label={$text('daily_inspiration.next')}
          type="button"
        >
          <ChevronRight size={18} color="rgba(255,255,255,0.9)" />
        </button>
      {/if}
    </div>
  </div>
{/if}

<style>
  /* ── Wrapper ── */
  .daily-inspiration-wrapper {
    animation: inspirationFadeIn 300ms ease-out;
    margin-bottom: 8px;
  }

  @keyframes inspirationFadeIn {
    from { opacity: 0; transform: translateY(8px); }
    to   { opacity: 1; transform: translateY(0);   }
  }

  /* ── Banner card (full-width button) ── */
  .daily-inspiration-banner {
    position: relative;
    width: 100%;
    border: none;
    border-radius: 14px;
    padding: 14px 16px 12px;
    cursor: pointer;
    text-align: left;
    overflow: hidden;
    transition: filter 0.15s ease, transform 0.1s ease;
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.25);
    min-height: 120px;
    display: flex;
    flex-direction: column;
    gap: 10px;
    /* Reset browser button defaults */
    font: inherit;
    color: white;
  }

  .daily-inspiration-banner:hover {
    filter: brightness(1.07);
  }

  .daily-inspiration-banner:active {
    transform: scale(0.995);
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
  }

  /* ── Main content row ── */
  .banner-content {
    display: flex;
    align-items: flex-start;
    gap: 14px;
    flex: 1;
  }

  /* ── Left column ── */
  .banner-left {
    display: flex;
    flex-direction: column;
    gap: 8px;
    flex: 1;
    min-width: 0;
  }

  .category-circle {
    width: 38px;
    height: 38px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    border: 1.5px solid rgba(255, 255, 255, 0.3);
  }

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
  }

  .banner-cta {
    display: inline-flex;
    align-items: center;
    padding: 5px 12px;
    background: rgba(255, 255, 255, 0.2);
    border-radius: 20px;
    border: 1px solid rgba(255, 255, 255, 0.3);
    font-size: 12px;
    font-weight: 500;
    color: rgba(255, 255, 255, 0.95);
    letter-spacing: 0.2px;
    width: fit-content;
    transition: background 0.15s ease;
  }

  .daily-inspiration-banner:hover .banner-cta {
    background: rgba(255, 255, 255, 0.28);
  }

  /* ── Right column: embed preview card ── */
  .banner-embed-wrapper {
    flex-shrink: 0;
    /* Scale down the embed preview to fit inside the banner */
    /* Default embed size is 300×200px; we want ~160px wide in the banner */
    width: 160px;
    /* Constrain height so it doesn't overflow the banner */
    max-height: 130px;
    overflow: hidden;
    border-radius: 10px;
    /* Slightly reduce the overall embed scale to keep it compact */
    transform: scale(0.88);
    transform-origin: top right;
    /* Counteract the scale reducing effective width */
    margin-right: -10px;
    /* Pointer events pass through so the banner onclick fires */
    pointer-events: auto;
  }

  /* Override the embed preview rounded corners to match our wrapper */
  .banner-embed-wrapper :global(.embed-preview-container) {
    border-radius: 10px;
    box-shadow: none;
  }

  /* ── Carousel arrows ── */
  .carousel-arrow {
    position: absolute;
    top: 50%;
    transform: translateY(-50%);
    background: rgba(0, 0, 0, 0.25);
    border: none;
    border-radius: 50%;
    width: 28px;
    height: 28px;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    padding: 0;
    transition: background 0.15s ease;
    z-index: 10;
  }

  .carousel-arrow:hover {
    background: rgba(0, 0, 0, 0.4);
  }

  .carousel-arrow-left {
    left: 8px;
  }

  .carousel-arrow-right {
    right: 8px;
  }

  /* ── Mobile adjustments ── */
  @media (max-width: 730px) {
    .banner-phrase {
      font-size: 14px;
    }

    .banner-embed-wrapper {
      width: 130px;
      max-height: 110px;
      transform: scale(0.75);
      transform-origin: top right;
      margin-right: -20px;
    }

    .banner-cta {
      font-size: 11px;
      padding: 4px 10px;
    }
  }

  /* Hide embed panel on very narrow screens to keep banner readable */
  @media (max-width: 480px) {
    .banner-embed-wrapper {
      display: none;
    }
  }
</style>
