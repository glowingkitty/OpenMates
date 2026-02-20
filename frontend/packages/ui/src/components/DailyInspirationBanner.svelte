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
   *   - A YouTube thumbnail + metadata panel (right side, if video attached)
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
   */

  import { onDestroy } from 'svelte';
  import { text } from '@repo/ui';
  import { getLucideIcon, getCategoryGradientColors, getValidIconName } from '../utils/categoryUtils';
  import { dailyInspirationStore, type DailyInspiration } from '../stores/dailyInspirationStore';

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

  /** Array of dot indices for carousel indicator rendering. */
  let dotIndices = $derived(inspirations.map((__, i) => i));

  /** Category icon component for the current inspiration. */
  let CategoryIcon = $derived.by(() => {
    if (!current) return getLucideIcon('help-circle');
    const iconName = getValidIconName([], current.category);
    return getLucideIcon(iconName);
  });

  /** Duration string "M:SS" from seconds, or null if unknown. */
  function formatDuration(seconds: number | null): string | null {
    if (seconds === null || seconds === undefined) return null;
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    return `${m}:${s.toString().padStart(2, '0')}`;
  }

  /** Human-friendly view count (e.g. "1.2M", "345K"). */
  function formatViews(views: number | null): string | null {
    if (views === null || views === undefined) return null;
    if (views >= 1_000_000) return `${(views / 1_000_000).toFixed(1)}M views`;
    if (views >= 1_000) return `${Math.round(views / 1_000)}K views`;
    return `${views} views`;
  }

  // ─── Icon resolution ────────────────────────────────────────────────────────

  // Lucide icons used by the banner
  const BookOpen = getLucideIcon('book-open');
  const ChevronLeft = getLucideIcon('chevron-left');
  const ChevronRight = getLucideIcon('chevron-right');
  const Play = getLucideIcon('play');

  // ─── Event handlers ─────────────────────────────────────────────────────────

  /**
   * Navigate to the previous inspiration in the carousel.
   */
  function handlePrevious(e: MouseEvent) {
    e.stopPropagation();
    dailyInspirationStore.previous();
  }

  /**
   * Navigate to the next inspiration in the carousel.
   */
  function handleNext(e: MouseEvent) {
    e.stopPropagation();
    dailyInspirationStore.next();
  }

  /**
   * Navigate directly to a dot indicator.
   */
  function handleDotClick(e: MouseEvent, index: number) {
    e.stopPropagation();
    dailyInspirationStore.goTo(index);
  }

  /**
   * Handle clicking on the banner or CTA — start a chat from this inspiration.
   * Also marks the inspiration as viewed via WebSocket.
   */
  function handleStartChat(e: MouseEvent) {
    e.stopPropagation();
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
         (carousel arrows and dot buttons live inside the card). -->
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

        <!-- Right column: YouTube thumbnail (if video) -->
        {#if current.video}
          {@const duration = formatDuration(current.video.duration_seconds)}
          {@const views = formatViews(current.video.view_count)}
          <div class="banner-right">
            <div class="video-thumbnail-wrapper">
              <!-- Thumbnail image -->
              {#if current.video.thumbnail_url}
                <img
                  class="video-thumbnail"
                  src={current.video.thumbnail_url}
                  alt={current.video.title}
                  loading="lazy"
                />
              {:else}
                <!-- Fallback placeholder when no thumbnail -->
                <div class="video-thumbnail-placeholder"></div>
              {/if}

              <!-- Play button overlay -->
              <div class="play-overlay" aria-label={$text('daily_inspiration.watch_video')}>
                <div class="play-button-circle">
                  <Play size={18} color="white" />
                </div>
              </div>

              <!-- Duration badge -->
              {#if duration}
                <div class="duration-badge">{duration}</div>
              {/if}
            </div>

            <!-- Video metadata below thumbnail -->
            <div class="video-meta">
              <span class="video-title">{current.video.title}</span>
              {#if views || current.video.channel_name}
                <span class="video-channel">
                  {current.video.channel_name ?? ''}
                  {#if views && current.video.channel_name} · {/if}
                  {views ?? ''}
                </span>
              {/if}
            </div>
          </div>
        {/if}
      </div>

      <!-- ── Carousel navigation ── -->
      {#if hasMultiple}
        <!-- Previous arrow -->
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

        <!-- Dot indicators -->
        <div class="carousel-dots">
          {#each dotIndices as idx}
            <button
              class="dot"
              class:dot-active={idx === currentIndex}
              onclick={(e) => handleDotClick(e, idx)}
              aria-label={`Inspiration ${idx + 1}`}
              type="button"
            ></button>
          {/each}
        </div>
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

  /* ── Right column (video) ── */
  .banner-right {
    display: flex;
    flex-direction: column;
    gap: 6px;
    flex-shrink: 0;
    width: 140px;
  }

  .video-thumbnail-wrapper {
    position: relative;
    width: 140px;
    height: 79px; /* 16:9 */
    border-radius: 8px;
    overflow: hidden;
    background: rgba(0, 0, 0, 0.3);
    flex-shrink: 0;
  }

  .video-thumbnail {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
  }

  .video-thumbnail-placeholder {
    width: 100%;
    height: 100%;
    background: rgba(255, 255, 255, 0.1);
  }

  .play-overlay {
    position: absolute;
    inset: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    background: rgba(0, 0, 0, 0.2);
    transition: background 0.15s ease;
  }

  .daily-inspiration-banner:hover .play-overlay {
    background: rgba(0, 0, 0, 0.3);
  }

  .play-button-circle {
    width: 34px;
    height: 34px;
    border-radius: 50%;
    background: rgba(255, 255, 255, 0.9);
    display: flex;
    align-items: center;
    justify-content: center;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3);
    /* Shift icon slightly right to visually center the play triangle */
    padding-left: 2px;
  }

  .play-button-circle :global(svg) {
    color: #222;
  }

  .duration-badge {
    position: absolute;
    bottom: 4px;
    right: 5px;
    background: rgba(0, 0, 0, 0.75);
    color: white;
    font-size: 10px;
    font-weight: 500;
    padding: 1px 4px;
    border-radius: 3px;
  }

  .video-meta {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  .video-title {
    font-size: 11px;
    font-weight: 500;
    color: rgba(255, 255, 255, 0.95);
    line-height: 1.3;
    /* Clamp to 2 lines */
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }

  .video-channel {
    font-size: 10px;
    color: rgba(255, 255, 255, 0.65);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
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

  /* ── Dot indicators ── */
  .carousel-dots {
    position: absolute;
    bottom: 10px;
    left: 50%;
    transform: translateX(-50%);
    display: flex;
    gap: 5px;
    z-index: 10;
  }

  .dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: rgba(255, 255, 255, 0.45);
    border: none;
    cursor: pointer;
    padding: 0;
    transition: background 0.15s ease, transform 0.15s ease;
  }

  .dot-active {
    background: rgba(255, 255, 255, 0.95);
    transform: scale(1.3);
  }

  /* ── Mobile adjustments ── */
  @media (max-width: 730px) {
    .banner-phrase {
      font-size: 14px;
    }

    .banner-right {
      width: 110px;
    }

    .video-thumbnail-wrapper {
      width: 110px;
      height: 62px;
    }

    .banner-cta {
      font-size: 11px;
      padding: 4px 10px;
    }
  }

  /* Hide video panel on very narrow screens to keep banner readable */
  @media (max-width: 480px) {
    .banner-right {
      display: none;
    }
  }
</style>
