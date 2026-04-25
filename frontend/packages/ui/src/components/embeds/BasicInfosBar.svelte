<!--
  frontend/packages/ui/src/components/embeds/BasicInfosBar.svelte
  
  Reusable basic info bar component used in both embed previews and fullscreen views.
  
  Structure:
  - App icon in gradient circle (61x61px container, 26x26px icon)
    OR custom favicon (when faviconUrl is provided)
  - Skill icon (29x29px)
  - Status text (skill name/title + optional processing status)
  - Stop button (when processing)
  
  Supports both desktop and mobile layouts.
-->

<script lang="ts">
  import { tick } from 'svelte';
  import { text } from '@repo/ui';
  import { handleImageError } from '../../utils/offlineImageHandler';
  import { proxyImage, MAX_WIDTH_FAVICON } from '../../utils/imageProxy';
  
  /**
   * Props interface for basic info bar
   */
  interface Props {
    /** App identifier (e.g., 'web', 'videos', 'code') - used for gradient color */
    appId: string;
    /** Skill identifier (e.g., 'search', 'get_transcript') */
    skillId: string;
    /** Icon name for the skill icon (e.g., 'search', 'videos', 'book') */
    skillIconName: string;
    /** Processing status */
    status: 'processing' | 'finished' | 'error' | 'cancelled';
    /** Skill display name (shown in status text) */
    skillName: string;
    /** Optional task ID for cancellation */
    taskId?: string;
    /** Whether to use mobile layout */
    isMobile?: boolean;
    /** Click handler for stop button */
    onStop?: () => void;
    /** Whether to show the status text line (default: true) */
    showStatus?: boolean;
    /** Custom favicon URL to show instead of app icon */
    faviconUrl?: string;
    /** Whether favicon should be circular (for channel thumbnails, profile pics) */
    faviconIsCircular?: boolean;
    /** Whether to show skill icon (only for app skills, not for individual embeds like code, website, video) */
    showSkillIcon?: boolean;
    /** Custom status text (overrides default status text) */
    customStatusText?: string;
    /** Optional snippet rendered before the title text (e.g., a small category circle for chat embeds) */
    titleIcon?: import('svelte').Snippet;
    /** Optional snippet rendered between the app icon and the status text (e.g., a play button for audio embeds) */
    actionButton?: import('svelte').Snippet;
  }
  
  let {
    appId,
    skillId,
    skillIconName,
    status,
    skillName,
    taskId,
    isMobile = false,
    onStop,
    showStatus = true,
    faviconUrl,
    faviconIsCircular = false,
    showSkillIcon = true,
    customStatusText,
    titleIcon,
    actionButton
  }: Props = $props();

  // Silence lint for props that exist in the interface for API consistency
  // but are not directly used in the template. skillId is used by data attributes
  // in parent components; taskId is reserved for future cancellation logic.
  // Use $effect to suppress Svelte 5 "state_referenced_locally" warning for reactive props.
  $effect(() => { void skillId; void taskId; });

  // SECURITY: Defense-in-depth — ensure favicon URLs are always proxied even if
  // the caller forgot. Prevents user IP leaks to external favicon hosts.
  let safeFaviconUrl = $derived(
    faviconUrl ? proxyImage(faviconUrl, MAX_WIDTH_FAVICON) : undefined
  );

  // Hint animation phases for the 'finished' state:
  //   'hint'       → showing "Click/Tap to show details" (2s)
  //   'fading'     → hint text fading out (0.35s CSS transition)
  //   'settled'    → final state: custom text fades in, or status line collapses
  type HintPhase = 'hint' | 'fading' | 'settled';
  let hintPhase = $state<HintPhase>('settled');
  // true during the brief window between hint fade-out and custom-text fade-in
  let hintFadingIn = $state(false);

  // Set to true the first time this mounted component observes status='processing'.
  // History-loaded embeds mount with status='finished' and never set this, so
  // they skip the hint entirely — it only fires during live streaming.
  let hasBeenProcessing = $state(false);

  $effect(() => {
    if (status === 'processing') hasBeenProcessing = true;
  });

  $effect(() => {
    const timers: ReturnType<typeof setTimeout>[] = [];
    let cancelled = false;

    if (status === 'finished' && hasBeenProcessing) {
      hintPhase = 'hint';

      timers.push(setTimeout(() => {
        if (cancelled) return;
        hintPhase = 'fading';

        timers.push(setTimeout(async () => {
          if (cancelled) return;
          if (customStatusText) {
            // Cross-fade: keep opacity at 0 while swapping text, then fade in
            hintFadingIn = true;
            hintPhase = 'settled';
            await tick();
            if (!cancelled) hintFadingIn = false;
          } else {
            hintPhase = 'settled';
          }
        }, 350));
      }, 2000));
    } else if (status !== 'finished') {
      hintPhase = 'settled';
      hintFadingIn = false;
    }

    return () => {
      cancelled = true;
      timers.forEach(clearTimeout);
    };
  });

  // Text shown in the status-value line. During hint phases shows the interaction prompt;
  // at settled it shows the custom text (or nothing, since the line collapses).
  let displayedStatusText = $derived(() => {
    if (status === 'finished' && hintPhase !== 'settled') {
      return isMobile ? $text('embeds.tap_to_show_details') : $text('embeds.click_to_show_details');
    }
    if (customStatusText) return customStatusText;
    if (status === 'processing') return $text('common.processing');
    if (status === 'cancelled') return $text('embeds.cancelled');
    return $text('embeds.error');
  });

  // Wrapper collapses (height → 0) when finished and no custom text to show
  let statusValueCollapsed = $derived(
    status === 'finished' && hintPhase === 'settled' && !customStatusText
  );

  // Span fades out during hint → settled transition, and stays transparent during cross-fade
  let statusValueFading = $derived(
    (status === 'finished' && hintPhase === 'fading') || hintFadingIn
  );
  
  // Compute app gradient style using CSS variables from theme.css
  let appGradientStyle = $derived(`background: var(--color-app-${appId});`);
  
  // Handle stop button click - prevent event propagation
  function handleStopClick(e: MouseEvent) {
    e.stopPropagation();
    if (onStop) {
      onStop();
    }
  }
</script>

{#if isMobile}
  <!-- Mobile Layout: Vertical layout with app icon, skill icon, status text, and stop button -->
  <div class="basic-infos-bar mobile">
    <!-- App icon container OR favicon (full width, 44px height, gradient background) -->
    {#if safeFaviconUrl}
      <div class="app-icon-container {appId}" style={appGradientStyle}>
        <img src={safeFaviconUrl} alt="" class="favicon-image-mobile" crossorigin="anonymous" />
      </div>
    {:else}
      <div class="app-icon-container {appId}" style={appGradientStyle}>
        <div class="icon_rounded {appId}"></div>
      </div>
    {/if}
    
    <!-- Skill icon (centered) - only show for app skills -->
    {#if showSkillIcon}
      <div class="skill-icon-container">
        <div class="skill-icon" data-skill-icon={skillIconName}></div>
      </div>
    {/if}
    
    <!-- Status text lines -->
    <div class="status-text-container" class:single-line={!showStatus}>
      <span class="status-label">{skillName}</span>
      {#if showStatus}
        <div class="status-value-wrapper" class:collapsed={statusValueCollapsed}>
          <span
            class="status-value"
            data-testid="embed-status-value"
            class:processing-shimmer={status === 'processing'}
            class:fading={statusValueFading}
          >{displayedStatusText()}</span>
        </div>
      {/if}
    </div>
    
    <!-- Stop button (only when processing) -->
    {#if status === 'processing'}
      <button 
        class="stop-button"
        onclick={handleStopClick}
        aria-label={$text('common.stop')}
        title={$text('common.stop')}
      >
        <span class="clickable-icon icon_stop_processing"></span>
      </button>
    {/if}
  </div>
{:else}
  <!-- Desktop Layout: Horizontal bar (61px height, 30px rounded edges, grey-20 background) -->
  <div class="basic-infos-bar desktop">
    <!-- App icon in gradient circle (always show app icon, not favicon) -->
    <div class="app-icon-circle {appId}" data-testid="app-icon-circle" style={appGradientStyle}>
      <div class="icon_rounded {appId}"></div>
    </div>
    
    <!-- Skill icon (29x29px) - only show for app skills -->
    {#if showSkillIcon}
      <div class="skill-icon" data-skill-icon={skillIconName}></div>
    {/if}
    
    <!-- Status text with optional favicon next to title -->
    <div class="status-text" class:single-line={!showStatus}>
      <span class="status-label">
        {#if titleIcon}
          {@render titleIcon()}
        {:else if safeFaviconUrl}
          <img
            src={safeFaviconUrl}
            alt=""
            class="title-favicon"
            class:circular={faviconIsCircular}
            crossorigin="anonymous"
            onerror={(e) => {
              handleImageError(e.currentTarget as HTMLImageElement);
            }}
          />
        {/if}
        <span class="title-text" class:two-lines={!customStatusText && !statusValueCollapsed}>{skillName}</span>
      </span>
      {#if showStatus}
        <div class="status-value-wrapper" class:collapsed={statusValueCollapsed}>
          <span
            class="status-value"
            data-testid="embed-status-value"
            class:processing-shimmer={status === 'processing'}
            class:fading={statusValueFading}
          >{displayedStatusText()}</span>
        </div>
      {/if}
    </div>
    
    <!-- Optional action button on the right (e.g., play/pause for audio embeds) -->
    {#if actionButton}
      {@render actionButton()}
    {/if}
    
    <!-- Stop button (only when processing) -->
    {#if status === 'processing'}
      <button 
        class="stop-button"
        onclick={handleStopClick}
        aria-label={$text('common.stop')}
        title={$text('common.stop')}
      >
        <span class="clickable-icon icon_stop_processing"></span>
      </button>
    {/if}
  </div>
{/if}

<style>
  /* ===========================================
     Basic Infos Bar - Desktop Layout
     =========================================== */
  
  .basic-infos-bar.desktop {
    display: flex;
    align-items: center;
    gap: var(--spacing-5);
    height: 61px;
    min-height: 61px;
    background-color: var(--color-grey-30);
    border-radius: 30px;
    padding: 0 0 0 0;
    flex-shrink: 0;
    z-index: var(--z-index-raised);
  }
  
  /* App icon circle: 61x61px with gradient background, contains 26x26px icon */
  /* Gradient is dynamically set via inline style using CSS variables from theme.css */
  .basic-infos-bar.desktop .app-icon-circle {
    width: 61px;
    height: 61px;
    min-width: 61px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
  }
  
  /* Override the default icon_rounded positioning for flex layout */
  .basic-infos-bar.desktop .app-icon-circle .icon_rounded {
    width: 26px;
    height: 26px;
    position: relative;
    bottom: auto;
    left: auto;
    z-index: auto;
  }
  
  /* Make the icon white on gradient background */
  .basic-infos-bar.desktop .app-icon-circle .icon_rounded {
    background: transparent !important;
  }
  
  .basic-infos-bar.desktop .app-icon-circle .icon_rounded::after {
    filter: brightness(0) invert(1);
  }
  
  /* Skill icon: 29x29px with color-grey-70, dynamically set icon via data attribute */
  .basic-infos-bar.desktop .skill-icon {
    width: 29px;
    height: 29px;
    background-color: var(--color-grey-70);
    -webkit-mask-position: center;
    mask-position: center;
    -webkit-mask-repeat: no-repeat;
    mask-repeat: no-repeat;
    -webkit-mask-size: contain;
    mask-size: contain;
    flex-shrink: 0;
  }
  
  /* Skill icon variants based on data-skill-icon attribute */
  .basic-infos-bar .skill-icon[data-skill-icon="search"] {
    -webkit-mask-image: url('@openmates/ui/static/icons/search.svg');
    mask-image: url('@openmates/ui/static/icons/search.svg');
  }
  
  .basic-infos-bar .skill-icon[data-skill-icon="videos"] {
    -webkit-mask-image: url('@openmates/ui/static/icons/videos.svg');
    mask-image: url('@openmates/ui/static/icons/videos.svg');
  }
  
  .basic-infos-bar .skill-icon[data-skill-icon="book"] {
    -webkit-mask-image: url('@openmates/ui/static/icons/book.svg');
    mask-image: url('@openmates/ui/static/icons/book.svg');
  }
  
  .basic-infos-bar .skill-icon[data-skill-icon="visible"] {
    -webkit-mask-image: url('@openmates/ui/static/icons/visible.svg');
    mask-image: url('@openmates/ui/static/icons/visible.svg');
  }
  
  .basic-infos-bar .skill-icon[data-skill-icon="reminder"] {
    -webkit-mask-image: url('@openmates/ui/static/icons/reminder.svg');
    mask-image: url('@openmates/ui/static/icons/reminder.svg');
  }
  
  .basic-infos-bar .skill-icon[data-skill-icon="image"] {
    -webkit-mask-image: url('@openmates/ui/static/icons/image.svg');
    mask-image: url('@openmates/ui/static/icons/image.svg');
  }
  
  .basic-infos-bar .skill-icon[data-skill-icon="ai"] {
    -webkit-mask-image: url('@openmates/ui/static/icons/ai.svg');
    mask-image: url('@openmates/ui/static/icons/ai.svg');
  }
  
  .basic-infos-bar .skill-icon[data-skill-icon="focus"] {
    -webkit-mask-image: url('@openmates/ui/static/icons/insight.svg');
    mask-image: url('@openmates/ui/static/icons/insight.svg');
  }

  .basic-infos-bar .skill-icon[data-skill-icon="pin"] {
    -webkit-mask-image: url('@openmates/ui/static/icons/pin.svg');
    mask-image: url('@openmates/ui/static/icons/pin.svg');
  }

  .basic-infos-bar .skill-icon[data-skill-icon="table"],
  .basic-infos-bar .skill-icon[data-skill-icon="sheet"],
  .basic-infos-bar .skill-icon[data-skill-icon="sheets"] {
    -webkit-mask-image: url('@openmates/ui/static/icons/sheets.svg');
    mask-image: url('@openmates/ui/static/icons/sheets.svg');
  }

  .basic-infos-bar .skill-icon[data-skill-icon="event"] {
    -webkit-mask-image: url('@openmates/ui/static/icons/event.svg');
    mask-image: url('@openmates/ui/static/icons/event.svg');
  }

  .basic-infos-bar .skill-icon[data-skill-icon="health"] {
    -webkit-mask-image: url('@openmates/ui/static/icons/heart.svg');
    mask-image: url('@openmates/ui/static/icons/heart.svg');
  }

  .basic-infos-bar .skill-icon[data-skill-icon="mail"] {
    -webkit-mask-image: url('@openmates/ui/static/icons/mail.svg');
    mask-image: url('@openmates/ui/static/icons/mail.svg');
  }

  .basic-infos-bar .skill-icon[data-skill-icon="home"] {
    -webkit-mask-image: url('@openmates/ui/static/icons/home.svg');
    mask-image: url('@openmates/ui/static/icons/home.svg');
  }

  .basic-infos-bar .skill-icon[data-skill-icon="coding"] {
    -webkit-mask-image: url('@openmates/ui/static/icons/coding.svg');
    mask-image: url('@openmates/ui/static/icons/coding.svg');
  }

  .basic-infos-bar .skill-icon[data-skill-icon="travel"] {
    -webkit-mask-image: url('@openmates/ui/static/icons/travel.svg');
    mask-image: url('@openmates/ui/static/icons/travel.svg');
  }

  .basic-infos-bar .skill-icon[data-skill-icon="website"] {
    -webkit-mask-image: url('@openmates/ui/static/icons/web.svg');
    mask-image: url('@openmates/ui/static/icons/web.svg');
  }

  .basic-infos-bar .skill-icon[data-skill-icon="text"] {
    -webkit-mask-image: url('@openmates/ui/static/icons/text.svg');
    mask-image: url('@openmates/ui/static/icons/text.svg');
  }

  .basic-infos-bar .skill-icon[data-skill-icon="transcript"] {
    -webkit-mask-image: url('@openmates/ui/static/icons/videos.svg');
    mask-image: url('@openmates/ui/static/icons/videos.svg');
  }

  .basic-infos-bar .skill-icon[data-skill-icon="docs"] {
    -webkit-mask-image: url('@openmates/ui/static/icons/docs.svg');
    mask-image: url('@openmates/ui/static/icons/docs.svg');
  }

  .basic-infos-bar .skill-icon[data-skill-icon="video"] {
    -webkit-mask-image: url('@openmates/ui/static/icons/videos.svg');
    mask-image: url('@openmates/ui/static/icons/videos.svg');
  }

  .basic-infos-bar .skill-icon[data-skill-icon="math"] {
    -webkit-mask-image: url('@openmates/ui/static/icons/math.svg');
    mask-image: url('@openmates/ui/static/icons/math.svg');
  }

  .basic-infos-bar .skill-icon[data-skill-icon="nutrition"] {
    -webkit-mask-image: url('@openmates/ui/static/icons/nutrition.svg');
    mask-image: url('@openmates/ui/static/icons/nutrition.svg');
  }

  /* Status text container */
  .basic-infos-bar.desktop .status-text {
    display: flex;
    flex-direction: column;
    justify-content: center;
    flex: 1;
    min-width: 0;
    /* gap handled by margin-top on .status-value-wrapper for smooth collapse animation */
  }
  
  .basic-infos-bar.desktop .status-label {
    font-size: var(--font-size-p);
    font-weight: 600;
    color: var(--color-grey-100);
    line-height: 1.2;
    display: flex;
    align-items: center;
    gap: var(--spacing-4);
    overflow: hidden;
  }
  
  .basic-infos-bar.desktop .title-favicon {
    width: 20px;
    height: 20px;
    border-radius: var(--radius-1);
    flex-shrink: 0;
    object-fit: cover;
  }
  
  /* Circular favicon for channel thumbnails/profile pictures */
  .basic-infos-bar.desktop .title-favicon.circular {
    width: 25px;
    height: 25px;
    border-radius: 50%;
  }
  
  .basic-infos-bar.desktop .title-text {
    flex: 1;
    min-width: 0;
    /* Default: 1 line with ellipsis (for embeds with custom status text like videos) */
    display: -webkit-box;
    -webkit-line-clamp: 1;
    line-clamp: 1;
    -webkit-box-orient: vertical;
    overflow: hidden;
    text-overflow: ellipsis;
    word-break: break-word;
  }
  
  /* Two lines for title when no custom status text is present (e.g., websites) */
  /* This allows the title to use more vertical space when there's no duration/date line */
  .basic-infos-bar.desktop .title-text.two-lines {
    -webkit-line-clamp: 2;
    line-clamp: 2;
  }
  
  /* Collapsible wrapper for the status-value line — animates height and spacing to zero */
  .basic-infos-bar.desktop .status-value-wrapper {
    display: grid;
    grid-template-rows: 1fr;
    margin-top: var(--spacing-1);
    transition: grid-template-rows 0.35s ease, margin-top 0.35s ease;
  }

  .basic-infos-bar.desktop .status-value-wrapper.collapsed {
    grid-template-rows: 0fr;
    margin-top: 0;
  }

  .basic-infos-bar.desktop .status-value {
    font-size: var(--font-size-p);
    font-weight: 500;
    color: var(--color-grey-70);
    line-height: 1.2;
    /* Required for grid height-collapse trick */
    overflow: hidden;
    min-height: 0;
    transition: opacity 0.35s ease;
  }

  .basic-infos-bar.desktop .status-value.fading,
  .basic-infos-bar.desktop .status-value-wrapper.collapsed .status-value {
    opacity: 0;
  }

  /* Processing shimmer animation for status text */
  .basic-infos-bar.desktop .status-value.processing-shimmer {
    background: linear-gradient(
      90deg,
      var(--color-grey-70) 0%,
      var(--color-grey-70) 40%,
      var(--color-grey-50) 50%,
      var(--color-grey-70) 60%,
      var(--color-grey-70) 100%
    );
    background-size: 200% 100%;
    background-clip: text;
    -webkit-background-clip: text;
    color: transparent;
    animation: shimmer 1.5s infinite linear;
  }
  
  @keyframes shimmer {
    0% {
      background-position: 200% 0;
    }
    100% {
      background-position: -200% 0;
    }
  }
  
  /* Single line mode: center the label vertically */
  .basic-infos-bar.desktop .status-text.single-line {
    justify-content: center;
  }
  
  .basic-infos-bar.desktop .status-text.single-line .status-label {
    font-size: var(--font-size-p);
    line-height: 1.4;
  }
  
  /* Stop button - aligned to the right with no extra spacing */
  /* Override global button styles from buttons.css */
  .basic-infos-bar.desktop .stop-button {
    width: 40px;
    height: 40px;
    background: none !important;
    background-color: transparent !important;
    border: none !important;
    padding: 0 !important;
    margin-left: auto !important;
    margin-right: 10px !important;
    min-width: auto !important;
    filter: none !important;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    border-radius: 50%;
    transition: background-color var(--duration-normal);
  }
  
  .basic-infos-bar.desktop .stop-button:hover {
    background-color: rgba(0, 0, 0, 0.05) !important;
    scale: 1 !important; /* Override scale: 1.02 from buttons.css */
  }
  
  .basic-infos-bar.desktop .stop-button:active {
    background-color: rgba(0, 0, 0, 0.05) !important;
    scale: 1 !important; /* Override scale: 0.98 from buttons.css */
    filter: none !important;
  }
  
  /* Stop button icon - red color matching MessageInput stop button */
  /* Includes pulsing animation while processing to indicate interactive state */
  .basic-infos-bar.desktop .stop-button .clickable-icon.icon_stop_processing {
    width: 35px;
    height: 35px;
    background: red !important;
    transition: background var(--duration-normal) var(--easing-default);
    /* Ensure mask-image is properly applied */
    -webkit-mask-size: contain;
    mask-size: contain;
    -webkit-mask-position: center;
    mask-position: center;
    -webkit-mask-repeat: no-repeat;
    mask-repeat: no-repeat;
    /* Pulsing animation for processing state */
    animation: stopButtonPulse 1.2s ease-in-out infinite;
  }
  
  .basic-infos-bar.desktop .stop-button:hover .clickable-icon.icon_stop_processing {
    background: darkred !important;
    /* Pause animation on hover for better UX */
    animation-play-state: paused;
  }
  
  /* Pulsing animation for stop button - subtle opacity changes */
  @keyframes stopButtonPulse {
    0%, 100% {
      opacity: 1;
    }
    50% {
      opacity: 0.5;
    }
  }
  
  /* ===========================================
     Basic Infos Bar - Mobile Layout
     =========================================== */
  
  .basic-infos-bar.mobile {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: var(--spacing-4);
    padding: 13px;
  }
  
  /* App icon container: full width, 44px height, gradient background */
  .basic-infos-bar.mobile .app-icon-container {
    width: 100%;
    height: 44px;
    border-radius: 22px;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
  }
  
  .basic-infos-bar.mobile .app-icon-container .icon_rounded {
    width: 26px;
    height: 26px;
    position: relative;
    bottom: auto;
    left: auto;
    z-index: auto;
  }
  
  .basic-infos-bar.mobile .app-icon-container .icon_rounded::after {
    background-size: 16px 16px;
    filter: brightness(0) invert(1);
  }
  
  .basic-infos-bar.mobile .app-icon-container .icon_rounded {
    background: transparent !important;
  }
  
  /* Mobile favicon image */
  .basic-infos-bar.mobile .favicon-image-mobile {
    width: 20px;
    height: 20px;
    border-radius: var(--radius-1);
    object-fit: cover;
  }
  
  /* Skill icon container (centered) */
  .basic-infos-bar.mobile .skill-icon-container {
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
  }
  
  .basic-infos-bar.mobile .skill-icon-container .skill-icon {
    width: 29px;
    height: 29px;
    background-color: var(--color-grey-70);
    -webkit-mask-position: center;
    mask-position: center;
    -webkit-mask-repeat: no-repeat;
    mask-repeat: no-repeat;
    -webkit-mask-size: contain;
    mask-size: contain;
  }
  
  /* Status text container (centered) */
  .basic-infos-bar.mobile .status-text-container {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    text-align: center;
    /* gap handled by margin-top on .status-value-wrapper for smooth collapse animation */
    flex-shrink: 0;
  }
  
  .basic-infos-bar.mobile .status-text-container .status-label {
    font-size: var(--font-size-small);
    font-weight: 600;
    color: var(--color-grey-100);
    line-height: 1.2;
  }
  
  /* Collapsible wrapper for the status-value line (mobile) */
  .basic-infos-bar.mobile .status-text-container .status-value-wrapper {
    display: grid;
    grid-template-rows: 1fr;
    margin-top: var(--spacing-1);
    transition: grid-template-rows 0.35s ease, margin-top 0.35s ease;
  }

  .basic-infos-bar.mobile .status-text-container .status-value-wrapper.collapsed {
    grid-template-rows: 0fr;
    margin-top: 0;
  }

  .basic-infos-bar.mobile .status-text-container .status-value {
    font-size: var(--font-size-xxs);
    font-weight: 500;
    color: var(--color-grey-70);
    line-height: 1.2;
    overflow: hidden;
    min-height: 0;
    transition: opacity 0.35s ease;
  }

  .basic-infos-bar.mobile .status-text-container .status-value.fading,
  .basic-infos-bar.mobile .status-text-container .status-value-wrapper.collapsed .status-value {
    opacity: 0;
  }

  /* Processing shimmer animation for status text (mobile) */
  .basic-infos-bar.mobile .status-text-container .status-value.processing-shimmer {
    background: linear-gradient(
      90deg,
      var(--color-grey-70) 0%,
      var(--color-grey-70) 40%,
      var(--color-grey-50) 50%,
      var(--color-grey-70) 60%,
      var(--color-grey-70) 100%
    );
    background-size: 200% 100%;
    background-clip: text;
    -webkit-background-clip: text;
    color: transparent;
    animation: shimmer 1.5s infinite linear;
  }
  
  /* Single line mode for mobile */
  .basic-infos-bar.mobile .status-text-container.single-line {
    justify-content: center;
  }
  
  .basic-infos-bar.mobile .status-text-container.single-line .status-label {
    font-size: var(--font-size-small);
    line-height: 1.4;
  }
  
  /* Stop button in mobile (centered) */
  /* Override global button styles from buttons.css */
  .basic-infos-bar.mobile .stop-button {
    width: 40px;
    height: 40px;
    margin-top: auto;
    margin-right: 0 !important; /* Override margin-right: 10px from buttons.css */
    background: none !important;
    background-color: transparent !important;
    border: none !important;
    padding: 0 !important;
    min-width: auto !important;
    filter: none !important;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 50%;
    transition: background-color var(--duration-normal);
  }
  
  .basic-infos-bar.mobile .stop-button:hover {
    background-color: rgba(0, 0, 0, 0.05) !important;
    scale: 1 !important; /* Override scale: 1.02 from buttons.css */
  }
  
  .basic-infos-bar.mobile .stop-button:active {
    background-color: rgba(0, 0, 0, 0.05) !important;
    scale: 1 !important; /* Override scale: 0.98 from buttons.css */
    filter: none !important;
  }
  
  /* Stop button icon - red color matching MessageInput stop button */
  /* Includes pulsing animation while processing to indicate interactive state */
  .basic-infos-bar.mobile .stop-button .clickable-icon.icon_stop_processing {
    width: 35px;
    height: 35px;
    background: red !important;
    transition: background var(--duration-normal) var(--easing-default);
    /* Ensure mask-image is properly applied */
    -webkit-mask-size: contain;
    mask-size: contain;
    -webkit-mask-position: center;
    mask-position: center;
    -webkit-mask-repeat: no-repeat;
    mask-repeat: no-repeat;
    /* Pulsing animation for processing state */
    animation: stopButtonPulse 1.2s ease-in-out infinite;
  }
  
  .basic-infos-bar.mobile .stop-button:hover .clickable-icon.icon_stop_processing {
    background: darkred !important;
    /* Pause animation on hover for better UX */
    animation-play-state: paused;
  }
</style>

