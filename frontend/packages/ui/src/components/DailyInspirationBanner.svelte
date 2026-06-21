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
   *   - Left/right arrow buttons or horizontal touch swipes → navigate the carousel
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
  import { CATEGORY_GRADIENTS, getCategoryGradientColors } from '../utils/categoryUtils';
  import { dailyInspirationStore, type DailyInspiration, type DailyInspirationSurface } from '../stores/dailyInspirationStore';
  import { loadDefaultInspirations } from '../demo_chats/loadDefaultInspirations';
  import { authStore } from '../stores/authStore';
  import { proxyImage, MAX_WIDTH_PREVIEW_THUMBNAIL } from '../utils/imageProxy';
  import VideoEmbedPreview from './embeds/videos/VideoEmbedPreview.svelte';
  import DirectVideoEmbedFullscreen from './embeds/videos/DirectVideoEmbedFullscreen.svelte';
  import WikipediaEmbedPreview from './embeds/wiki/WikipediaEmbedPreview.svelte';

  // ─── Lucide icons ────────────────────────────────────────────────────────────

  import { getLucideIcon, getValidIconName } from '../utils/categoryUtils';

  const BookOpen = getLucideIcon('book-open');
  const LinkIcon = getLucideIcon('link');
  const ChevronLeft = getLucideIcon('chevron-left');
  const ChevronRight = getLucideIcon('chevron-right');

  const MOBILE_CARD_ROTATION_INTERVAL_MS = 5000;
  const INSPIRATION_AUTO_ROTATION_INTERVAL_MS = 20000;
  const TOUCH_SWIPE_DISTANCE_PX = 56;
  const TOUCH_SWIPE_VERTICAL_CANCEL_PX = 48;
  // Temporarily disabled with the visit-cycling effect below.
  // const VISIT_INDEX_STORAGE_PREFIX = 'openmates.daily_inspiration.visit_index.';
  const AUTHENTICATED_ONLY_FEATURE_IDS = new Set([
    'export-data',
    'incognito-mode',
  ]);
  const GUEST_ALLOWED_FEATURE_PATHS = new Set([
    'apps/all/focus_modes',
    'apps/events/skill/search',
    'apps/all/skills',
    'privacy',
    'privacy/hide-personal-data',
    'settings_memories',
  ]);

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
    /** Which workspace surface this banner is rendered in. Legacy items default to chats. */
    surface?: DailyInspirationSurface;
    /** Visual treatment. Guest intro keeps carousel behavior with ChatHeader-like split media. */
    variant?: 'default' | 'guest-intro';
  }

  let { onStartChat, onEmbedFullscreen, containerWidth = 0, surface = 'chats', variant = 'default' }: Props = $props();
  let isGuestIntroVariant = $derived(variant === 'guest-intro');

  // ─── Local state (Svelte 5 runes) ──────────────────────────────────────────

  // Mirror of the store – updated via subscription below
  let inspirations = $state<DailyInspiration[]>([]);
  let currentIndex = $state(0);
  let isAuthenticated = $state(false);

  // Track which inspiration_ids we have already sent a `viewed` WS event for.
  // An entry is added as soon as the banner is visible in the viewport AND the
  // inspiration is the currently displayed carousel slide — this ensures each
  // unique inspiration is counted toward tomorrow's replacement quota even if
  // the user never clicks it (passive view tracking).
  let viewedIds = $state(new Set<string>());

  // Whether the banner wrapper is currently intersecting the viewport. Default
  // to true so Safari/blocked IntersectionObserver does not stall the carousel.
  let isBannerVisible = $state(true);

  // On mobile, alternate between the assistant message and interactive preview instead
  // of squeezing both into the narrow banner width.
  let showMobileCard = $state(false);

  // Touch gesture state for mobile carousel swipes.
  let touchStartX = $state(0);
  let touchStartY = $state(0);
  let touchSwipeHandled = $state(false);
  let suppressNextClick = $state(false);
  let prefersTouchCta = $state(false);
  let isUserInteracting = $state(false);
  let isOpeningInspiration = $state(false);
  let directVideoFullscreenOpen = $state(false);
  let progressRestartToken = $state(0);
  // Temporarily disabled with the visit-cycling effect below.
  // let visitCycleTargetIndexes = $state(new Map<string, number>());
  // let visitCycleAppliedInspirations = $state<DailyInspiration[] | null>(null);
  let manuallyNavigatedSetKeys = $state(new Set<string>());

  // Reference to the outer wrapper element — used as the IntersectionObserver target.
  let bannerWrapperEl = $state<HTMLElement | null>(null);

  // ─── Crossfade when data source changes ─────────────────────────────────────
  // When hardcoded inspirations are replaced by real data (IndexedDB / server /
  // WS), the banner crossfades: the old content fades out, then the new content
  // fades in. This avoids a jarring instant swap.
  const HARDCODED_ID_PREFIX = "hardcoded-";
  let isCrossfading = $state(false);

  // ─── Subscribe to store ─────────────────────────────────────────────────────

  const unsubscribeDailyInspirations = dailyInspirationStore.subscribe((state) => {
    const wasHardcoded = inspirations.length > 0 &&
      inspirations.every((i) => i.inspiration_id.startsWith(HARDCODED_ID_PREFIX));
    const isNowReal = state.inspirations.length > 0 &&
      !state.inspirations.every((i) => i.inspiration_id.startsWith(HARDCODED_ID_PREFIX));

    const previousVisibleInspirations = surfaceInspirations(inspirations).filter((inspiration) =>
      isDailyInspirationVisible(inspiration),
    );
    const nextSurfaceInspirations = surfaceInspirations(state.inspirations);
    const nextVisibleInspirations = nextSurfaceInspirations.filter((inspiration) =>
      isDailyInspirationVisible(inspiration),
    );
    const isSameVisibleSet = hasSameVisibleInspirationIds(previousVisibleInspirations, nextVisibleInspirations);

    if (wasHardcoded && isNowReal) {
      // Trigger crossfade: fade out, swap data, fade in
      isCrossfading = true;
      setTimeout(() => {
        inspirations = state.inspirations;
        if (!isSameVisibleSet) {
          currentIndex = getVisibleIndexForStoreIndex(nextSurfaceInspirations, state.currentIndex);
        }
        // Allow a frame for the DOM to update with new data before fading in
        requestAnimationFrame(() => {
          isCrossfading = false;
        });
      }, 200); // Match the CSS fade-out duration
    } else {
      inspirations = state.inspirations;
      if (!isSameVisibleSet) {
        currentIndex = getVisibleIndexForStoreIndex(nextSurfaceInspirations, state.currentIndex);
      }
    }
  });

  const unsubscribeAuth = authStore.subscribe((state) => {
    isAuthenticated = state.isAuthenticated;
  });

  onDestroy(() => {
    unsubscribeDailyInspirations();
    unsubscribeAuth();
  });

  // ─── Reload inspirations on language change ─────────────────────────────────
  // Default (non-personalized) inspirations are fetched from the server with a
  // lang parameter. When the user switches language, we clear the store and
  // re-fetch so the inspiration phrases match the new locale.
  // Personalized inspirations (from WS/IndexedDB) are AI-generated content in the
  // user's language at creation time — they cannot be retranslated, so we skip.
  onMount(() => {
    const pointerQuery = window.matchMedia('(pointer: coarse)');
    const updatePointerCta = () => {
      prefersTouchCta = pointerQuery.matches || navigator.maxTouchPoints > 0;
    };
    updatePointerCta();
    pointerQuery.addEventListener('change', updatePointerCta);

    const handleLanguageChange = () => {
      const state = get(dailyInspirationStore);
      if (!state.isPersonalized) {
        dailyInspirationStore.reset();
        loadDefaultInspirations({ allowIndexedDB: false, surface }).catch((err) => {
          console.error('[DailyInspirationBanner] Failed to reload inspirations after language change:', err);
        });
      }
    };
    // Use 'language-changed-complete' (fires 50ms after locale.set + waitLocale)
    // to ensure the svelte-i18n locale store is fully settled before re-fetching.
    window.addEventListener('language-changed-complete', handleLanguageChange);

    return () => {
      pointerQuery.removeEventListener('change', updatePointerCta);
      window.removeEventListener('language-changed-complete', handleLanguageChange);
    };
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
    if (typeof IntersectionObserver === 'undefined') {
      isBannerVisible = true;
      return;
    }
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

  // Mobile card loop: start on the assistant message, then alternate message and preview.
  $effect(() => {
    if (!shouldCycleMobileCard) {
      showMobileCard = false;
      return;
    }

    void currentIndex;
    void mobilePreviewKey;
    showMobileCard = false;

    const interval = window.setInterval(() => {
      showMobileCard = !showMobileCard;
    }, MOBILE_CARD_ROTATION_INTERVAL_MS);

    return () => window.clearInterval(interval);
  });

  // ─── Derived values ─────────────────────────────────────────────────────────

  let visibleInspirations = $derived.by(() => (
    surfaceInspirations(inspirations).filter((inspiration) => isDailyInspirationVisible(inspiration))
  ));

  /** Currently displayed inspiration. */
  let current = $derived.by(() => {
    if (visibleInspirations.length === 0) return null;
    return visibleInspirations[currentIndex % visibleInspirations.length] ?? null;
  });

  /** Valid mate/category class to render. Public cached wiki cards may contain old unsupported categories. */
  let displayCategory = $derived.by(() => {
    if (!current) return 'general_knowledge';
    return current.category in CATEGORY_GRADIENTS ? current.category : 'general_knowledge';
  });

  /** Background gradient style string for the current card.
   *  Also emits --orb-color-a (start/outer) and --orb-color-b (end/inner) as
   *  CSS custom properties consumed by the living gradient orb animation — same
   *  technique as ChatHeader.svelte. */
  let gradientStyle = $derived.by(() => {
    if (!current) return '';
    const colors = getCategoryGradientColors(displayCategory);
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
  let hasMultiple = $derived(visibleInspirations.length > 1);

  $effect(() => {
    if (visibleInspirations.length === 0) {
      currentIndex = 0;
      return;
    }
    if (currentIndex >= visibleInspirations.length) {
      currentIndex = 0;
    }
  });

  /** Stable key for the currently loaded inspiration set, used for visit-time cycling. */
  let inspirationSetKey = $derived.by(() => getInspirationSetKey(visibleInspirations));

  // Temporarily disabled for live regression testing: this effect both depends on
  // and writes carousel state, and is a likely source of Svelte effect-depth loops.
  // $effect(() => {
  //   if (visibleInspirations.length <= 1) return;
  //   if (!inspirationSetKey) return;
  //   if (manuallyNavigatedSetKeys.has(inspirationSetKey)) return;
  //   if (visitCycleAppliedInspirations === visibleInspirations) return;
  //
  //   let targetIndex = visitCycleTargetIndexes.get(inspirationSetKey);
  //   if (targetIndex === undefined || targetIndex >= visibleInspirations.length) {
  //     targetIndex = getNextVisitIndex(inspirationSetKey, visibleInspirations.length);
  //     visitCycleTargetIndexes = new Map([
  //       ...visitCycleTargetIndexes,
  //       [inspirationSetKey, targetIndex],
  //     ]);
  //   }
  //
  //   visitCycleAppliedInspirations = visibleInspirations;
  //   if (currentIndex !== targetIndex) {
  //     currentIndex = targetIndex;
  //   }
  // });

  /**
   * Whether to show a video embed for the current inspiration.
   * True when a video object is present (has a youtube_id) AND there is enough
   * horizontal space in the container to display both the text and the embed
   * side-by-side without squeezing either.  We require at least 520px: ~220px
   * for the embed card, ~200px for the text, plus padding/gap overhead.
   * When containerWidth is 0 (unknown) we default to hiding the embed to avoid
   * a layout flash.
   */
  let hasAttachedVideo = $derived(!!current?.video?.youtube_id);
  let hasInfoContent = $derived(current?.content_type === 'wiki' || current?.content_type === 'feature');
  let hasWikiContent = $derived(current?.content_type === 'wiki' && !!current.wiki);
  let isFeatureInspiration = $derived(current?.content_type === 'feature');

  /** Whether the banner is rendered in the narrow mobile layout. */
  let isMobileBannerLayout = $derived(containerWidth > 0 && containerWidth <= 730);

  /** Whether mobile should alternate between the assistant message and embed. */
  let shouldCycleMobileCard = $derived(!isGuestIntroVariant && (hasAttachedVideo || hasInfoContent) && isMobileBannerLayout);

  let hasVideo = $derived(hasAttachedVideo && (containerWidth >= 520 || shouldCycleMobileCard));

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
    const iconName = getValidIconName('', displayCategory);
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
  let directVideoMp4Url = $derived(current?.direct_video?.mp4_url ?? '');
  let directVideoTeaserUrl = $derived(current?.direct_video?.teaser_url ?? '');
  let directVideoTeaserMp4Url = $derived(current?.direct_video?.teaser_mp4_url ?? '');
  let directVideoPosterUrl = $derived(
    current?.direct_video?.teaser_webp_url
      || (current?.direct_video?.thumbnail_url
        ? proxyImage(current.direct_video.thumbnail_url, MAX_WIDTH_PREVIEW_THUMBNAIL)
        : ''),
  );

  let infoCardTitle = $derived(current?.wiki?.title || current?.feature?.title || current?.title || '');
  let infoCardSubtitle = $derived(current?.wiki?.description || current?.feature?.description || '');
  let infoCardImage = $derived(
    current?.wiki?.thumbnail_url
      ? proxyImage(current.wiki.thumbnail_url, MAX_WIDTH_PREVIEW_THUMBNAIL)
      : current?.direct_video?.thumbnail_url
        ? proxyImage(current.direct_video.thumbnail_url, MAX_WIDTH_PREVIEW_THUMBNAIL)
        : ''
  );
  let hasInfoCard = $derived(!isGuestIntroVariant && !hasVideo && hasInfoContent && !hasWikiContent);
  let mobilePreviewKey = $derived(embedPreviewId || infoCardTitle || current?.inspiration_id || '');
  let progressAnimationKey = $derived(`${current?.inspiration_id ?? 'none'}-${currentIndex}-${progressRestartToken}`);
  let InfoCardIconComponent = $derived.by(() => {
    if (!current) return null;
    if (current.content_type === 'wiki') return getLucideIcon('book-open');
    if (current.feature?.icon) return getLucideIcon(current.feature.icon);
    return CategoryIconComponent;
  });

  // ─── Event handlers ─────────────────────────────────────────────────────────

  /**
   * Navigate to the previous inspiration in the carousel.
   * stopPropagation prevents the banner's onclick from firing.
   */
  function handlePrevious(e: MouseEvent) {
    e.stopPropagation();
    e.preventDefault();
    markManualNavigation();
    resumeAutoRotation();
    goToVisibleIndex(currentIndex - 1);
    restartProgressAnimation();
  }

  /**
   * Navigate to the next inspiration in the carousel.
   * stopPropagation prevents the banner's onclick from firing.
   */
  function handleNext(e: MouseEvent) {
    e.stopPropagation();
    e.preventDefault();
    markManualNavigation();
    resumeAutoRotation();
    goToVisibleIndex(currentIndex + 1);
    restartProgressAnimation();
  }

  function handleTouchStart(e: TouchEvent) {
    if (!hasMultiple || e.touches.length !== 1) return;

    isUserInteracting = true;
    const touch = e.touches[0];
    touchStartX = touch.clientX;
    touchStartY = touch.clientY;
    touchSwipeHandled = false;
  }

  function handleTouchMove(e: TouchEvent) {
    if (!hasMultiple || touchSwipeHandled || e.touches.length !== 1) return;

    const touch = e.touches[0];
    const deltaX = touch.clientX - touchStartX;
    const deltaY = touch.clientY - touchStartY;
    const absDeltaY = Math.abs(deltaY);
    const isMostlyHorizontal = Math.abs(deltaX) > absDeltaY * 1.2;

    if (absDeltaY > TOUCH_SWIPE_VERTICAL_CANCEL_PX && !isMostlyHorizontal) {
      touchSwipeHandled = true;
      return;
    }

    if (!isMostlyHorizontal || Math.abs(deltaX) < TOUCH_SWIPE_DISTANCE_PX) return;

    e.preventDefault();
    touchSwipeHandled = true;
    suppressNextClick = true;
    markManualNavigation();

    if (deltaX < 0) {
      resumeAutoRotation();
      goToVisibleIndex(currentIndex + 1);
    } else {
      resumeAutoRotation();
      goToVisibleIndex(currentIndex - 1);
    }
  }

  function markManualNavigation() {
    if (!inspirationSetKey) return;
    manuallyNavigatedSetKeys = new Set([
      ...manuallyNavigatedSetKeys,
      inspirationSetKey,
    ]);
  }

  function handleTouchEnd() {
    touchStartX = 0;
    touchStartY = 0;
    touchSwipeHandled = false;
    isUserInteracting = false;
    restartProgressAnimation();

    if (suppressNextClick) {
      window.setTimeout(() => {
        suppressNextClick = false;
      }, 400);
    }
  }

  /**
   * Handle clicking on the banner body — start a chat from this inspiration.
   * Also marks the inspiration as viewed via WebSocket.
   */
  function handleStartChat(e: MouseEvent) {
    const sourceCapabilities = (e as MouseEvent & {
      sourceCapabilities?: { firesTouchEvents?: boolean } | null;
    }).sourceCapabilities;
    if (suppressNextClick && sourceCapabilities?.firesTouchEvents === true) {
      e.stopPropagation();
      e.preventDefault();
      suppressNextClick = false;
      return;
    }

    if (!current) return;
    isOpeningInspiration = true;

    // Send viewed event if not already sent
    if (!viewedIds.has(current.inspiration_id)) {
      viewedIds = new Set([...viewedIds, current.inspiration_id]);
      sendViewedEvent(current.inspiration_id);
    }

    onStartChat(current);
  }

  function handleBannerPointerDown(e: PointerEvent) {
    if (e.pointerType === 'touch') return;
    const target = e.target instanceof Element ? e.target : null;
    if (target?.closest('.carousel-arrow, .banner-embed-wrapper')) return;
    isOpeningInspiration = true;
  }

  function resumeAutoRotation() {
    isOpeningInspiration = false;
    isUserInteracting = false;
  }

  function restartProgressAnimation() {
    progressRestartToken += 1;
  }

  function handleProgressAnimationEnd(e: AnimationEvent) {
    if (e.target !== e.currentTarget) return;
    if (!isBannerVisible || visibleInspirations.length <= 1) return;
    if (isUserInteracting || isOpeningInspiration) return;
    goToVisibleIndex(currentIndex + 1);
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

  function handleDirectVideoClick(e: MouseEvent | KeyboardEvent) {
    if (!directVideoMp4Url) return;
    e.stopPropagation();
    e.preventDefault();
    directVideoFullscreenOpen = true;
  }

  function handleInfoCardClick(e: MouseEvent | KeyboardEvent) {
    if (!current?.wiki) return;
    e.stopPropagation();
    e.preventDefault();

    const wikiTitle = current.wiki.wiki_title || current.wiki.title;
    document.dispatchEvent(
      new CustomEvent('wikifullscreen', {
        detail: {
          wikiTitle,
          wikidataId: current.wiki.wikidata_id,
          displayText: current.wiki.title || wikiTitle,
          thumbnailUrl: current.wiki.thumbnail_url,
          description: current.wiki.description,
        },
        bubbles: true,
      }),
    );
  }

  function getInspirationSetKey(items: DailyInspiration[]): string {
    if (items.length === 0) return '';
    return hashString(items.map((item) => item.inspiration_id).join('|'));
  }

  function getVisibleIndexForStoreIndex(items: DailyInspiration[], storeIndex: number): number {
    const storeItem = items[storeIndex];
    const visibleItems = items.filter((inspiration) => isDailyInspirationVisible(inspiration));
    if (visibleItems.length === 0) return 0;
    if (!storeItem) return 0;

    const visibleIndex = visibleItems.findIndex(
      (inspiration) => inspiration.inspiration_id === storeItem.inspiration_id,
    );
    return visibleIndex >= 0 ? visibleIndex : 0;
  }

  function hasSameVisibleInspirationIds(
    previous: DailyInspiration[],
    next: DailyInspiration[],
  ): boolean {
    if (previous.length !== next.length) return false;
    return previous.every(
      (inspiration, index) => inspiration.inspiration_id === next[index]?.inspiration_id,
    );
  }

  function goToVisibleIndex(nextIndex: number): void {
    if (visibleInspirations.length === 0) {
      currentIndex = 0;
      return;
    }
    currentIndex = (nextIndex + visibleInspirations.length) % visibleInspirations.length;
  }

  // Temporarily disabled with the visit-cycling effect above.
  // function getNextVisitIndex(setKey: string, count: number): number {
  //   if (typeof window === 'undefined' || count <= 1) return 0;
  //
  //   const storageKey = `${VISIT_INDEX_STORAGE_PREFIX}${setKey}`;
  //   try {
  //     const rawValue = window.localStorage.getItem(storageKey);
  //     const currentValue = rawValue ? Number.parseInt(rawValue, 10) : 0;
  //     const safeValue = Number.isFinite(currentValue) && currentValue >= 0 ? currentValue : 0;
  //     const nextIndex = safeValue % count;
  //
  //     window.localStorage.setItem(storageKey, String((nextIndex + 1) % count));
  //     return nextIndex;
  //   } catch (err) {
  //     console.error('[DailyInspirationBanner] Failed to persist visit cycling index:', err);
  //     return 0;
  //   }
  // }

  function hashString(value: string): string {
    let hash = 0;
    for (let index = 0; index < value.length; index += 1) {
      hash = (hash * 31 + value.charCodeAt(index)) % 2147483647;
    }
    return hash.toString(36);
  }

  function isDailyInspirationVisible(inspiration: DailyInspiration): boolean {
    if (inspiration.content_type !== 'feature') return true;
    if (isAuthenticated) return true;

    const feature = inspiration.feature;
    if (!feature) return false;
    if (AUTHENTICATED_ONLY_FEATURE_IDS.has(feature.feature_id)) return false;
    if (!feature.settings_path) return feature.requires_authentication !== true;
    if (feature.requires_authentication === true && !GUEST_ALLOWED_FEATURE_PATHS.has(feature.settings_path)) return false;
    return GUEST_ALLOWED_FEATURE_PATHS.has(feature.settings_path);
  }

  function surfaceInspirations(source: DailyInspiration[]): DailyInspiration[] {
    return source.filter((inspiration) => (inspiration.surface ?? 'chats') === surface);
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

{#if visibleInspirations.length > 0 && current}
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
      class:guest-intro-variant={isGuestIntroVariant}
      data-testid="daily-inspiration-banner"
      style={gradientStyle}
      onclick={handleStartChat}
      onpointerdown={handleBannerPointerDown}
      ontouchstart={handleTouchStart}
      ontouchmove={handleTouchMove}
      ontouchend={handleTouchEnd}
      ontouchcancel={handleTouchEnd}
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

        {#if !isGuestIntroVariant}
          <!-- ── Top label ── -->
          <div class="banner-label">
            <BookOpen size={14} color="rgba(255,255,255,0.85)" />
            <span data-testid="daily-inspiration-label">{$text('daily_inspiration.label')}</span>
          </div>
        {/if}

        <!-- ── Main content row: left (mate + text + CTA) + right (embed) ── -->
        <div
          class="banner-content"
          class:mobile-card-loop={shouldCycleMobileCard}
          class:show-mobile-card={shouldCycleMobileCard && showMobileCard}
        >

          {#if isGuestIntroVariant}
            {#if current.inspiration_id === 'openmates-intro'}
              <div class="deco-icon deco-icon-left guest-intro-ai-deco-icon"></div>
              <div class="deco-icon deco-icon-right guest-intro-ai-deco-icon"></div>
            {/if}
            <div class="guest-intro-copy" data-testid="guest-intro-copy">
              {#if current.inspiration_id === 'openmates-intro'}
                <div class="guest-intro-ai-icon" data-testid="guest-intro-ai-icon" aria-hidden="true"></div>
                <span class="guest-intro-copy-line">{$text('demo_chats.for_everyone.teaser_line1')}</span>
                <span class="guest-intro-copy-line">{$text('demo_chats.for_everyone.teaser_line2')}</span>
                <span class="guest-intro-copy-line">{$text('demo_chats.for_everyone.teaser_line3')}</span>
              {:else}
                <span class="guest-intro-copy-line">{infoCardTitle || current.title || $text('daily_inspiration.label')}</span>
                <span class="guest-intro-copy-summary" data-testid="daily-inspiration-phrase">{current.phrase}</span>
              {/if}
            </div>
          {:else}
            <!-- Left column: mate profile (left) + phrase (right), CTA pinned to bottom -->
            <div class="banner-left">
              <!-- Row: mate profile image + inspiration phrase side-by-side, vertically centered -->
              <div class="banner-phrase-row">
                <!-- Mate profile image with AI badge (uses global mates.css classes) -->
                <div class="mate-profile banner-mate-profile {displayCategory}"></div>

                <!-- Inspiration phrase -->
                <p class="banner-phrase" data-testid="daily-inspiration-phrase">{current.phrase}</p>
              </div>

              <!-- CTA: plain text + icon — pinned to bottom of banner-left. -->
              <div class="banner-cta">
                {#if isFeatureInspiration}
                  <LinkIcon class="banner-cta-svg-icon" size={15} color="rgba(255, 255, 255, 0.85)" />
                {:else}
                  <span class="clickable-icon icon_create banner-cta-icon"></span>
                {/if}
                <span class="banner-cta-text">
                  {isFeatureInspiration
                    ? (prefersTouchCta
                      ? $text('daily_inspiration.tap_to_open_settings')
                      : $text('daily_inspiration.click_to_open_settings'))
                    : current.is_opened && current.opened_chat_id
                    ? $text('daily_inspiration.open_chat')
                    : $text('daily_inspiration.click_to_start_chat')}
                </span>
              </div>
            </div>
          {/if}

          <!-- Right column: VideoEmbedPreview (if video attached).
               Click on this area opens the video fullscreen, NOT a new chat.
               We wrap with a transparent overlay button to capture clicks cleanly
               and prevent the banner's onclick from firing. -->
          {#if isGuestIntroVariant && directVideoMp4Url}
            <button
              type="button"
              class="guest-intro-video-box"
              data-testid="guest-intro-video-shell"
              aria-label={$text('daily_inspiration.watch_video')}
              onclick={handleDirectVideoClick}
            >
              {#if directVideoTeaserUrl || directVideoTeaserMp4Url}
                <video
                  class="guest-intro-video"
                  data-testid="guest-intro-video"
                  poster={directVideoPosterUrl || undefined}
                  autoplay
                  muted
                  loop
                  playsinline
                  preload="metadata"
                >
                  {#if directVideoTeaserUrl}
                    <source src={directVideoTeaserUrl} type="video/webm" />
                  {/if}
                  {#if directVideoTeaserMp4Url}
                    <source src={directVideoTeaserMp4Url} type="video/mp4" />
                  {/if}
                </video>
              {:else if directVideoPosterUrl}
                <img class="guest-intro-video" data-testid="guest-intro-video" src={directVideoPosterUrl} alt="" />
              {/if}
              <span class="guest-intro-play" aria-hidden="true"><span></span></span>
            </button>
          {:else if isGuestIntroVariant && hasInfoContent}
            <div class="guest-intro-feature-card" data-testid="daily-inspiration-info-card">
              {#if InfoCardIconComponent}
                <div class="guest-intro-feature-icon" aria-hidden="true">
                  <InfoCardIconComponent size={34} color="white" />
                </div>
              {/if}
              <div class="guest-intro-feature-text">
                <h3>{infoCardTitle}</h3>
                {#if infoCardSubtitle}
                  <p>{infoCardSubtitle}</p>
                {/if}
              </div>
            </div>
          {:else if hasVideo && embedPreviewId}
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
          {:else if hasWikiContent && current.wiki}
            <div class="banner-embed-wrapper">
              <WikipediaEmbedPreview
                id={`wiki-${current.inspiration_id}`}
                title={current.wiki.title}
                wikiTitle={current.wiki.wiki_title || current.wiki.title}
                description={current.wiki.description}
                thumbnailUrl={current.wiki.thumbnail_url}
                wikidataId={current.wiki.wikidata_id}
                status="finished"
                isMobile={false}
                onFullscreen={() => handleInfoCardClick(new MouseEvent('click'))}
              />
            </div>
          {:else if hasInfoCard}
            {#if directVideoMp4Url}
              <button
                type="button"
                class="banner-info-card"
                data-testid="daily-inspiration-info-card"
                data-direct-video="true"
                onclick={handleDirectVideoClick}
              >
                {#if infoCardImage}
                  <img class="banner-info-image" src={infoCardImage} alt={infoCardTitle} />
                {:else if InfoCardIconComponent}
                  <div class="banner-info-icon" aria-hidden="true">
                    <InfoCardIconComponent size={42} color="white" />
                  </div>
                {/if}
                <div class="banner-info-text">
                  <h3>{infoCardTitle}</h3>
                  {#if infoCardSubtitle}
                    <p>{infoCardSubtitle}</p>
                  {/if}
                </div>
              </button>
            {:else}
              <div
                class="banner-info-card"
                data-testid="daily-inspiration-info-card"
                data-direct-video="false"
              >
                {#if infoCardImage}
                  <img class="banner-info-image" src={infoCardImage} alt={infoCardTitle} />
                {:else if InfoCardIconComponent}
                  <div class="banner-info-icon" aria-hidden="true">
                    <InfoCardIconComponent size={42} color="white" />
                  </div>
                {/if}
                <div class="banner-info-text">
                  <h3>{infoCardTitle}</h3>
                  {#if infoCardSubtitle}
                    <p>{infoCardSubtitle}</p>
                  {/if}
                </div>
              </div>
            {/if}
          {/if}
        </div>
      </div><!-- /.banner-inner -->

      <!-- ── Carousel navigation arrows ──
           These are real <button> elements with explicit stopPropagation.
           They are positioned outside .banner-inner so they sit at the edges
           of the full-width card, not constrained by the 680px inner width.
           z-index: 20 ensures they are always on top of the embed wrapper. -->
      {#if hasMultiple}
        {#if isBannerVisible && !isOpeningInspiration}
          <div
            class="carousel-progress"
            data-testid="daily-inspiration-carousel-progress"
            style={`--carousel-progress-duration: ${INSPIRATION_AUTO_ROTATION_INTERVAL_MS}ms`}
            aria-hidden="true"
          >
            {#key progressAnimationKey}
              <div class="carousel-progress-fill" onanimationend={handleProgressAnimationEnd}></div>
            {/key}
          </div>
        {/if}

        <button
          class="carousel-arrow carousel-arrow-left"
          data-testid="daily-inspiration-previous"
          onclick={handlePrevious}
          aria-label={$text('daily_inspiration.previous')}
          type="button"
        >
          <ChevronLeft size={22} color="rgba(255,255,255,0.85)" />
        </button>

        <button
          class="carousel-arrow carousel-arrow-right"
          data-testid="daily-inspiration-next"
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

{#if directVideoFullscreenOpen && current?.direct_video?.mp4_url}
  <DirectVideoEmbedFullscreen
    mp4Url={current.direct_video.mp4_url}
    title={current.direct_video.title}
    onClose={() => { directVideoFullscreenOpen = false; }}
  />
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
    transition: filter 0.15s ease, transform 0.1s ease, height 0.3s ease, min-height 0.3s ease;
    box-shadow: var(--shadow-xl);
    /* Reset browser button defaults */
    font: inherit;
    color: white;
    display: flex;
    align-items: stretch;
    touch-action: pan-y;
  }

  /* When settings panel is open or embed fullscreen is side-by-side, revert to
     fixed height so the banner matches the settings/embed header height.
     Mirrors the identical rule in ChatHeader.svelte. */
  :global(.menu-open) .daily-inspiration-banner,
  :global(.side-by-side-active) .daily-inspiration-banner {
    height: 240px;
    min-height: unset;
  }

  .daily-inspiration-banner:hover {
    filter: brightness(1.07);
  }

  .daily-inspiration-banner:active {
    transform: scale(0.995);
  }

  .daily-inspiration-banner.guest-intro-variant {
    height: clamp(470px, 48vh, 520px);
    min-height: 470px;
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

  .guest-intro-variant .banner-inner {
    width: min(calc(100% - 80px), clamp(960px, 72vw, 1080px));
    max-width: none;
    padding: 8px 40px;
    justify-content: center;
    gap: 0;
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

  .guest-intro-variant .banner-content {
    align-items: center;
    justify-content: center;
    gap: 36px;
    width: 100%;
    transform: translateZ(0);
    contain: layout paint;
  }

  .guest-intro-copy {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    justify-content: center;
    gap: 4px;
    color: white;
    text-align: left;
  }

  .guest-intro-ai-icon {
    width: clamp(54px, 4.2vw, 72px);
    height: clamp(54px, 4.2vw, 72px);
    margin-bottom: var(--spacing-3);
    flex-shrink: 0;
    -webkit-mask-image: url('@openmates/ui/static/icons/ai.svg');
    mask-image: url('@openmates/ui/static/icons/ai.svg');
    -webkit-mask-size: contain;
    mask-size: contain;
    -webkit-mask-repeat: no-repeat;
    mask-repeat: no-repeat;
    -webkit-mask-position: center;
    mask-position: center;
    background-color: rgba(255, 255, 255, 0.92);
  }

  .guest-intro-ai-deco-icon {
    -webkit-mask-image: url('@openmates/ui/static/icons/ai.svg');
    mask-image: url('@openmates/ui/static/icons/ai.svg');
    -webkit-mask-size: contain;
    mask-size: contain;
    -webkit-mask-repeat: no-repeat;
    mask-repeat: no-repeat;
    -webkit-mask-position: center;
    mask-position: center;
    background-color: rgba(255, 255, 255, 0.15);
    --deco-target-opacity: 1;
    --float-rx: 10px;
    --float-ry: 12px;
    animation:
      decoEnter 0.6s ease-out 0.1s both,
      decoFloat 16s linear 0.7s infinite;
  }

  .guest-intro-copy-line {
    display: block;
    max-width: 720px;
    font-size: clamp(3.1rem, 4.1vw, 4.9rem);
    line-height: 1.08;
    font-weight: 700;
    letter-spacing: -0.035em;
    text-shadow: 0 2px 18px rgba(0, 0, 0, 0.2);
  }

  .guest-intro-copy-summary {
    display: block;
    max-width: 560px;
    margin-top: var(--spacing-2);
    font-size: clamp(1rem, 1.35vw, 1.35rem);
    line-height: 1.35;
    font-weight: 600;
    color: rgba(255, 255, 255, 0.92);
  }

  .guest-intro-video-box,
  .guest-intro-feature-card {
    position: relative;
    flex: 0 0 min(48vw, 880px);
    width: min(48vw, 880px);
    min-width: 420px;
    height: clamp(76px, 6.6vw, 118px);
    border-radius: var(--radius-4);
    border: 1px solid rgba(255, 255, 255, 0.16);
    overflow: hidden;
    background: rgba(18, 18, 18, 0.9);
    box-shadow: 0 18px 44px rgba(0, 0, 0, 0.3), 0 4px 12px rgba(0, 0, 0, 0.18);
  }

  .guest-intro-video-box {
    display: block;
    padding: 0 !important;
    cursor: pointer;
  }

  .guest-intro-video {
    display: block;
    width: 100%;
    height: 100%;
    object-fit: cover;
    object-position: center;
  }

  .guest-intro-play {
    position: absolute;
    inset: 50% auto auto 50%;
    transform: translate(-50%, -50%);
    display: grid;
    place-items: center;
    width: clamp(68px, 7vw, 96px);
    height: clamp(68px, 7vw, 96px);
    border-radius: 999px;
    background: rgba(245, 105, 86, 0.72);
    border: 2px solid rgba(255, 255, 255, 0.58);
    box-shadow: 0 8px 28px rgba(0, 0, 0, 0.35);
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
  }

  .guest-intro-play span {
    display: block;
    width: 0;
    height: 0;
    margin-left: 6px;
    border-top: 17px solid transparent;
    border-bottom: 17px solid transparent;
    border-left: 25px solid rgba(255, 255, 255, 0.96);
  }

  .guest-intro-feature-card {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: var(--spacing-5);
    padding: var(--spacing-8);
    box-sizing: border-box;
    color: white;
    text-align: center;
  }

  .guest-intro-feature-icon {
    display: grid;
    place-items: center;
    width: 62px;
    height: 62px;
    border-radius: 999px;
    background: rgba(255, 255, 255, 0.14);
  }

  .guest-intro-feature-text h3,
  .guest-intro-feature-text p {
    margin: 0;
  }

  .guest-intro-feature-text h3 {
    font-size: var(--font-size-lg);
    line-height: 1.15;
  }

  .guest-intro-feature-text p {
    margin-top: var(--spacing-2);
    font-size: var(--font-size-small);
    line-height: 1.35;
    color: rgba(255, 255, 255, 0.78);
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

  .banner-cta-svg-icon {
    flex-shrink: 0;
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

  .banner-info-card {
    width: 220px;
    min-width: 220px;
    align-self: center;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: var(--spacing-4);
    padding: 0;
    border: 0;
    border-radius: 0;
    background: transparent;
    box-shadow: none;
    text-align: center;
    color: white;
    font: inherit;
    filter: none;
    margin: 0;
  }

  .banner-info-image {
    width: 72px;
    height: 72px;
    object-fit: cover;
    border-radius: var(--radius-6);
    box-shadow: var(--shadow-md);
    transition: transform var(--duration-fast) var(--easing-default);
  }

  .banner-info-icon {
    width: 64px;
    height: 64px;
    border-radius: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    background: transparent;
    transition: transform var(--duration-fast) var(--easing-default);
  }

  .banner-info-text h3,
  .banner-info-text p {
    margin: 0;
  }

  .banner-info-text h3 {
    font-size: var(--font-size-sm);
    line-height: 1.2;
    font-weight: 700;
  }

  .banner-info-text p {
    margin-top: var(--spacing-2);
    font-size: var(--font-size-xs);
    line-height: 1.25;
    opacity: 0.9;
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

  .carousel-progress {
    position: absolute;
    left: 0;
    right: 0;
    bottom: 0;
    height: 2px;
    background: transparent;
    pointer-events: none;
    z-index: var(--z-index-dropdown-2);
  }

  .carousel-progress-fill {
    width: 100%;
    height: 100%;
    background: rgba(255, 255, 255, 0.2);
    transform: scaleX(0);
    transform-origin: left center;
    animation: carouselProgressFill var(--carousel-progress-duration) linear forwards;
  }

  @keyframes carouselProgressFill {
    from { transform: scaleX(0); }
    to { transform: scaleX(1); }
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

    .daily-inspiration-banner.guest-intro-variant {
      height: 320px;
      min-height: 320px;
    }

    :global(.menu-open) .daily-inspiration-banner,
    :global(.side-by-side-active) .daily-inspiration-banner {
      height: 190px;
      min-height: unset;
    }

    .banner-inner {
      padding: 12px 48px 10px;
    }

    .guest-intro-variant .banner-inner {
      width: 100%;
      padding: 16px 48px 18px;
    }

    .guest-intro-variant .banner-content {
      flex-direction: column;
      align-items: stretch;
      gap: 14px;
    }

    .guest-intro-copy-line {
      font-size: clamp(1.35rem, 6.8vw, 2.15rem);
      line-height: 1.06;
    }

    .guest-intro-copy-summary {
      font-size: var(--font-size-small);
      -webkit-line-clamp: 2;
      line-clamp: 2;
      display: -webkit-box;
      -webkit-box-orient: vertical;
      overflow: hidden;
    }

    .guest-intro-video-box,
    .guest-intro-feature-card {
      width: 100%;
      min-width: 0;
      flex-basis: auto;
      max-height: 145px;
    }

    .carousel-arrow {
      width: 48px !important;
    }

    .banner-phrase {
      font-size: var(--font-size-small);
      -webkit-line-clamp: 4;
      line-clamp: 4;
    }

    .banner-content.mobile-card-loop {
      position: relative;
      overflow: hidden;
    }

    .banner-content.mobile-card-loop .banner-left,
    .banner-content.mobile-card-loop .banner-embed-wrapper,
    .banner-content.mobile-card-loop .banner-info-card {
      position: absolute;
      inset: 0;
      width: 100%;
      transition:
        opacity 420ms ease,
        transform 420ms ease;
    }

    .banner-content.mobile-card-loop .banner-left {
      opacity: 1;
      transform: translateY(0);
    }

    .banner-content.mobile-card-loop.show-mobile-card .banner-left {
      opacity: 0;
      pointer-events: none;
      transform: translateY(-6px);
    }

    .banner-embed-wrapper {
      width: 140px;
    }

    .banner-info-card {
      width: 140px;
      min-width: 140px;
      padding: 0;
    }

    .banner-info-image,
    .banner-info-icon {
      width: 46px;
      height: 46px;
    }

    .banner-info-text p {
      display: none;
    }

    .banner-content.mobile-card-loop .banner-embed-wrapper,
    .banner-content.mobile-card-loop .banner-info-card {
      margin: 0;
      opacity: 0;
      pointer-events: none;
      transform: translateY(6px);
      justify-content: center;
    }

    .banner-content.mobile-card-loop.show-mobile-card .banner-embed-wrapper,
    .banner-content.mobile-card-loop.show-mobile-card .banner-info-card {
      opacity: 1;
      pointer-events: auto;
      transform: translateY(0);
    }

    .banner-content.mobile-card-loop .banner-embed-wrapper :global(.embed-preview-container) {
      width: min(100%, 220px);
      height: 100%;
      max-width: 220px;
      margin: 0 auto;
    }

    .banner-content.mobile-card-loop .banner-embed-wrapper :global(.unified-embed-preview.desktop) {
      width: 100% !important;
      min-width: unset !important;
      max-width: unset !important;
      height: 100% !important;
      max-height: unset !important;
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
