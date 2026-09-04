<script lang="ts">
  /**
   * DailyInspirationBanner.svelte
   *
   * Native Swift counterparts:
   * - apple/OpenMates/Sources/Features/Chat/Views/DailyInspirationView.swift
   * - apple/OpenMates/Sources/App/MainAppView.swift
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
  import { fade } from 'svelte/transition';
  import { get } from 'svelte/store';
  import { text } from '@repo/ui';
  import { CATEGORY_GRADIENTS, getCategoryGradientColors } from '../utils/categoryUtils';
  import { dailyInspirationStore, type DailyInspiration, type DailyInspirationSource, type DailyInspirationSurface } from '../stores/dailyInspirationStore';
  import { loadDefaultInspirations, loadGuestOnboardingInspirations } from '../demo_chats/loadDefaultInspirations';
  import { authStore } from '../stores/authStore';
  import { introBannerVisible } from '../stores/uiStateStore';
  import { proxyImage, MAX_WIDTH_PREVIEW_THUMBNAIL } from '../utils/imageProxy';
  import { appsMetadata } from '../data/appsMetadata';
  import { resolveIconName } from '../utils/iconNameResolver';
  import VideoEmbedPreview from './embeds/videos/VideoEmbedPreview.svelte';
  import DirectVideoEmbedFullscreen from './embeds/videos/DirectVideoEmbedFullscreen.svelte';
  import WikipediaEmbedPreview from './embeds/wiki/WikipediaEmbedPreview.svelte';
  import LandingActionableEventDemo from './landing/LandingActionableEventDemo.svelte';
  import LandingPrivacySafetyDemo from './landing/LandingPrivacySafetyDemo.svelte';
  import LandingMatesFocusDemo from './landing/LandingMatesFocusDemo.svelte';
  import LandingPeopleExperienceDemo from './landing/LandingPeopleExperienceDemo.svelte';
  import LandingHeadingMotion, { type LandingHeadingMotionPhase } from './landing/LandingHeadingMotion.svelte';
  import {
    ACTIONABLE_DEMO_DURATION_MS,
  } from './landing/landingActionableEventTimeline';
  import {
    PRODUCT_STORY_HEADING_DELAY_MS,
    PRODUCT_STORY_HEADING_FADE_OUT_MS,
    PRODUCT_STORY_HEADING_HIDDEN_SETTLE_MS,
    PRODUCT_STORY_HEADING_SWAP_MS,
    PRIVACY_STORY_CAROUSEL_DURATION_MS,
    MATES_FOCUS_STORY_CAROUSEL_DURATION_MS,
    PEOPLE_EXPERIENCE_STORY_CAROUSEL_DURATION_MS,
  } from './landing/landingProductStoryTimelines';

  // ─── Lucide icons ────────────────────────────────────────────────────────────

  import { getLucideIcon, getValidIconName } from '../utils/categoryUtils';

  const BookOpen = getLucideIcon('book-open');
  const LinkIcon = getLucideIcon('link');
  const ChevronLeft = getLucideIcon('chevron-left');
  const ChevronRight = getLucideIcon('chevron-right');

  const INSPIRATION_AUTO_ROTATION_INTERVAL_MS = 20000;
  const MOBILE_CARD_ROTATION_INTERVAL_MS = Math.round(INSPIRATION_AUTO_ROTATION_INTERVAL_MS * 0.55);
  const LANDING_INTRO_REQUESTS_COUNT = 4;
  const LANDING_INTRO_HEADLINE_ONLY_MS = 1200;
  const LANDING_INTRO_REQUEST_INTERVAL_MS = 2100;
  const LANDING_INTRO_TOTAL_MS = LANDING_INTRO_HEADLINE_ONLY_MS + (LANDING_INTRO_REQUEST_INTERVAL_MS * LANDING_INTRO_REQUESTS_COUNT) + 700;
  const LANDING_INTRO_CONTENT_FADE_MS = 360;
  const LANDING_INTRO_REGULAR_REVEAL_MS = 520;
  const LANDING_INTRO_RESIZE_TRANSITION_MS = 760;
  const HEADING_ENTRY_PAINT_DELAY_MS = 80;
  const SIGNUP_BENEFITS_HOLD_MS = 2800;
  const TOUCH_SWIPE_DISTANCE_PX = 56;
  const TOUCH_SWIPE_VERTICAL_CANCEL_PX = 48;
  const LANDING_INTRO_INSPIRATION_ID = 'openmates-intro';
  const LANDING_ACTIONABLE_EVENTS_ID = 'openmates-actionable-events';
  const LANDING_SIGNUP_CTA_ID = 'openmates-signup-cta';
  const LANDING_INTRO_RAIL_MIN_ICON_COUNT = 40;
  const LANDING_INTRO_PRIMARY_RAIL_MAX_BASE_ICON_COUNT = 12;
  const LANDING_INTRO_PRIMARY_RAIL_DURATION_MS = Math.round(
    LANDING_INTRO_REQUEST_INTERVAL_MS * LANDING_INTRO_RAIL_MIN_ICON_COUNT,
  );
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
  const LANDING_INTRO_FEATURED_APP_IDS = ['health', 'events', 'code', 'news'];
  const LANDING_INTRO_EXCLUDED_APP_IDS = new Set(['ai']);
  const LANDING_INTRO_REQUESTS = [
    { appId: 'health', labelKey: 'guest_onboarding.landing_intro_request_doctor' },
    { appId: 'events', labelKey: 'guest_onboarding.landing_intro_request_events' },
    { appId: 'code', labelKey: 'guest_onboarding.landing_intro_request_web_app' },
    { appId: 'news', labelKey: 'guest_onboarding.landing_intro_request_news' },
  ];

  interface LandingIntroAppIcon {
    appId: string;
    iconName: string;
  }

  type LandingIntroPhase = 'regular' | 'expanded' | 'fading-out' | 'collapsing' | 'expanding';
  type ActionableMobileHeadingPhase = 'large' | 'fading-out' | 'hidden';
  type GuestSlidePhase = 'idle' | 'fading-out' | 'hidden' | 'fading-in';
  type SignupSlidePhase = 'idle' | 'benefits' | 'cta';

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
    /** Increment to force the guest intro carousel back to slide 0. */
    landingIntroResetToken?: number;
    /** Increment to move the guest carousel to the terminal signup slide. */
    landingSignupSlideToken?: number;
    /** Start after the expanded intro when returning from a guest example chat. */
    skipLandingIntro?: boolean;
    /** Called when the visible inspiration changes, including manual and automatic carousel moves. */
    onVisibleInspirationChange?: (inspiration: DailyInspiration) => void;
    /** Called while the logged-out intro overlay changes size over the welcome surface. */
    onLandingIntroExpandedChange?: (phase: LandingIntroPhase) => void;
  }

  let { onStartChat, onEmbedFullscreen, containerWidth = 0, surface = 'chats', variant = 'default', landingIntroResetToken = 0, landingSignupSlideToken = 0, skipLandingIntro = false, onVisibleInspirationChange, onLandingIntroExpandedChange }: Props = $props();
  let isGuestIntroVariant = $derived(variant === 'guest-intro');

  // ─── Local state (Svelte 5 runes) ──────────────────────────────────────────

  // Mirror of the store – updated via subscription below
  let inspirations = $state<DailyInspiration[]>([]);
  let currentIndex = $state(0);
  let isAuthenticated = $state(false);
  let inspirationSource = $state<DailyInspirationSource>('none');

  // Track which inspiration_ids we have already sent a `viewed` WS event for.
  // An entry is added as soon as the banner is visible in the viewport AND the
  // inspiration is the currently displayed carousel slide — this ensures each
  // unique inspiration is counted toward tomorrow's replacement quota even if
  // the user never clicks it (passive view tracking).
  let viewedIds = $state(new Set<string>());
  let pendingViewedIds = $state(new Set<string>());

  // Whether the banner wrapper is currently intersecting the viewport. Default
  // to true so Safari/blocked IntersectionObserver does not stall the carousel.
  let isBannerVisible = $state(true);

  // On mobile, alternate between the assistant message and interactive preview instead
  // of squeezing both into the narrow banner width.
  let showMobileCard = $state(false);
  let actionableMobileHeadingReady = $state(false);
  let actionableMobileHeadingPhase = $state<ActionableMobileHeadingPhase>('large');
  let guestHeadingMotionPhase = $state<LandingHeadingMotionPhase>('entering');
  let introHeadingMotionPhase = $state<LandingHeadingMotionPhase>('entering');
  let guestSlidePhase = $state<GuestSlidePhase>('idle');
  let signupSlidePhase = $state<SignupSlidePhase>('idle');

  // Touch gesture state for mobile carousel swipes.
  let touchStartX = $state(0);
  let touchStartY = $state(0);
  let touchSwipeHandled = $state(false);
  let suppressNextClick = $state(false);
  let prefersTouchCta = $state(false);
  let prefersReducedMotion = $state(false);
  let isUserInteracting = $state(false);
  let isOpeningInspiration = $state(false);
  let directVideoFullscreenOpen = $state(false);
  let progressRestartToken = $state(0);
  let actionableDemoComplete = $state(false);
  let actionableProgressComplete = $state(false);
  let actionableAdvanceCommitted = $state(false);
  let actionableCompletionKey = $state('');
  let lastNotifiedInspirationId = $state('');
  let lastNotifiedLandingIntroPhase = $state<LandingIntroPhase>('regular');
  let landingIntroDismissed = $state(false);
  let landingIntroPhase = $state<LandingIntroPhase>('expanded');
  let landingIntroRequestIndex = $state(-1);
  let pendingLandingIntroIndex = $state<number | null>(null);
  let landingIntroRevealActive = $state(false);
  let landingIntroRevealVisible = $state(false);
  let landingIntroTransitionTimeout: number | undefined;
  let landingIntroAnimationFrame: number | undefined;
  let landingIntroRevealAnimationFrame: number | undefined;
  let landingIntroRevealTimeout: number | undefined;
  let landingIntroRailSyncAnimationFrame: number | undefined;
  let guestProductHeadingEntryTimeout: number | undefined;
  let guestProductHeadingStartTimeout: number | undefined;
  let guestProductHeadingFallbackTimeout: number | undefined;
  let guestProductHeadingReadyTimeout: number | undefined;
  let signupStageTimeout: number | undefined;
  let lastLandingIntroResetToken = $state(0);
  let lastLandingSignupSlideToken = $state(0);
  let skipLandingIntroApplied = $state(false);
  let landingIntroPrimaryRailOffsetPx = $state(0);
  // Temporarily disabled with the visit-cycling effect below.
  // let visitCycleTargetIndexes = $state(new Map<string, number>());
  // let visitCycleAppliedInspirations = $state<DailyInspiration[] | null>(null);
  let manuallyNavigatedSetKeys = $state(new Set<string>());

  // Reference to the outer wrapper element — used as the IntersectionObserver target.
  let bannerWrapperEl = $state<HTMLElement | null>(null);
  let landingIntroPrimaryRailRowEl = $state<HTMLElement | null>(null);
  let landingIntroPrimaryRailEl = $state<HTMLElement | null>(null);

  // ─── Crossfade when data source changes ─────────────────────────────────────
  // When bootstrap/fallback inspirations are replaced by a new source, the
  // banner crossfades: the old content fades out, then the new content fades in.
  // This avoids a jarring instant swap during auth recovery.
  const HARDCODED_ID_PREFIX = "hardcoded-";
  let isCrossfading = $state(false);

  // ─── Subscribe to store ─────────────────────────────────────────────────────

  const unsubscribeDailyInspirations = dailyInspirationStore.subscribe((state) => {
    const previousSource = inspirationSource;
    inspirationSource = state.source;
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
    const isSourceReplacement = previousSource !== 'none' && previousSource !== state.source;
    const shouldCrossfade = !isSameVisibleSet &&
      previousVisibleInspirations.length > 0 &&
      nextVisibleInspirations.length > 0 &&
      ((wasHardcoded && isNowReal) || isSourceReplacement);

    if (shouldCrossfade) {
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
    const becameAuthenticated = state.isAuthenticated && !isAuthenticated;
    const becameUnauthenticated = !state.isAuthenticated && isAuthenticated;
    isAuthenticated = state.isAuthenticated;
    if (becameAuthenticated && surface === 'chats') {
      void loadDefaultInspirations({ allowIndexedDB: true, surface: 'chats' }).catch((error) => {
        console.error('[DailyInspirationBanner] Failed to restore authenticated inspirations:', error);
      });
    } else if (becameUnauthenticated && surface === 'chats') {
      loadGuestOnboardingInspirations();
    }
  });

  onDestroy(() => {
    unsubscribeDailyInspirations();
    unsubscribeAuth();
    onLandingIntroExpandedChange?.('regular');
    window.clearTimeout(landingIntroTransitionTimeout);
    window.clearTimeout(landingIntroRevealTimeout);
    window.cancelAnimationFrame(landingIntroAnimationFrame ?? 0);
    window.cancelAnimationFrame(landingIntroRevealAnimationFrame ?? 0);
    window.cancelAnimationFrame(landingIntroRailSyncAnimationFrame ?? 0);
    window.clearTimeout(signupStageTimeout);
    introBannerVisible.set(false);
  });

  // ─── Reload inspirations on language change ─────────────────────────────────
  // Default (non-personalized) inspirations are fetched from the server with a
  // lang parameter. When the user switches language, we clear the store and
  // re-fetch so the inspiration phrases match the new locale.
  // Personalized inspirations (from WS/IndexedDB) are AI-generated content in the
  // user's language at creation time — they cannot be retranslated, so we skip.
  onMount(() => {
    const pointerQuery = window.matchMedia('(pointer: coarse)');
    const reducedMotionQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
    const updatePointerCta = () => {
      prefersTouchCta = pointerQuery.matches || navigator.maxTouchPoints > 0;
    };
    const updateReducedMotion = () => {
      prefersReducedMotion = reducedMotionQuery.matches;
    };
    updatePointerCta();
    updateReducedMotion();
    pointerQuery.addEventListener('change', updatePointerCta);
    reducedMotionQuery.addEventListener('change', updateReducedMotion);

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
    window.addEventListener('resize', scheduleLandingIntroRailSync);

    return () => {
      pointerQuery.removeEventListener('change', updatePointerCta);
      reducedMotionQuery.removeEventListener('change', updateReducedMotion);
      window.removeEventListener('language-changed-complete', handleLanguageChange);
      window.removeEventListener('resize', scheduleLandingIntroRailSync);
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

  $effect(() => {
    if (!landingIntroOverlayActive) {
      introHeadingMotionPhase = 'hidden';
      return;
    }
    if (landingIntroPhase === 'fading-out' || landingIntroPhase === 'collapsing') {
      introHeadingMotionPhase = 'exiting';
      return;
    }
    introHeadingMotionPhase = 'entering';
    const timeout = window.setTimeout(() => {
      introHeadingMotionPhase = 'visible';
    }, HEADING_ENTRY_PAINT_DELAY_MS);
    return () => window.clearTimeout(timeout);
  });

  // Fire `inspiration_viewed` whenever the current inspiration becomes visible.
  $effect(() => {
    if (!isBannerVisible) return;
    if (!current) return;
    const id = current.inspiration_id;
    if (viewedIds.has(id)) return;
    if (pendingViewedIds.has(id)) return;

    pendingViewedIds = new Set([...pendingViewedIds, id]);
    void sendViewedEvent(id).then((sent) => {
      pendingViewedIds = new Set([...pendingViewedIds].filter((pendingId) => pendingId !== id));
      if (sent) {
        viewedIds = new Set([...viewedIds, id]);
      }
    });
  });

  $effect(() => {
    if (!current) return;
    if (current.inspiration_id === lastNotifiedInspirationId) return;
    lastNotifiedInspirationId = current.inspiration_id;
    onVisibleInspirationChange?.(current);
  });

  // Guest product stories show the heading first, then the demo. The heading is
  // intentionally hidden before the demo starts so text and animation never share
  // the same screen.
  $effect(() => {
    clearGuestProductHeadingTimers();

    if (!shouldCycleMobileCard || landingIntroOverlayActive) {
      showMobileCard = false;
      actionableMobileHeadingReady = false;
      actionableMobileHeadingPhase = 'large';
      guestHeadingMotionPhase = 'hidden';
      return;
    }

    void currentIndex;
    void mobilePreviewKey;
    showMobileCard = false;
    actionableMobileHeadingReady = false;
    actionableMobileHeadingPhase = 'large';
    guestHeadingMotionPhase = 'visible';

    if (isGuestIntroVariant) {
      if (prefersReducedMotion) {
        showMobileCard = true;
        actionableMobileHeadingReady = true;
        actionableMobileHeadingPhase = 'hidden';
        guestHeadingMotionPhase = 'hidden';
        return;
      }
      guestProductHeadingEntryTimeout = window.setTimeout(() => {
        guestHeadingMotionPhase = 'visible';
      }, HEADING_ENTRY_PAINT_DELAY_MS);
      guestProductHeadingStartTimeout = window.setTimeout(() => {
        guestHeadingMotionPhase = 'exiting';
        actionableMobileHeadingPhase = 'fading-out';
        guestProductHeadingFallbackTimeout = window.setTimeout(() => {
          guestHeadingMotionPhase = 'hidden';
          actionableMobileHeadingPhase = 'hidden';
          showMobileCard = true;
          actionableMobileHeadingReady = true;
        }, PRODUCT_STORY_HEADING_SWAP_MS);
      }, PRODUCT_STORY_HEADING_DELAY_MS);

      return clearGuestProductHeadingTimers;
    }

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
  let reachableSlideIndexes = $derived.by(() => getReachableSlideIndexes(currentIndex, visibleInspirations.length));

  let landingIntroIsCurrentSlide = $derived(
    isGuestIntroVariant && current?.inspiration_id === LANDING_INTRO_INSPIRATION_ID,
  );
  let landingIntroOverlayActive = $derived(landingIntroIsCurrentSlide);
  let landingIntroUsesFullHeight = $derived(
    landingIntroOverlayActive && (
      landingIntroPhase === 'regular'
      || landingIntroPhase === 'expanded'
      || landingIntroPhase === 'fading-out'
    ),
  );
  let landingIntroParentPhase = $derived(
    landingIntroOverlayActive && landingIntroPhase === 'regular' ? 'expanded' : landingIntroPhase,
  );
  let landingIntroActiveRequest = $derived(
    LANDING_INTRO_REQUESTS[landingIntroRequestIndex] ?? LANDING_INTRO_REQUESTS[0],
  );

  let landingIntroExamplesVisible = $derived(landingIntroRequestIndex >= 0);
  let landingIntroRequestLabel = $derived(landingIntroExamplesVisible ? $text(landingIntroActiveRequest.labelKey) : '');
  let landingIntroActiveAppId = $derived(landingIntroActiveRequest.appId);
  let isGuestActionableSlide = $derived(
    isGuestIntroVariant && !landingIntroOverlayActive && current?.inspiration_id === LANDING_ACTIONABLE_EVENTS_ID,
  );
  let isGuestSignupCtaSlide = $derived(
    isGuestIntroVariant && !landingIntroOverlayActive && current?.inspiration_id === LANDING_SIGNUP_CTA_ID,
  );
  let shouldHoldOnFinalSlide = $derived(isGuestSignupCtaSlide && currentIndex === visibleInspirations.length - 1);
  let signupBenefitsVisible = $derived(signupSlidePhase === 'benefits');
  let signupCtaVisible = $derived(signupSlidePhase === 'cta');
  let guestProductAnimationKind = $derived.by(() => {
    if (!isGuestIntroVariant || landingIntroOverlayActive) return '';
    if (current?.inspiration_id === 'openmates-privacy-safety') return 'privacy';
    if (current?.inspiration_id === 'openmates-mates-focus') return 'mates';
    if (current?.inspiration_id === 'openmates-provider-cross-platform') return 'platform';
    return '';
  });
  let isCoordinatedGuestStory = $derived(isGuestActionableSlide || !!guestProductAnimationKind);
  let guestHeadingPhaseAttribute = $derived(actionableMobileHeadingReady ? 'demo' : actionableMobileHeadingPhase);
  let guestFeatureHeadlineLines = $derived.by(() => {
    if (isGuestActionableSlide) {
      return [
        $text('guest_onboarding.landing_actionable_line1'),
        $text('guest_onboarding.landing_actionable_line2'),
      ];
    }
    return current?.phrase ? [current.phrase] : [];
  });

  let landingIntroAppIcons = $derived(buildLandingIntroAppIcons());
  let landingIntroFirstRailBase = $derived.by(() => buildPrimaryLandingIntroIcons(landingIntroAppIcons));
  let landingIntroSecondRailBase = $derived.by(() => buildSecondaryLandingIntroIcons(landingIntroAppIcons, landingIntroFirstRailBase));
  let landingIntroFirstRail = $derived.by(() => repeatLandingIntroRailIcons(landingIntroFirstRailBase));
  let landingIntroSecondRail = $derived.by(() => repeatLandingIntroRailIcons(landingIntroSecondRailBase));
  $effect(() => {
    if (landingIntroParentPhase === lastNotifiedLandingIntroPhase) return;
    lastNotifiedLandingIntroPhase = landingIntroParentPhase;
    onLandingIntroExpandedChange?.(landingIntroParentPhase);
  });

  $effect(() => {
    if (!isGuestIntroVariant || landingIntroDismissed || visibleInspirations.length === 0) return;
    const introIndex = visibleInspirations.findIndex((inspiration) =>
      inspiration.inspiration_id === LANDING_INTRO_INSPIRATION_ID,
    );
    if (introIndex >= 0 && currentIndex !== introIndex) {
      currentIndex = introIndex;
    }
  });

  $effect(() => {
    if (!skipLandingIntro) {
      skipLandingIntroApplied = false;
      return;
    }
    if (!isGuestIntroVariant || skipLandingIntroApplied || visibleInspirations.length < 2) return;
    skipLandingIntroApplied = true;
    landingIntroDismissed = true;
    landingIntroPhase = 'regular';
    if (landingIntroIsCurrentSlide) {
      currentIndex = 1;
    }
  });

  $effect(() => {
    window.clearTimeout(signupStageTimeout);

    if (!isGuestSignupCtaSlide) {
      signupSlidePhase = 'idle';
      return;
    }

    signupSlidePhase = 'benefits';

    signupStageTimeout = window.setTimeout(() => {
      signupSlidePhase = 'cta';
    }, SIGNUP_BENEFITS_HOLD_MS);

    return () => {
      window.clearTimeout(signupStageTimeout);
    };
  });

  $effect(() => {
    introBannerVisible.set(isGuestSignupCtaSlide && signupCtaVisible && isBannerVisible);
    return () => introBannerVisible.set(false);
  });

  $effect(() => {
    if (!isGuestIntroVariant || landingIntroResetToken === lastLandingIntroResetToken) return;
    lastLandingIntroResetToken = landingIntroResetToken;
    resetLandingIntroToFirstSlide();
  });

  $effect(() => {
    if (!isGuestIntroVariant || landingSignupSlideToken === lastLandingSignupSlideToken) return;
    const signupIndex = visibleInspirations.findIndex((inspiration) =>
      inspiration.inspiration_id === LANDING_SIGNUP_CTA_ID,
    );
    if (signupIndex < 0) return;
    lastLandingSignupSlideToken = landingSignupSlideToken;
    landingIntroDismissed = true;
    landingIntroPhase = 'regular';
    goToVisibleIndex(signupIndex);
  });

  $effect(() => {
    void containerWidth;
    void landingIntroRequestIndex;
    void landingIntroFirstRail.length;
    void landingIntroPrimaryRailRowEl;
    void landingIntroPrimaryRailEl;
    if (!landingIntroOverlayActive || landingIntroPhase !== 'expanded') {
      landingIntroPrimaryRailOffsetPx = 0;
      return;
    }
    if (landingIntroRequestIndex >= 0) return;
    scheduleLandingIntroRailSync();
  });

  $effect(() => {
    if (!landingIntroOverlayActive || landingIntroPhase === 'regular') {
      landingIntroRequestIndex = -1;
      return;
    }
    if (landingIntroPhase !== 'expanded') return;

    landingIntroRequestIndex = -1;
    let interval: number | undefined;
    const headlineTimeout = window.setTimeout(() => {
      landingIntroRequestIndex = 0;
      interval = window.setInterval(() => {
        landingIntroRequestIndex = Math.min(
          LANDING_INTRO_REQUESTS.length - 1,
          landingIntroRequestIndex + 1,
        );
      }, LANDING_INTRO_REQUEST_INTERVAL_MS);
    }, LANDING_INTRO_HEADLINE_ONLY_MS);
    const timeout = window.setTimeout(() => {
      completeLandingIntro(1);
    }, LANDING_INTRO_TOTAL_MS);

    return () => {
      window.clearTimeout(headlineTimeout);
      if (interval !== undefined) window.clearInterval(interval);
      window.clearTimeout(timeout);
    };
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
  let actionablePlaybackActive = $derived(
    isGuestActionableSlide
      && isBannerVisible
      && containerWidth > 0
      && actionableMobileHeadingReady
      && !prefersReducedMotion,
  );
  let productStoryPlaybackActive = $derived(
    !!guestProductAnimationKind
      && isBannerVisible
      && containerWidth > 0
      && actionableMobileHeadingReady
      && !prefersReducedMotion,
  );
  let carouselProgressDurationMs = $derived(
    landingIntroOverlayActive
      ? LANDING_INTRO_TOTAL_MS
      : isGuestActionableSlide
        ? ACTIONABLE_DEMO_DURATION_MS + PRODUCT_STORY_HEADING_DELAY_MS + PRODUCT_STORY_HEADING_SWAP_MS
        : guestProductAnimationKind === 'privacy'
          ? PRIVACY_STORY_CAROUSEL_DURATION_MS
          : guestProductAnimationKind === 'mates'
            ? MATES_FOCUS_STORY_CAROUSEL_DURATION_MS
            : guestProductAnimationKind === 'platform'
              ? PEOPLE_EXPERIENCE_STORY_CAROUSEL_DURATION_MS
              : INSPIRATION_AUTO_ROTATION_INTERVAL_MS,
  );

  $effect(() => {
    const completionKey = isCoordinatedGuestStory
      ? `${current?.inspiration_id ?? 'none'}-${currentIndex}`
      : '';
    if (completionKey === actionableCompletionKey) return;
    actionableCompletionKey = completionKey;
    actionableDemoComplete = false;
    actionableProgressComplete = false;
    actionableAdvanceCommitted = false;
  });

  $effect(() => {
    if (!isCoordinatedGuestStory || prefersReducedMotion) return;
    if (!actionableDemoComplete || !actionableProgressComplete || actionableAdvanceCommitted) return;
    if (!isBannerVisible || isUserInteracting || isOpeningInspiration) return;
    actionableAdvanceCommitted = true;
    goToNavigableVisibleIndex(currentIndex + 1, 1);
  });

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

  /** Whether mobile should alternate between the assistant message and preview. */
  let shouldCycleMobileCard = $derived(
    isGuestIntroVariant
      ? !!directVideoMp4Url || hasInfoContent
      : isMobileBannerLayout && (hasAttachedVideo || hasInfoContent)
  );

  let hasVideo = $derived(hasAttachedVideo && (containerWidth >= 520 || shouldCycleMobileCard));

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
  let landingIntroPrimaryRailStyle = $derived([
    `--landing-intro-primary-rail-offset: ${landingIntroPrimaryRailOffsetPx}px`,
    `--landing-intro-primary-rail-duration: ${LANDING_INTRO_PRIMARY_RAIL_DURATION_MS}ms`,
  ].join(';'));
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
    if (guestSlidePhase !== 'idle') return;
    if (landingIntroOverlayActive) {
      completeLandingIntro(-1);
      return;
    }
    markManualNavigation();
    resumeAutoRotation();
    goToNavigableVisibleIndex(currentIndex - 1, -1);
    restartProgressAnimation();
  }

  /**
   * Navigate to the next inspiration in the carousel.
   * stopPropagation prevents the banner's onclick from firing.
   */
  function handleNext(e: MouseEvent) {
    e.stopPropagation();
    e.preventDefault();
    if (guestSlidePhase !== 'idle') return;
    if (landingIntroOverlayActive) {
      completeLandingIntro(1);
      return;
    }
    if (shouldHoldOnFinalSlide) return;
    markManualNavigation();
    resumeAutoRotation();
    goToNavigableVisibleIndex(currentIndex + 1, 1);
    restartProgressAnimation();
  }

  function handleTouchStart(e: TouchEvent) {
    if (!hasMultiple || guestSlidePhase !== 'idle' || e.touches.length !== 1) return;

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
      if (landingIntroOverlayActive) {
        completeLandingIntro(1);
        return;
      }
      if (shouldHoldOnFinalSlide) return;
      resumeAutoRotation();
      goToNavigableVisibleIndex(currentIndex + 1, 1);
    } else {
      if (landingIntroOverlayActive) {
        completeLandingIntro(-1);
        return;
      }
      resumeAutoRotation();
      goToNavigableVisibleIndex(currentIndex - 1, -1);
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
   * Handle clicking on the banner body. Guest intro slides advance through the
   * explainer carousel; regular inspiration banners still start/open chats.
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

    if (landingIntroOverlayActive) {
      e.stopPropagation();
      e.preventDefault();
      completeLandingIntro(1);
      return;
    }

    if (!current) return;
    if (isGuestSignupCtaSlide) {
      e.stopPropagation();
      e.preventDefault();
      return;
    }
    if (isGuestIntroVariant) {
      e.stopPropagation();
      e.preventDefault();
      markManualNavigation();
      resumeAutoRotation();
      goToNavigableVisibleIndex(currentIndex + 1, 1);
      restartProgressAnimation();
      return;
    }
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

  function clearGuestProductHeadingTimers(): void {
    window.clearTimeout(guestProductHeadingEntryTimeout);
    window.clearTimeout(guestProductHeadingStartTimeout);
    window.clearTimeout(guestProductHeadingFallbackTimeout);
    window.clearTimeout(guestProductHeadingReadyTimeout);
    guestProductHeadingEntryTimeout = undefined;
    guestProductHeadingStartTimeout = undefined;
    guestProductHeadingFallbackTimeout = undefined;
    guestProductHeadingReadyTimeout = undefined;
  }

  function handleGuestProductHeadingTransitionEnd(event: TransitionEvent): void {
    if (event.target !== event.currentTarget || event.propertyName !== 'opacity') return;
    if (!isGuestIntroVariant || !isCoordinatedGuestStory || actionableMobileHeadingPhase !== 'fading-out') return;

    window.clearTimeout(guestProductHeadingFallbackTimeout);
    window.clearTimeout(guestProductHeadingReadyTimeout);
    guestHeadingMotionPhase = 'hidden';
    actionableMobileHeadingPhase = 'hidden';
    guestProductHeadingReadyTimeout = window.setTimeout(() => {
      showMobileCard = true;
      actionableMobileHeadingReady = true;
    }, PRODUCT_STORY_HEADING_HIDDEN_SETTLE_MS);
  }

  function resetLandingIntroToFirstSlide(): void {
    window.clearTimeout(landingIntroTransitionTimeout);
    window.clearTimeout(landingIntroRevealTimeout);
    window.cancelAnimationFrame(landingIntroAnimationFrame ?? 0);
    window.cancelAnimationFrame(landingIntroRevealAnimationFrame ?? 0);
    window.cancelAnimationFrame(landingIntroRailSyncAnimationFrame ?? 0);
    cancelGuestSlideTransition();
    landingIntroDismissed = false;
    landingIntroRequestIndex = -1;
    landingIntroRevealActive = false;
    landingIntroRevealVisible = false;
    pendingLandingIntroIndex = null;
    const introIndex = visibleInspirations.findIndex((inspiration) =>
      inspiration.inspiration_id === LANDING_INTRO_INSPIRATION_ID,
    );
    currentIndex = introIndex >= 0 ? introIndex : 0;
    landingIntroPhase = 'expanded';
    restartProgressAnimation();
  }

  function handleProgressAnimationEnd(e: AnimationEvent) {
    if (e.target !== e.currentTarget) return;
    if (landingIntroOverlayActive) {
      completeLandingIntro(1);
      return;
    }
    if (isCoordinatedGuestStory) {
      actionableProgressComplete = true;
      return;
    }
    if (!isBannerVisible || visibleInspirations.length <= 1 || shouldHoldOnFinalSlide) return;
    if (isUserInteracting || isOpeningInspiration) return;
    goToNavigableVisibleIndex(currentIndex + 1, 1);
  }

  function handleActionableDemoComplete() {
    if (!isCoordinatedGuestStory || !isBannerVisible) return;
    actionableDemoComplete = true;
  }

  function openSignup(): void {
    if (typeof window === 'undefined') return;
    window.dispatchEvent(new CustomEvent('openSignupInterface'));
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
    if (isGuestIntroVariant) {
      handleStartChat(e as MouseEvent);
      return;
    }
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

  function completeLandingIntro(direction: 1 | -1): void {
    if (!landingIntroOverlayActive || landingIntroPhase === 'fading-out' || landingIntroPhase === 'collapsing') return;
    window.clearTimeout(landingIntroTransitionTimeout);
    window.clearTimeout(landingIntroRevealTimeout);
    window.cancelAnimationFrame(landingIntroAnimationFrame ?? 0);
    window.cancelAnimationFrame(landingIntroRevealAnimationFrame ?? 0);
    window.cancelAnimationFrame(landingIntroRailSyncAnimationFrame ?? 0);
    landingIntroRevealActive = false;
    landingIntroRevealVisible = false;
    pendingLandingIntroIndex = getResolvedVisibleIndex(currentIndex + direction);
    landingIntroPhase = 'fading-out';
    markManualNavigation();
    resumeAutoRotation();
    landingIntroDismissed = true;
    landingIntroTransitionTimeout = window.setTimeout(() => {
      landingIntroPhase = 'collapsing';
      if (pendingLandingIntroIndex !== null) {
        currentIndex = pendingLandingIntroIndex;
        pendingLandingIntroIndex = null;
        landingIntroRequestIndex = -1;
        startLandingIntroRegularReveal();
        restartProgressAnimation();
      }
      landingIntroTransitionTimeout = window.setTimeout(() => {
        finishLandingIntroCollapse();
      }, LANDING_INTRO_RESIZE_TRANSITION_MS + 80);
    }, LANDING_INTRO_CONTENT_FADE_MS);
  }

  function finishLandingIntroCollapse(): void {
    if (landingIntroPhase !== 'collapsing') return;
    window.clearTimeout(landingIntroTransitionTimeout);
    landingIntroPhase = 'regular';
  }

  function startLandingIntroRegularReveal(): void {
    window.clearTimeout(landingIntroRevealTimeout);
    window.cancelAnimationFrame(landingIntroRevealAnimationFrame ?? 0);
    landingIntroRevealActive = true;
    landingIntroRevealVisible = false;
    landingIntroRevealAnimationFrame = window.requestAnimationFrame(() => {
      landingIntroRevealVisible = true;
      landingIntroRevealTimeout = window.setTimeout(() => {
        landingIntroRevealActive = false;
        landingIntroRevealVisible = false;
      }, LANDING_INTRO_REGULAR_REVEAL_MS);
    });
  }

  function buildLandingIntroAppIcons(): LandingIntroAppIcon[] {
    return Object.values(appsMetadata)
      .filter((app) => Boolean(app.id && app.icon_image) && !LANDING_INTRO_EXCLUDED_APP_IDS.has(app.id))
      .map((app) => ({
        appId: app.id,
        iconName: resolveIconName((app.icon_image ?? app.id).replace(/\.svg$/, '').trim()),
      }))
      .sort((a, b) => {
        const aIndex = LANDING_INTRO_FEATURED_APP_IDS.indexOf(a.appId);
        const bIndex = LANDING_INTRO_FEATURED_APP_IDS.indexOf(b.appId);
        if (aIndex >= 0 || bIndex >= 0) {
          return (aIndex >= 0 ? aIndex : Number.MAX_SAFE_INTEGER)
            - (bIndex >= 0 ? bIndex : Number.MAX_SAFE_INTEGER);
        }
        return a.appId.localeCompare(b.appId);
      });
  }

  function buildPrimaryLandingIntroIcons(icons: LandingIntroAppIcon[]): LandingIntroAppIcon[] {
    const featuredIcons = LANDING_INTRO_FEATURED_APP_IDS
      .map((appId) => icons.find((icon) => icon.appId === appId))
      .filter((icon): icon is LandingIntroAppIcon => Boolean(icon));
    const otherIcons = icons.filter((icon) => !LANDING_INTRO_FEATURED_APP_IDS.includes(icon.appId));
    if (featuredIcons.length === 0) return otherIcons.slice(0, LANDING_INTRO_PRIMARY_RAIL_MAX_BASE_ICON_COUNT);
    const remainingIconCount = Math.max(0, LANDING_INTRO_PRIMARY_RAIL_MAX_BASE_ICON_COUNT - featuredIcons.length);
    return [
      ...featuredIcons,
      ...otherIcons.slice(0, remainingIconCount),
    ];
  }

  function buildSecondaryLandingIntroIcons(
    icons: LandingIntroAppIcon[],
    firstRail: LandingIntroAppIcon[],
  ): LandingIntroAppIcon[] {
    const firstRailIds = new Set(firstRail.map((icon) => icon.appId));
    const remainingIcons = icons.filter((icon) => !firstRailIds.has(icon.appId));
    const sourceIcons = remainingIcons.length >= 7 ? remainingIcons : icons.filter((icon) => !LANDING_INTRO_FEATURED_APP_IDS.includes(icon.appId));
    if (sourceIcons.length === 0) return [];
    return Array.from({ length: Math.min(Math.max(sourceIcons.length, 7), 12) }, (_, index) => sourceIcons[index % sourceIcons.length]);
  }

  function repeatLandingIntroRailIcons(icons: LandingIntroAppIcon[]): LandingIntroAppIcon[] {
    if (icons.length === 0) return [];
    const count = Math.max(icons.length, LANDING_INTRO_RAIL_MIN_ICON_COUNT);
    return Array.from({ length: count }, (_, index) => icons[index % icons.length]);
  }

  function getReachableSlideIndexes(index: number, count: number): number[] {
    if (count <= 0) return [];
    if (count === 1) return [0];
    const safeIndex = Math.min(Math.max(index, 0), count - 1);
    const start = Math.max(0, safeIndex - 1);
    const end = Math.min(count - 1, safeIndex + 1);
    return Array.from({ length: end - start + 1 }, (_, offset) => start + offset);
  }

  function getResolvedVisibleIndex(nextIndex: number): number {
    if (visibleInspirations.length === 0) return 0;
    return (nextIndex + visibleInspirations.length) % visibleInspirations.length;
  }

  function landingIntroIconStyle(icon: LandingIntroAppIcon): string {
    return [
      `--landing-intro-icon-url: var(--icon-url-${icon.iconName})`,
      `--landing-intro-app-bg: var(--color-app-${icon.appId}, rgba(255, 255, 255, 0.16))`,
    ].join(';');
  }

  function scheduleLandingIntroRailSync(): void {
    if (typeof window === 'undefined') return;
    window.cancelAnimationFrame(landingIntroRailSyncAnimationFrame ?? 0);
    landingIntroRailSyncAnimationFrame = window.requestAnimationFrame(() => {
      landingIntroRailSyncAnimationFrame = window.requestAnimationFrame(() => {
        landingIntroRailSyncAnimationFrame = undefined;
        syncLandingIntroPrimaryRail();
      });
    });
  }

  function syncLandingIntroPrimaryRail(): void {
    const railRow = landingIntroPrimaryRailRowEl;
    const rail = landingIntroPrimaryRailEl;
    if (!railRow || !rail || !landingIntroOverlayActive || landingIntroPhase !== 'expanded' || landingIntroRequestIndex >= 0) return;

    const rowRect = railRow.getBoundingClientRect();
    const railRect = rail.getBoundingClientRect();
    const targetCenterX = rowRect.left + rowRect.width / 2;
    const activeIcons = Array.from(rail.querySelectorAll<HTMLElement>('[data-testid="landing-intro-app-icon"]'))
      .filter((icon) => icon.dataset.appId === landingIntroActiveAppId);
    if (activeIcons.length === 0) return;

    let bestDelta = 0;
    let bestScore = Number.POSITIVE_INFINITY;
    for (const icon of activeIcons) {
      const iconRect = icon.getBoundingClientRect();
      const iconCenterX = iconRect.left + iconRect.width / 2;
      const delta = targetCenterX - iconCenterX;
      const railCoversRowAfterMove = railRect.left + delta <= rowRect.left && railRect.right + delta >= rowRect.right;
      const score = Math.abs(delta) + (railCoversRowAfterMove ? 0 : 100000);
      if (score < bestScore) {
        bestScore = score;
        bestDelta = delta;
      }
    }

    if (Math.abs(bestDelta) < 0.5) return;
    landingIntroPrimaryRailOffsetPx += bestDelta;
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

  function goToVisibleIndex(
    nextIndex: number,
    options: { restoreLandingIntro?: boolean } = {},
  ): void {
    window.clearTimeout(landingIntroRevealTimeout);
    window.cancelAnimationFrame(landingIntroRevealAnimationFrame ?? 0);
    landingIntroRevealActive = false;
    landingIntroRevealVisible = false;

    if (visibleInspirations.length === 0) {
      currentIndex = 0;
      return;
    }
    const resolvedIndex = getResolvedVisibleIndex(nextIndex);
    if (options.restoreLandingIntro && visibleInspirations[resolvedIndex]?.inspiration_id === LANDING_INTRO_INSPIRATION_ID) {
      window.clearTimeout(landingIntroTransitionTimeout);
      window.cancelAnimationFrame(landingIntroAnimationFrame ?? 0);
      pendingLandingIntroIndex = null;
      landingIntroDismissed = false;
      landingIntroRequestIndex = -1;
      landingIntroPhase = 'expanding';
      landingIntroAnimationFrame = window.requestAnimationFrame(() => {
        landingIntroPhase = 'expanded';
      });
    }
    currentIndex = resolvedIndex;
  }

  function goToNavigableVisibleIndex(nextIndex: number, direction: 1 | -1): void {
    if (!isGuestIntroVariant || !landingIntroDismissed || visibleInspirations.length <= 1) {
      goToVisibleIndex(nextIndex, { restoreLandingIntro: direction < 0 });
      return;
    }

    let resolvedIndex = getResolvedVisibleIndex(nextIndex);
    if (visibleInspirations[resolvedIndex]?.inspiration_id === LANDING_INTRO_INSPIRATION_ID) {
      if (direction > 0) {
        resolvedIndex = getResolvedVisibleIndex(resolvedIndex + direction);
      } else {
        goToVisibleIndex(resolvedIndex, { restoreLandingIntro: true });
        return;
      }
    }
    if (resolvedIndex !== currentIndex) {
      startGuestSlideTransition(resolvedIndex);
      return;
    }
    goToVisibleIndex(resolvedIndex, { restoreLandingIntro: direction < 0 });
  }

  function startGuestSlideTransition(resolvedIndex: number): void {
    if (guestSlidePhase !== 'idle') return;
    goToVisibleIndex(resolvedIndex);
    guestHeadingMotionPhase = 'visible';
  }

  function cancelGuestSlideTransition(): void {
    guestSlidePhase = 'idle';
    guestHeadingMotionPhase = 'visible';
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
  async function sendViewedEvent(inspirationId: string): Promise<boolean> {
    if (!get(authStore).isAuthenticated) return true;
    try {
      const { webSocketService } = await import('../services/websocketService');
      if (!webSocketService.isConnected()) {
        console.debug('[DailyInspirationBanner] Skipping inspiration_viewed while WebSocket is disconnected:', inspirationId);
        return true;
      }
      await webSocketService.sendMessage('inspiration_viewed', {
        inspiration_id: inspirationId,
      });
      console.debug('[DailyInspirationBanner] Sent inspiration_viewed:', inspirationId);
      return true;
    } catch (err) {
      console.error('[DailyInspirationBanner] Failed to send inspiration_viewed:', err);
      return true;
    }
  }
</script>

{#if visibleInspirations.length > 0 && current}
  <!-- Outer wrapper for fade-in animation and full-width layout.
       bind:this lets the IntersectionObserver target this element to detect
       when the banner enters the viewport for passive view tracking. -->
  <div
    class="daily-inspiration-wrapper"
    class:crossfading={isCrossfading}
    class:landing-intro-overlay-active={landingIntroOverlayActive}
    bind:this={bannerWrapperEl}
  >

    <!--
      Banner card: div[role=button] avoids nested-button HTML validation errors
      since carousel arrow <button> elements live inside the card.
      Fixed height of 240px so the embed is never cut off.
    -->
      <!-- svelte-ignore a11y_no_noninteractive_tabindex -->
      <div
        class="daily-inspiration-banner"
      class:guest-intro-variant={isGuestIntroVariant}
      class:guest-signup-slide={isGuestSignupCtaSlide}
      class:landing-intro-overlay-active={landingIntroOverlayActive}
      class:landing-intro-expanded={landingIntroUsesFullHeight}
      class:landing-intro-fading-out={landingIntroPhase === 'fading-out'}
      class:landing-intro-collapsing={landingIntroPhase === 'collapsing'}
      class:landing-intro-expanding={landingIntroPhase === 'expanding'}
      class:landing-intro-revealing-next={landingIntroRevealActive}
      class:landing-intro-reveal-visible={landingIntroRevealVisible}
      data-landing-intro-phase={landingIntroParentPhase}
      data-landing-intro-revealing-next={landingIntroRevealActive ? 'true' : 'false'}
      data-guest-slide-phase={guestSlidePhase}
      data-mounted-slide-indexes={reachableSlideIndexes.join(',')}
      data-visible-inspiration-ids={visibleInspirations.map((inspiration) => inspiration.inspiration_id).join(',')}
      data-inspiration-source={inspirationSource}
      data-testid="daily-inspiration-banner"
      data-current-inspiration-id={current.inspiration_id}
      style={gradientStyle}
      onclick={handleStartChat}
      onpointerdown={handleBannerPointerDown}
      ontransitionend={(e) => {
        if (e.target === e.currentTarget && (e.propertyName === 'height' || e.propertyName === 'min-height')) {
          finishLandingIntroCollapse();
        }
      }}
      ontouchstart={handleTouchStart}
      ontouchmove={handleTouchMove}
      ontouchend={handleTouchEnd}
      ontouchcancel={handleTouchEnd}
      onkeydown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); handleStartChat(e as unknown as MouseEvent); } }}
      role={isGuestSignupCtaSlide ? undefined : 'button'}
      tabindex={isGuestSignupCtaSlide ? undefined : 0}
      aria-label={isGuestSignupCtaSlide ? undefined : current.phrase}
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
      {#if CategoryIconComponent && !isGuestIntroVariant}
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
          class:mobile-card-loop={shouldCycleMobileCard && !landingIntroOverlayActive}
          class:show-mobile-card={shouldCycleMobileCard && !landingIntroOverlayActive && showMobileCard}
          class:guest-actionable-slide={isGuestActionableSlide}
          class:actionable-heading-fading-out={actionableMobileHeadingPhase === 'fading-out'}
          class:actionable-heading-hidden={actionableMobileHeadingPhase === 'hidden'}
          data-actionable-heading-phase={isGuestActionableSlide ? actionableMobileHeadingPhase : undefined}
          data-guest-heading-phase={shouldCycleMobileCard ? guestHeadingPhaseAttribute : undefined}
          data-mobile-heading-phase={shouldCycleMobileCard ? guestHeadingPhaseAttribute : undefined}
          data-testid="guest-slide-content"
          style={`--actionable-mobile-heading-fade-out: ${PRODUCT_STORY_HEADING_FADE_OUT_MS}ms`}
        >

          {#if isGuestIntroVariant}
            {#if landingIntroOverlayActive}
              <div
                class="landing-intro-expanded-content"
                class:examples-visible={landingIntroExamplesVisible}
                data-testid="landing-intro-expanded"
              >
                <div class="landing-intro-expanded-motion">
                  <LandingHeadingMotion phase={introHeadingMotionPhase} testId="landing-intro-heading-motion">
                    <div class="guest-intro-ai-icon landing-intro-ai-icon" data-testid="guest-intro-ai-icon" aria-hidden="true"></div>
                    <h1 class="landing-intro-headline" data-testid="landing-intro-headline">
                      <span class="landing-intro-headline-desktop">
                        <span>{$text('guest_onboarding.landing_intro_headline_line1')}</span>
                        <span>{$text('guest_onboarding.landing_intro_headline_line2')}</span>
                      </span>
                      <span class="landing-intro-headline-mobile">
                        <span>{$text('guest_onboarding.landing_intro_headline_line1')}</span>
                        <span>{$text('guest_onboarding.landing_intro_headline_line2')}</span>
                      </span>
                    </h1>
                  </LandingHeadingMotion>
                  <div class="landing-intro-examples" class:visible={landingIntroExamplesVisible}>
                    <div class="landing-intro-request" data-testid="landing-intro-request" aria-live="polite">
                      {#key landingIntroRequestLabel}
                        <span>{landingIntroRequestLabel}</span>
                      {/key}
                    </div>
                    <div class="landing-intro-app-rails" aria-hidden="true">
                      <div class="landing-intro-app-rail-row landing-intro-app-rail-row-primary" bind:this={landingIntroPrimaryRailRowEl}>
                        <div
                          class="landing-intro-app-rail landing-intro-app-rail-primary"
                          data-testid="landing-intro-app-rail"
                          data-active-app-id={landingIntroActiveAppId}
                          style={landingIntroPrimaryRailStyle}
                          bind:this={landingIntroPrimaryRailEl}
                        >
                          {#each [...landingIntroFirstRail, ...landingIntroFirstRail] as icon, index (`primary-${icon.appId}-${index}`)}
                            <span
                              class="landing-intro-app-icon"
                              class:highlighted={icon.appId === landingIntroActiveAppId}
                              data-testid="landing-intro-app-icon"
                              data-app-id={icon.appId}
                              data-highlighted={icon.appId === landingIntroActiveAppId ? 'true' : 'false'}
                              style={landingIntroIconStyle(icon)}
                            ></span>
                          {/each}
                        </div>
                      </div>
                      <div class="landing-intro-app-rail-row landing-intro-app-rail-row-secondary">
                        <div class="landing-intro-app-rail landing-intro-app-rail-secondary" data-testid="landing-intro-app-rail">
                          {#each [...landingIntroSecondRail, ...landingIntroSecondRail] as icon, index (`secondary-${icon.appId}-${index}`)}
                            <span
                              class="landing-intro-app-icon"
                              data-testid="landing-intro-app-icon"
                              data-app-id={icon.appId}
                              data-highlighted="false"
                              style={landingIntroIconStyle(icon)}
                            ></span>
                          {/each}
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            {:else if isGuestSignupCtaSlide}
              <div
                class="guest-signup-sequence"
                data-testid="landing-signup-cta"
                data-stage={signupCtaVisible ? 'cta' : 'benefits'}
              >
                <div
                  class="guest-signup-stage guest-signup-benefits-stage"
                  class:stage-visible={signupSlidePhase === 'benefits'}
                  aria-hidden={!signupBenefitsVisible}
                >
                  <ul
                    class="guest-signup-benefits-list"
                    data-testid="landing-signup-benefits"
                    aria-label={current.feature?.description ?? current.phrase}
                  >
                    {#each current.follow_up_suggestions ?? [] as reason}
                      <li data-testid="landing-signup-benefit">
                        <span class="guest-signup-benefit-check" aria-hidden="true">✓</span>
                        <span>{reason}</span>
                      </li>
                    {/each}
                  </ul>
                </div>
                <div
                  class="guest-signup-stage guest-signup-cta"
                  class:stage-visible={signupSlidePhase === 'cta'}
                  aria-hidden={!signupCtaVisible}
                >
                  <h2>{current.phrase}</h2>
                  <button
                    class="guest-signup-cta-button"
                    class:pulsing={signupSlidePhase === 'cta'}
                    data-testid="landing-signup-cta-button"
                    type="button"
                    onclick={(e) => { e.stopPropagation(); openSignup(); }}
                  >
                    {current.title ?? current.phrase}
                  </button>
                </div>
              </div>
            {:else}
              {#key current.inspiration_id}
                <div
                  class="guest-intro-copy"
                  class:guest-feature-copy={true}
                  class:guest-actionable-copy={isGuestActionableSlide}
                  data-actionable-heading-ready={isGuestActionableSlide ? (actionableMobileHeadingReady ? 'true' : 'false') : undefined}
                  data-testid="guest-intro-copy"
                  in:fade={{ duration: 320 }}
                  ontransitionend={handleGuestProductHeadingTransitionEnd}
                >
                  <LandingHeadingMotion phase={guestHeadingMotionPhase} testId="landing-guest-heading-motion">
                    {#if InfoCardIconComponent && !isCoordinatedGuestStory}
                      <span class="guest-feature-inline-icon" data-testid="guest-feature-inline-icon" aria-hidden="true">
                        <InfoCardIconComponent size={44} color="white" />
                      </span>
                    {/if}
                    <span class="guest-feature-headline" data-testid="daily-inspiration-phrase">
                      {#each guestFeatureHeadlineLines as line, index}
                        <span>{line}</span>{#if index < guestFeatureHeadlineLines.length - 1}<br>{/if}
                      {/each}
                    </span>
                  </LandingHeadingMotion>
                </div>
              {/key}
            {/if}
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
                <span class="banner-cta-text" data-testid="daily-inspiration-cta-text">
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
          {#if isGuestIntroVariant && landingIntroOverlayActive}
            <!-- The expanded intro owns the full banner; no side preview is rendered. -->
          {:else if isGuestIntroVariant && (!isCoordinatedGuestStory || actionableMobileHeadingReady)}
            {#key current.inspiration_id}
              {#if isGuestSignupCtaSlide}
                <!-- The final slide sequence owns the full banner content area. -->
              {:else if isGuestActionableSlide}
                <div class="guest-actionable-demo-shell" in:fade={{ duration: 320 }}>
                  <LandingActionableEventDemo playing={actionablePlaybackActive} onComplete={handleActionableDemoComplete} />
                </div>
              {:else if guestProductAnimationKind}
                <div class="guest-story-demo-shell" in:fade={{ duration: 320 }}>
                  {#if guestProductAnimationKind === 'privacy'}
                    <LandingPrivacySafetyDemo playing={productStoryPlaybackActive} reducedMotion={prefersReducedMotion} onComplete={handleActionableDemoComplete} />
                  {:else if guestProductAnimationKind === 'mates'}
                    <LandingMatesFocusDemo playing={productStoryPlaybackActive} reducedMotion={prefersReducedMotion} onComplete={handleActionableDemoComplete} />
                  {:else}
                    <LandingPeopleExperienceDemo playing={productStoryPlaybackActive} reducedMotion={prefersReducedMotion} onComplete={handleActionableDemoComplete} />
                  {/if}
                </div>
              {:else if directVideoMp4Url}
                <button
                  type="button"
                  class="guest-intro-video-box"
                  data-testid="guest-intro-video-shell"
                  aria-label={$text('daily_inspiration.watch_video')}
                  onclick={handleDirectVideoClick}
                  in:fade={{ duration: 320 }}
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
              {:else if hasInfoContent}
                <div
                  class="guest-intro-feature-card"
                  class:guest-feature-card={current.inspiration_id !== LANDING_INTRO_INSPIRATION_ID}
                  data-testid="daily-inspiration-info-card"
                  in:fade={{ duration: 320 }}
                >
                  {#if InfoCardIconComponent}
                    <div class="guest-intro-feature-icon" aria-hidden="true">
                      <InfoCardIconComponent size={34} color="white" />
                    </div>
                  {/if}
                  <div class="guest-intro-feature-text">
                    <h3>{infoCardTitle}</h3>
                    {#if infoCardSubtitle && current.inspiration_id === LANDING_INTRO_INSPIRATION_ID}
                      <p>{infoCardSubtitle}</p>
                    {/if}
                  </div>
                </div>
              {/if}
            {/key}
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
                {#if directVideoTeaserUrl || directVideoTeaserMp4Url}
                  <span class="banner-info-video-shell">
                    <video
                      class="banner-info-video"
                      data-testid="daily-inspiration-direct-video"
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
                    <span class="banner-info-play" aria-hidden="true"><span></span></span>
                  </span>
                {:else if infoCardImage}
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

      <div class="mounted-slide-sentinels" aria-hidden="true">
        {#each reachableSlideIndexes as slideIndex (slideIndex)}
          <span
            data-testid="daily-inspiration-mounted-slide"
            data-slide-index={slideIndex}
            data-current={slideIndex === currentIndex ? 'true' : 'false'}
          ></span>
        {/each}
      </div>

      <!-- ── Carousel navigation arrows ──
           These are real <button> elements with explicit stopPropagation.
           They are positioned outside .banner-inner so they sit at the edges
           of the full-width card, not constrained by the 680px inner width.
           z-index: 20 ensures they are always on top of the embed wrapper. -->
      {#if hasMultiple}
        {#if isBannerVisible && !isOpeningInspiration && !shouldHoldOnFinalSlide && landingIntroPhase !== 'fading-out' && landingIntroPhase !== 'collapsing'}
          <div
            class="carousel-progress"
            data-testid="daily-inspiration-carousel-progress"
            style={`--carousel-progress-duration: ${carouselProgressDurationMs}ms`}
            aria-hidden="true"
          >
            {#key progressAnimationKey}
              <div class="carousel-progress-fill" class:reduced-motion={prefersReducedMotion} data-testid="daily-inspiration-carousel-progress-fill" onanimationend={handleProgressAnimationEnd}></div>
            {/key}
          </div>
        {/if}

        {#if !landingIntroOverlayActive}
          <button
            class="carousel-arrow carousel-arrow-left"
            data-testid="daily-inspiration-previous"
            onclick={handlePrevious}
            disabled={guestSlidePhase !== 'idle'}
            aria-label={$text('daily_inspiration.previous')}
            type="button"
          >
            <ChevronLeft size={22} color="rgba(255,255,255,0.85)" />
          </button>
        {/if}

        {#if !shouldHoldOnFinalSlide}
          <button
            class="carousel-arrow carousel-arrow-right"
            data-testid="daily-inspiration-next"
            onclick={handleNext}
            disabled={guestSlidePhase !== 'idle'}
            aria-label={$text('daily_inspiration.next')}
            type="button"
          >
            <ChevronRight size={22} color="rgba(255,255,255,0.85)" />
          </button>
        {/if}
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
    height: 100%;
    /* Must be above other chat-side elements so the banner is clickable */
    position: relative;
    z-index: var(--z-index-dropdown);
  }

  .daily-inspiration-wrapper.landing-intro-overlay-active {
    position: absolute;
    inset: 0;
    bottom: calc(0px - var(--landing-intro-input-reserve, 0px));
    height: auto;
    z-index: var(--z-index-dropdown-1);
  }

  @keyframes inspirationFadeIn {
    from { opacity: 0; transform: translateY(8px); }
    to   { opacity: 1; transform: translateY(0);   }
  }

  /* Crossfade transition: when bootstrap/fallback data is replaced,
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
    height: 100%;
    min-height: 0;
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

  .daily-inspiration-banner.guest-signup-slide {
    cursor: default;
  }

  /* Settings and side-by-side layouts use the same container-derived height as
     the surrounding daily-inspiration area. */
  :global(.menu-open) .daily-inspiration-banner,
  :global(.side-by-side-active) .daily-inspiration-banner {
    height: 100%;
    min-height: 0;
  }

  .daily-inspiration-banner:not(.guest-signup-slide):hover {
    filter: brightness(1.07);
  }

  .daily-inspiration-banner:not(.guest-signup-slide):active {
    transform: scale(0.995);
  }

  .daily-inspiration-banner.landing-intro-expanded {
    height: 100%;
    min-height: 0;
    max-height: none;
    transition:
      filter 0.15s ease,
      transform 0.1s ease,
      height 0.75s cubic-bezier(0.22, 1, 0.36, 1),
      min-height 0.75s cubic-bezier(0.22, 1, 0.36, 1);
  }

  .daily-inspiration-banner.landing-intro-fading-out {
    transition:
      filter 0.15s ease,
      transform 0.1s ease,
      height 0.75s cubic-bezier(0.22, 1, 0.36, 1),
      min-height 0.75s cubic-bezier(0.22, 1, 0.36, 1);
  }

  .daily-inspiration-banner.landing-intro-collapsing {
    transition:
      filter 0.15s ease,
      transform 0.1s ease,
      height 0.75s cubic-bezier(0.22, 1, 0.36, 1),
      min-height 0.75s cubic-bezier(0.22, 1, 0.36, 1);
  }

  .daily-inspiration-banner.landing-intro-fading-out .landing-intro-expanded-content,
  .daily-inspiration-banner.landing-intro-collapsing .landing-intro-expanded-content {
    opacity: 0;
    pointer-events: none;
    transform: translateY(-14px) scale(0.985);
  }

  .daily-inspiration-banner.landing-intro-revealing-next:not(.landing-intro-reveal-visible) .guest-intro-copy,
  .daily-inspiration-banner.landing-intro-revealing-next:not(.landing-intro-reveal-visible) .guest-intro-video-box,
  .daily-inspiration-banner.landing-intro-revealing-next:not(.landing-intro-reveal-visible) .guest-intro-feature-card,
  .daily-inspiration-banner.landing-intro-revealing-next:not(.landing-intro-reveal-visible) .guest-product-demo-shell,
  .daily-inspiration-banner.landing-intro-revealing-next:not(.landing-intro-reveal-visible) .guest-story-demo-shell,
  .daily-inspiration-banner.landing-intro-revealing-next:not(.landing-intro-reveal-visible) .guest-actionable-demo-shell {
    opacity: 0;
    pointer-events: none;
    transform: translateY(12px) scale(0.985);
  }

  .daily-inspiration-banner.landing-intro-fading-out .orb,
  .daily-inspiration-banner.landing-intro-collapsing .orb,
  .daily-inspiration-banner.landing-intro-fading-out .landing-intro-headline span,
  .daily-inspiration-banner.landing-intro-collapsing .landing-intro-headline span,
  .daily-inspiration-banner.landing-intro-fading-out .landing-intro-app-rail,
  .daily-inspiration-banner.landing-intro-collapsing .landing-intro-app-rail {
    animation-play-state: paused;
  }

  .daily-inspiration-banner.landing-intro-collapsing .landing-intro-expanded-content {
    position: absolute;
    inset: 0;
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
    width: 100%;
    height: 100%;
    max-width: none;
    padding: clamp(16px, 2.5cqi, 32px) 48px;
    box-sizing: border-box;
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
    position: relative;
    flex-direction: column;
    align-items: stretch;
    justify-content: center;
    gap: 14px;
    width: 100%;
    transform: translateZ(0);
    contain: layout;
  }

  .landing-intro-expanded .banner-inner {
    width: 100%;
    padding: 0;
  }

  .landing-intro-expanded .banner-content {
    contain: none;
    display: grid;
    place-items: center;
    width: 100%;
    height: 100%;
    overflow: visible;
  }

  .landing-intro-expanded-content {
    position: relative;
    z-index: var(--z-index-dropdown-1);
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    width: 100%;
    min-width: 100%;
    height: 100%;
    padding: clamp(18px, 2.2vw, 34px) 0 clamp(16px, 1.8vw, 28px);
    box-sizing: border-box;
    overflow: visible;
    color: white;
    opacity: 1;
    text-align: center;
    transform: translateY(0) scale(1);
    transition:
      opacity 360ms ease,
      transform 360ms cubic-bezier(0.22, 1, 0.36, 1);
  }

  .landing-intro-expanded-motion {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    width: 100%;
    height: 100%;
    animation: landingIntroEnter 620ms cubic-bezier(0.22, 1, 0.36, 1) both;
  }

  .landing-intro-expanded-motion :global(.landing-heading-motion) {
    flex: 0 0 auto;
  }

  .landing-intro-ai-icon {
    width: clamp(68px, 6.2vw, 112px);
    height: clamp(68px, 6.2vw, 112px);
    margin: 0 0 clamp(8px, 1vw, 16px);
    filter: drop-shadow(0 12px 34px rgba(0, 0, 0, 0.2));
    transition: transform 780ms cubic-bezier(0.22, 1, 0.36, 1), margin 780ms cubic-bezier(0.22, 1, 0.36, 1);
  }

  .landing-intro-headline {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 0;
    margin: 0 auto;
    max-width: min(100% - 48px, 1050px);
    font-size: clamp(2.75rem, 4.7vw, 5.65rem);
    line-height: 1.05;
    font-weight: 800;
    letter-spacing: -0.04em;
    text-align: center;
    color: rgba(255, 255, 255, 0.96);
    text-shadow: 0 8px 38px rgba(0, 0, 0, 0.22);
    transition: transform 780ms cubic-bezier(0.22, 1, 0.36, 1), font-size 780ms cubic-bezier(0.22, 1, 0.36, 1);
  }

  .landing-intro-headline span {
    transform-origin: center;
    white-space: nowrap;
    animation: landingIntroHeadlineScale 1800ms ease-in-out infinite alternate;
  }

  .landing-intro-headline-mobile {
    display: none;
  }

  .landing-intro-headline-desktop {
    display: flex;
    flex-direction: column;
    align-items: center;
  }

  .landing-intro-headline span:nth-child(2) {
    animation-delay: 160ms;
  }

  .landing-intro-expanded-content.examples-visible .landing-intro-ai-icon {
    margin-bottom: clamp(6px, 0.8vw, 12px);
    transform: scale(0.92);
  }

  .landing-intro-expanded-content.examples-visible .landing-intro-headline {
    transform: scale(0.96);
  }

  .landing-intro-examples {
    position: relative;
    display: flex;
    flex-direction: column;
    align-items: center;
    width: 100%;
    min-width: 100%;
    padding-bottom: 0;
    box-sizing: border-box;
    opacity: 0;
    transform: translateY(12px);
    pointer-events: none;
    transition:
      opacity 680ms ease,
      transform 780ms cubic-bezier(0.22, 1, 0.36, 1);
  }

  .landing-intro-examples.visible {
    opacity: 1;
    transform: translateY(0);
  }

  .landing-intro-request {
    position: relative;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    margin-top: clamp(10px, 1.15vw, 20px);
    min-height: clamp(44px, 4.1vw, 68px);
    padding: 0 clamp(22px, 2.5vw, 38px);
    border-radius: clamp(11px, 1.1vw, 18px);
    color: var(--color-grey-100);
    background: var(--color-grey-blue);
    box-shadow: 0 8px 0 rgba(43, 62, 122, 0.22), 0 16px 30px rgba(17, 31, 76, 0.24);
    font-size: clamp(1.2rem, 2.25vw, 2.35rem);
    font-weight: 750;
    letter-spacing: -0.035em;
    white-space: nowrap;
  }

  .landing-intro-request::after {
    content: '';
    position: absolute;
    right: -8px;
    bottom: 9px;
    width: 18px;
    height: 18px;
    background: var(--color-grey-blue);
    clip-path: polygon(0 0, 100% 100%, 0 72%);
  }

  .landing-intro-request span {
    animation: landingIntroRequestIn 360ms ease both;
  }

  .landing-intro-app-rails {
    display: flex;
    flex-direction: column;
    gap: clamp(12px, 1.4vw, 22px);
    width: calc(100% + clamp(220px, 32vw, 520px));
    min-width: calc(100% + clamp(220px, 32vw, 520px));
    margin-left: calc(-1 * clamp(110px, 16vw, 260px));
    margin-right: calc(-1 * clamp(110px, 16vw, 260px));
    margin-top: clamp(12px, 1.35vw, 24px);
    overflow: visible;
  }

  .landing-intro-app-rail-row {
    position: relative;
    width: 100%;
    min-width: 100%;
    overflow: visible;
  }

  .landing-intro-app-rail {
    display: flex;
    align-items: center;
    justify-content: flex-start;
    gap: clamp(22px, 2.7vw, 38px);
    min-width: max-content;
    width: max-content;
    padding: clamp(8px, 1vw, 14px) 0;
  }

  .landing-intro-app-rail-primary {
    translate: var(--landing-intro-primary-rail-offset, 0px) 0;
    animation: landingIntroRailLeft var(--landing-intro-primary-rail-duration, 84000ms) linear infinite;
    animation-play-state: paused;
    will-change: transform;
  }

  .landing-intro-expanded-content.examples-visible .landing-intro-app-rail-primary {
    animation-play-state: running;
  }

  .landing-intro-app-rail-secondary {
    animation: landingIntroRailRight 48s linear infinite;
  }

  .mounted-slide-sentinels {
    display: none;
  }

  .landing-intro-app-icon {
    display: inline-grid;
    place-items: center;
    width: clamp(64px, 5.9vw, 112px);
    height: clamp(64px, 5.9vw, 112px);
    border-radius: clamp(14px, 1.15vw, 22px);
    background: var(--landing-intro-app-bg);
    border: 0;
    box-shadow: 0 16px 32px rgba(24, 43, 106, 0.16);
    opacity: 0.3;
    transform: scale(0.94);
    transition:
      opacity 680ms ease,
      transform 680ms cubic-bezier(0.22, 1, 0.36, 1),
      box-shadow 680ms ease;
  }

  .landing-intro-app-icon::before {
    content: '';
    width: 54%;
    height: 54%;
    background: rgba(209, 223, 255, 0.78);
    -webkit-mask-image: var(--landing-intro-icon-url);
    mask-image: var(--landing-intro-icon-url);
    -webkit-mask-size: contain;
    mask-size: contain;
    -webkit-mask-position: center;
    mask-position: center;
    -webkit-mask-repeat: no-repeat;
    mask-repeat: no-repeat;
  }

  .landing-intro-app-icon.highlighted {
    opacity: 1;
    transform: scale(1.12);
    box-shadow: 0 22px 48px rgba(24, 43, 106, 0.28);
  }

  @media (orientation: landscape) and (max-height: 760px) {
    .daily-inspiration-banner.landing-intro-expanded {
      height: 100%;
      min-height: 0;
      max-height: none;
    }

    .landing-intro-expanded-content {
      padding: clamp(12px, 2.1vh, 18px) 0 clamp(10px, 1.8vh, 16px);
    }

    .landing-intro-ai-icon {
      width: clamp(58px, 9.2vh, 76px);
      height: clamp(58px, 9.2vh, 76px);
      margin-bottom: clamp(4px, 1vh, 8px);
    }

    .landing-intro-headline {
      font-size: clamp(2.5rem, 7.2vh, 3.9rem);
      line-height: 1.02;
    }

    .landing-intro-expanded-content.examples-visible .landing-intro-ai-icon {
      transform: scale(0.92);
      margin-bottom: 4px;
    }

    .landing-intro-expanded-content.examples-visible .landing-intro-headline {
      transform: scale(0.94);
    }

    .landing-intro-examples {
      padding-bottom: 10px;
    }

    .landing-intro-request {
      min-height: 38px;
      margin-top: 6px;
      padding: 0 22px;
      font-size: clamp(1.1rem, 3.7vh, 1.75rem);
      border-radius: 12px;
    }

    .landing-intro-request::after {
      bottom: 6px;
      width: 14px;
      height: 14px;
    }

    .landing-intro-app-rails {
      gap: clamp(8px, 1.3vh, 12px);
      margin-top: clamp(8px, 1.4vh, 12px);
      width: calc(100% + clamp(260px, 44vw, 560px));
      min-width: calc(100% + clamp(260px, 44vw, 560px));
      margin-left: calc(-1 * clamp(130px, 22vw, 280px));
      margin-right: calc(-1 * clamp(130px, 22vw, 280px));
    }

    .landing-intro-app-rail {
      gap: clamp(22px, 3.8vh, 36px);
      padding: 3px 0;
    }

    .landing-intro-app-icon {
      width: clamp(54px, 8.8vh, 74px);
      height: clamp(54px, 8.8vh, 74px);
      border-radius: clamp(14px, 2vh, 18px);
    }
  }

  @keyframes landingIntroEnter {
    from { opacity: 0; transform: translateY(14px) scale(0.98); }
    to { opacity: 1; transform: translateY(0) scale(1); }
  }

  @keyframes landingIntroRequestIn {
    from { opacity: 0; transform: translateY(8px); }
    to { opacity: 1; transform: translateY(0); }
  }

  @keyframes landingIntroHeadlineScale {
    from { transform: scale(1); }
    to { transform: scale(1.018); }
  }

  @keyframes landingIntroRailLeft {
    from { transform: translateX(0); }
    to { transform: translateX(-50%); }
  }

  @keyframes landingIntroRailRight {
    from { transform: translateX(-50%); }
    to { transform: translateX(0); }
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
    opacity: 1;
    text-align: left;
    transform: translateY(0) scale(1);
    transition:
      opacity 420ms ease,
      transform 420ms cubic-bezier(0.22, 1, 0.36, 1);
  }

  .guest-intro-ai-icon {
    width: clamp(38px, 3.2vw, 72px);
    height: clamp(38px, 3.2vw, 72px);
    margin-bottom: var(--spacing-2);
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

  .guest-intro-ai-icon.landing-intro-ai-icon {
    width: clamp(70px, 6.2vw, 112px);
    height: clamp(70px, 6.2vw, 112px);
  }

  .guest-intro-copy-line {
    display: block;
    max-width: 760px;
    font-size: clamp(2rem, 2vw, 2.7rem);
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

  .guest-feature-copy {
    position: relative;
    justify-content: center;
    overflow: hidden;
  }

  .guest-feature-headline {
    position: relative;
    z-index: 1;
    display: block;
    max-width: 700px;
    font-size: clamp(2rem, 4.4cqi, 3.5rem);
    line-height: 1.06;
    font-weight: 800;
    letter-spacing: -0.03em;
    color: rgba(255, 255, 255, 0.96);
    text-shadow: 0 2px 18px rgba(0, 0, 0, 0.2);
  }

  .guest-feature-inline-icon {
    display: grid;
    place-items: center;
    width: clamp(38px, 3.2vw, 72px);
    height: clamp(38px, 3.2vw, 72px);
    margin-bottom: var(--spacing-2);
    flex-shrink: 0;
    color: rgba(255, 255, 255, 0.92);
    filter: drop-shadow(0 2px 18px rgba(0, 0, 0, 0.18));
  }

  .guest-feature-inline-icon :global(svg) {
    width: 100%;
    height: 100%;
  }

  .guest-signup-sequence {
    position: relative;
    display: grid;
    place-items: center;
    width: 100%;
    min-height: min(240px, 100%);
  }

  .guest-signup-stage {
    grid-area: 1 / 1;
    opacity: 0;
    visibility: hidden;
    pointer-events: none;
    transform: translateY(0);
    transition: none;
  }

  .guest-signup-stage.stage-visible {
    opacity: 1;
    visibility: visible;
    pointer-events: auto;
  }

  .guest-signup-benefits-stage {
    width: min(100%, 720px);
  }

  .guest-signup-cta {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: clamp(18px, 1.8vw, 28px);
    text-align: center;
  }

  .guest-signup-cta h2 {
    margin: 0;
    color: rgba(255, 255, 255, 0.98);
    font-size: clamp(2rem, 2.8vw, 4rem);
    line-height: 1.02;
    font-weight: 800;
    letter-spacing: -0.045em;
    text-shadow: 0 2px 18px rgba(0, 0, 0, 0.2);
  }

  .guest-signup-benefits-list {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: clamp(22px, 2.4vw, 40px) clamp(30px, 5vw, 80px);
    width: 100%;
    margin: 0;
    padding: 0;
    list-style: none;
  }

  .guest-signup-benefits-list li {
    display: flex;
    width: 100%;
    min-width: 0;
    align-items: center;
    gap: clamp(10px, 1vw, 16px);
    color: rgba(255, 255, 255, 0.96);
    font-size: clamp(1.05rem, 1.7vw, 2.1rem);
    line-height: 1.1;
    font-weight: 750;
    letter-spacing: -0.03em;
    text-shadow: 0 2px 18px rgba(0, 0, 0, 0.22);
    justify-content: flex-start;
  }

  .guest-signup-benefit-check {
    display: grid;
    place-items: center;
    width: 1.25em;
    height: 1.25em;
    flex: 0 0 auto;
    color: #62cf20;
    font-size: 1.25em;
    line-height: 1;
    text-shadow: none;
  }

  .guest-signup-cta-button {
    min-width: 0 !important;
    height: auto !important;
    margin: 10px 0 0 !important;
    padding: 18px 32px !important;
    border: 0 !important;
    border-radius: 999px !important;
    background: var(--color-button-primary, #ff553b) !important;
    color: white !important;
    box-shadow: 0 12px 28px rgba(0, 0, 0, 0.24) !important;
    filter: none !important;
    font: inherit;
    font-size: clamp(1.05rem, 1.3vw, 1.35rem) !important;
    font-weight: 800 !important;
    letter-spacing: -0.02em;
    cursor: pointer;
    transform-origin: center;
  }

  .guest-signup-cta-button.pulsing {
    animation: landingSignupCtaPulse 4.8s ease-in-out infinite;
  }

  @keyframes landingSignupCtaPulse {
    0%, 100% { transform: scale(1); }
    50% { transform: scale(1.2); }
  }

  .guest-signup-cta-button:hover {
    filter: brightness(1.06) !important;
  }

  .guest-intro-video-box,
  .guest-intro-feature-card,
  .guest-product-demo-shell,
  .guest-actionable-demo-shell,
  .guest-story-demo-shell {
    position: relative;
    flex: 0 1 auto;
    height: auto;
    width: min(100%, 760px);
    min-width: 0;
    max-width: 760px;
    aspect-ratio: 16 / 9;
    border-radius: var(--radius-4);
    border: 1px solid rgba(255, 255, 255, 0.16);
    overflow: hidden;
    opacity: 1;
    background: rgba(18, 18, 18, 0.9);
    box-shadow: 0 18px 44px rgba(0, 0, 0, 0.3), 0 4px 12px rgba(0, 0, 0, 0.18);
    transform: translateY(0) scale(1);
    transition:
      opacity 420ms ease,
      transform 420ms cubic-bezier(0.22, 1, 0.36, 1);
  }

  .guest-actionable-demo-shell {
    display: grid;
    place-items: center;
    min-height: 210px;
    overflow: visible;
    background: transparent;
    border: 0;
    box-shadow: none;
  }

  .guest-story-demo-shell {
    display: grid;
    place-items: center;
    min-height: 210px;
    overflow: visible;
    background: transparent;
    border: 0;
    box-shadow: none;
  }

  .guest-product-demo-shell {
    display: grid;
    place-items: center;
    min-height: 210px;
    isolation: isolate;
    background:
      radial-gradient(circle at 20% 18%, rgba(255, 255, 255, 0.2), transparent 28%),
      radial-gradient(circle at 82% 76%, rgba(255, 255, 255, 0.14), transparent 32%),
      rgba(18, 18, 18, 0.45);
  }

  .guest-product-demo-shell::before {
    content: '';
    position: absolute;
    inset: 14%;
    border-radius: 999px;
    border: 1px solid rgba(255, 255, 255, 0.14);
    animation: landingProductPulse 4.8s ease-in-out infinite;
    z-index: -1;
  }

  @keyframes landingProductPulse {
    0%, 100% { transform: scale(0.96); opacity: 0.74; }
    50% { transform: scale(1.05); opacity: 1; }
  }

  .guest-actionable-demo-shell :global(.landing-actionable-demo) {
    width: 100%;
    min-width: 0;
    height: 100%;
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

  .guest-intro-feature-card.guest-feature-card {
    gap: var(--spacing-5);
    padding: var(--spacing-6);
  }

  .guest-intro-feature-icon {
    display: grid;
    place-items: center;
    width: 62px;
    height: 62px;
    border-radius: 999px;
    background: rgba(255, 255, 255, 0.14);
  }

  .guest-feature-card .guest-intro-feature-icon {
    width: 68px;
    height: 68px;
  }

  .guest-feature-card .guest-intro-feature-text h3 {
    max-width: 260px;
    font-size: clamp(1.05rem, 1.6vw, 1.45rem);
    line-height: 1.12;
  }

  .guest-intro-feature-text h3,
  .guest-intro-feature-text p {
    margin: 0;
  }

  .guest-intro-feature-text h3 {
    font-size: var(--font-size-lg);
    line-height: 1.15;
    color: rgba(255, 255, 255, 0.96);
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

  .banner-info-video-shell {
    position: relative;
    display: block;
    width: 176px;
    aspect-ratio: 16 / 9;
    overflow: hidden;
    border-radius: var(--radius-4);
    border: 1px solid rgba(255, 255, 255, 0.18);
    background: rgba(18, 18, 18, 0.72);
    box-shadow: 0 10px 24px rgba(0, 0, 0, 0.26);
  }

  .banner-info-video {
    display: block;
    width: 100%;
    height: 100%;
    object-fit: cover;
    object-position: center;
  }

  .banner-info-play {
    position: absolute;
    inset: auto var(--spacing-3) var(--spacing-3) auto;
    display: grid;
    place-items: center;
    width: 34px;
    height: 34px;
    border-radius: 999px;
    background: rgba(245, 105, 86, 0.78);
    border: 1px solid rgba(255, 255, 255, 0.52);
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.32);
    backdrop-filter: blur(10px);
    -webkit-backdrop-filter: blur(10px);
  }

  .banner-info-play span {
    display: block;
    width: 0;
    height: 0;
    margin-left: 3px;
    border-top: 7px solid transparent;
    border-bottom: 7px solid transparent;
    border-left: 11px solid rgba(255, 255, 255, 0.96);
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
    color: rgba(255, 255, 255, 0.96);
  }

  .banner-info-text p {
    margin-top: var(--spacing-2);
    font-size: var(--font-size-xs);
    line-height: 1.25;
    color: rgba(255, 255, 255, 0.9);
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
    height: 4px;
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

  .carousel-progress-fill.reduced-motion {
    width: 100%;
    animation: none;
    transform: scaleX(1);
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
    .landing-intro-expanded-content,
    .landing-intro-request span,
    .landing-intro-app-rail-row,
    .landing-intro-app-rail,
    .guest-product-demo-shell::before,
    .guest-signup-stage,
    .guest-signup-cta-button.pulsing,
    .guest-signup-benefits-list li {
      animation: none !important;
      transition: none !important;
    }

    .landing-intro-app-rail-primary {
      transition: none !important;
    }

    .guest-signup-benefits-list li {
      opacity: 1;
      transform: none;
    }
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
  @container chat-side (max-width: 730px) {
    .daily-inspiration-banner {
      height: 100%;
      min-height: 0;
    }

    .daily-inspiration-banner.guest-intro-variant:not(.landing-intro-expanded) {
      height: 100%;
      min-height: 0;
    }

    .daily-inspiration-banner.landing-intro-expanded {
      height: 100%;
      min-height: 0;
      max-height: none;
    }

    :global(.menu-open) .daily-inspiration-banner,
    :global(.side-by-side-active) .daily-inspiration-banner {
      height: 100%;
      min-height: 0;
    }

    :global(.menu-open) .daily-inspiration-banner.guest-intro-variant:not(.landing-intro-expanded),
    :global(.side-by-side-active) .daily-inspiration-banner.guest-intro-variant:not(.landing-intro-expanded) {
      height: 100%;
      min-height: 0;
    }

    .banner-inner {
      padding: 12px 48px 10px;
    }

    .guest-intro-variant .banner-inner {
      width: 100%;
      padding: 16px 20px 18px;
    }

    .landing-intro-expanded .banner-inner {
      padding: 0;
    }

    .guest-intro-variant .banner-content {
      flex-direction: column;
      align-items: stretch;
      gap: 14px;
    }

    .landing-intro-expanded .banner-content {
      display: grid;
      align-items: center;
    }

    .landing-intro-headline-desktop {
      display: none;
    }

    .landing-intro-headline-mobile {
      display: flex;
      flex-direction: column;
      align-items: center;
    }

    .landing-intro-headline-mobile > span:nth-child(2) {
      max-width: 18rem;
      white-space: normal;
    }

    .landing-intro-headline {
      max-width: calc(100% - 18px);
      font-size: clamp(1.95rem, 10vw, 2.5rem);
      line-height: 1.1;
      letter-spacing: -0.032em;
      text-align: center;
      align-items: center;
    }

    .landing-intro-ai-icon {
      width: clamp(60px, 15vw, 74px);
      height: clamp(60px, 15vw, 74px);
      margin-bottom: 8px;
    }

    .landing-intro-expanded-content.examples-visible .landing-intro-ai-icon {
      transform: scale(0.92);
      margin-bottom: 6px;
    }

    .landing-intro-expanded-content.examples-visible .landing-intro-headline {
      transform: scale(0.94);
    }

    .landing-intro-examples {
      padding-bottom: 0;
    }

    .landing-intro-request {
      max-width: min(calc(100% - 32px), 360px);
      min-height: 44px;
      margin-top: 18px;
      padding: 0 18px;
      font-size: clamp(1.12rem, 5.4vw, 1.5rem);
      line-height: 1.08;
      white-space: normal;
    }

    .landing-intro-app-rails {
      gap: 12px;
      margin-top: 12px;
      width: calc(100% + 180px);
      min-width: calc(100% + 180px);
      margin-left: -90px;
      margin-right: -90px;
    }

    .landing-intro-app-rail {
      gap: 22px;
    }

    .landing-intro-app-icon {
      width: clamp(54px, 14vw, 66px);
      height: clamp(54px, 14vw, 66px);
      border-radius: 12px;
    }

    .guest-intro-copy-line {
      font-size: clamp(1.35rem, 7vw, 1.9rem);
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

    .guest-feature-headline {
      font-size: clamp(2rem, 8.4vw, 2.35rem);
      line-height: 1.03;
      -webkit-line-clamp: 5;
      line-clamp: 5;
      display: -webkit-box;
      -webkit-box-orient: vertical;
      overflow: hidden;
    }

    .guest-signup-cta {
      align-items: center;
      gap: 10px;
      text-align: center;
    }

    .guest-signup-cta h2 {
      font-size: clamp(1.35rem, 7vw, 2rem);
    }

    .guest-signup-benefits-list {
      gap: 14px 12px;
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }

    .guest-signup-benefits-list li {
      gap: 7px;
      justify-content: flex-start;
      font-size: clamp(0.82rem, 3.8vw, 1.05rem);
    }

    .guest-signup-cta-button {
      padding: 12px 22px !important;
      font-size: 1rem !important;
    }

    .guest-intro-video-box,
    .guest-intro-feature-card,
    .guest-product-demo-shell,
    .guest-actionable-demo-shell,
    .guest-story-demo-shell {
      width: 100%;
      min-width: 0;
      flex-basis: auto;
      height: auto;
      max-height: 145px;
    }

    .guest-intro-feature-card.guest-feature-card {
      gap: var(--spacing-3);
      padding: var(--spacing-4);
    }

    .guest-feature-card .guest-intro-feature-icon {
      width: 52px;
      height: 52px;
    }

    .guest-feature-card .guest-intro-feature-text h3 {
      max-width: 220px;
      font-size: var(--font-size-small);
    }

    .carousel-arrow {
      width: 48px !important;
    }

    .banner-phrase {
      font-size: var(--font-size-small);
      -webkit-line-clamp: 4;
      line-clamp: 4;
    }

  }

    .banner-content.mobile-card-loop {
      position: relative;
      overflow: visible;
    }

    .banner-content.mobile-card-loop .banner-left,
    .banner-content.mobile-card-loop .guest-intro-copy,
    .banner-content.mobile-card-loop .banner-embed-wrapper,
    .banner-content.mobile-card-loop .guest-intro-video-box,
    .banner-content.mobile-card-loop .guest-intro-feature-card,
    .banner-content.mobile-card-loop .guest-product-demo-shell,
    .banner-content.mobile-card-loop .guest-actionable-demo-shell,
    .banner-content.mobile-card-loop .guest-story-demo-shell,
    .banner-content.mobile-card-loop :global(.landing-actionable-demo),
    .banner-content.mobile-card-loop .banner-info-card {
      position: absolute;
      inset: 0;
      width: 100%;
      transition:
        opacity 420ms ease,
        transform 420ms ease;
    }

    .banner-content.mobile-card-loop .banner-left,
    .banner-content.mobile-card-loop .guest-intro-copy {
      opacity: 1;
      transform: translateY(0);
    }

    .banner-content.mobile-card-loop .guest-intro-copy.guest-feature-copy {
      inset: auto;
      top: 50%;
      left: 50%;
      width: min(calc(100% - 64px), 700px);
      height: auto;
      padding-inline: 0;
      box-sizing: border-box;
      align-items: center;
      justify-content: center;
      text-align: center;
      transform: translate(-50%, -50%);
      transform-origin: top center;
      transition:
        top 520ms cubic-bezier(0.22, 1, 0.36, 1),
        left 520ms cubic-bezier(0.22, 1, 0.36, 1),
        width 520ms cubic-bezier(0.22, 1, 0.36, 1),
        padding 520ms cubic-bezier(0.22, 1, 0.36, 1),
        transform 520ms cubic-bezier(0.22, 1, 0.36, 1);
    }

    .banner-content.mobile-card-loop .guest-intro-copy.guest-feature-copy .guest-feature-inline-icon {
      position: absolute;
      top: 0;
      left: 50%;
      margin: 0;
      transform: translate3d(-50%, 0, 0);
    }

    .banner-content.mobile-card-loop .guest-intro-copy.guest-feature-copy .guest-feature-headline {
      margin-top: clamp(46px, 11vw, 58px);
      margin-left: 0;
      text-align: center;
    }

    .banner-content.mobile-card-loop.show-mobile-card .banner-left {
      opacity: 0;
      pointer-events: none;
      transform: translateY(-6px);
    }

    .banner-content.mobile-card-loop.show-mobile-card .guest-intro-copy {
      inset: auto;
      top: 0;
      left: 50%;
      width: min(calc(100% - 44px), 700px);
      max-width: min(calc(100% - 44px), 700px);
      height: auto;
      padding-inline: 0;
      flex-direction: row;
      align-items: center;
      justify-content: center;
      gap: 8px;
      opacity: 1;
      pointer-events: none;
      text-align: center;
      transform: translateX(-50%);
      transform-origin: top center;
    }

    .banner-content.mobile-card-loop.show-mobile-card .guest-intro-copy .guest-feature-inline-icon {
      width: 20px;
      height: 20px;
      margin: 0;
      opacity: 0.5;
    }

    .banner-content.mobile-card-loop.show-mobile-card .guest-intro-copy.guest-feature-copy .guest-feature-inline-icon {
      position: static;
      transform: none;
    }

    .banner-content.mobile-card-loop.show-mobile-card .guest-intro-copy.guest-feature-copy .guest-feature-headline {
      max-width: min(calc(100cqi - 72px), 560px);
      margin-top: 0;
      margin-left: 0;
    }

    .banner-content.mobile-card-loop.show-mobile-card .guest-intro-copy :global(.landing-heading-motion.hidden) {
      opacity: 1;
      transform: none;
    }

    .banner-content.mobile-card-loop .guest-feature-inline-icon {
      transition:
        width 520ms cubic-bezier(0.22, 1, 0.36, 1),
        height 520ms cubic-bezier(0.22, 1, 0.36, 1),
        top 520ms cubic-bezier(0.22, 1, 0.36, 1),
        left 520ms cubic-bezier(0.22, 1, 0.36, 1),
        transform 520ms cubic-bezier(0.22, 1, 0.36, 1),
        margin 520ms cubic-bezier(0.22, 1, 0.36, 1),
        opacity 520ms ease;
    }

    .banner-content.mobile-card-loop.show-mobile-card .guest-intro-copy-line,
    .banner-content.mobile-card-loop.show-mobile-card .guest-feature-headline {
      display: block;
      max-width: min(100%, 560px);
      overflow: visible;
      color: rgba(255, 255, 255, 0.92);
      font-size: clamp(0.82rem, 3.4vw, 1rem);
      line-height: 1.08;
      opacity: 0.5;
      text-align: center;
      text-shadow: 0 2px 12px rgba(0, 0, 0, 0.18);
    }

    .banner-content.mobile-card-loop .guest-feature-headline {
      transition:
        font-size 520ms cubic-bezier(0.22, 1, 0.36, 1),
        line-height 520ms cubic-bezier(0.22, 1, 0.36, 1),
        margin 520ms cubic-bezier(0.22, 1, 0.36, 1),
        opacity 520ms ease;
    }

    .banner-content.mobile-card-loop .guest-feature-copy,
    .banner-content.mobile-card-loop .guest-feature-copy .guest-feature-inline-icon,
    .banner-content.mobile-card-loop .guest-feature-copy .guest-feature-headline {
      transition: none;
    }

    .banner-content.mobile-card-loop.actionable-heading-fading-out .guest-feature-copy {
      opacity: 0;
      transition: opacity var(--actionable-mobile-heading-fade-out) ease;
    }

    .banner-content.mobile-card-loop.actionable-heading-hidden .guest-feature-copy {
      opacity: 0;
      transition: none;
    }

    .banner-content.mobile-card-loop.show-mobile-card.actionable-heading-hidden .guest-feature-copy {
      opacity: 1;
    }

  @container chat-side (max-width: 730px) {

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

    .banner-info-video-shell {
      width: min(100%, 140px);
    }

    .banner-info-text p {
      display: none;
    }

  }

    .banner-content.mobile-card-loop .banner-embed-wrapper,
    .banner-content.mobile-card-loop .guest-intro-video-box,
    .banner-content.mobile-card-loop .guest-intro-feature-card,
    .banner-content.mobile-card-loop .guest-product-demo-shell,
    .banner-content.mobile-card-loop .guest-actionable-demo-shell,
    .banner-content.mobile-card-loop .guest-story-demo-shell,
    .banner-content.mobile-card-loop :global(.landing-actionable-demo),
    .banner-content.mobile-card-loop .banner-info-card {
      margin: 0;
      opacity: 0;
      pointer-events: none;
      transform: translateY(6px);
      justify-content: center;
    }

    .banner-content.mobile-card-loop.show-mobile-card .banner-embed-wrapper,
    .banner-content.mobile-card-loop.show-mobile-card .guest-intro-video-box,
    .banner-content.mobile-card-loop.show-mobile-card .guest-intro-feature-card,
    .banner-content.mobile-card-loop.show-mobile-card .guest-product-demo-shell,
    .banner-content.mobile-card-loop.show-mobile-card .guest-actionable-demo-shell,
    .banner-content.mobile-card-loop.show-mobile-card .guest-story-demo-shell,
    .banner-content.mobile-card-loop.show-mobile-card :global(.landing-actionable-demo),
    .banner-content.mobile-card-loop.show-mobile-card .banner-info-card {
      opacity: 1;
      pointer-events: auto;
      transform: translateY(0);
    }

    .banner-content.mobile-card-loop .guest-intro-video-box,
    .banner-content.mobile-card-loop .guest-intro-feature-card,
    .banner-content.mobile-card-loop .guest-product-demo-shell,
    .banner-content.mobile-card-loop .guest-actionable-demo-shell,
    .banner-content.mobile-card-loop .guest-story-demo-shell,
    .banner-content.mobile-card-loop :global(.landing-actionable-demo) {
      width: min(100%, 760px);
      height: 100%;
      max-height: none;
      min-height: 0;
      margin: 0 auto;
    }

    .banner-content.mobile-card-loop .guest-actionable-demo-shell {
      aspect-ratio: auto;
      max-height: 100%;
    }

    .banner-content.mobile-card-loop .guest-story-demo-shell {
      aspect-ratio: auto;
    }

    .banner-content.mobile-card-loop.show-mobile-card .guest-intro-video-box,
    .banner-content.mobile-card-loop.show-mobile-card .guest-intro-feature-card,
    .banner-content.mobile-card-loop.show-mobile-card .guest-product-demo-shell,
    .banner-content.mobile-card-loop.show-mobile-card .guest-actionable-demo-shell,
    .banner-content.mobile-card-loop.show-mobile-card .guest-story-demo-shell {
      inset: clamp(44px, 12vw, 56px) 0 0;
      height: auto;
    }

    .banner-content.mobile-card-loop.show-mobile-card .guest-actionable-demo-shell :global(.landing-actionable-demo) {
      inset: 0;
      height: 100%;
      margin: auto;
    }

    .banner-content.mobile-card-loop.show-mobile-card .guest-actionable-demo-shell {
      inset-block-start: clamp(42px, 11vw, 48px);
    }

    .banner-content.mobile-card-loop.show-mobile-card .guest-story-demo-shell {
      height: auto;
      max-height: none;
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
      scale: 0.8;
    }

  @container chat-side (max-width: 730px) {

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

  @media (prefers-reduced-motion: reduce) {
    .banner-content.mobile-card-loop.actionable-heading-fading-out .guest-feature-copy {
      transition-duration: 1ms !important;
    }
  }

  /* Note: embed visibility at narrow widths is handled in JS via the containerWidth prop
     (hasVideo derived value), so no CSS media query is needed here. */

</style>
