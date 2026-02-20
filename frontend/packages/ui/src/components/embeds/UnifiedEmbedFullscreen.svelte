<!--
  frontend/packages/ui/src/components/embeds/UnifiedEmbedFullscreen.svelte
  
  Unified base component for all embed fullscreen views (app skills, websites, etc.)
  
  Structure:
  - Top bar with action buttons (share, close)
  - Header section with title and optional extra content via snippet
  - Main content area (scrollable) with skill-specific content via snippet
  - Bottom preview bar with app icon and title
  
  Animations:
  - Opening: Scale up from 0.5 to 1.0 with opacity fade (originates from preview position)
  - Closing: Scale down to 0.5 with opacity fade (back to preview position)
  - CSS variables --preview-center-x and --preview-center-y set by UnifiedEmbedPreview
    determine the transform-origin for smooth origin-based animations
  
  Child Embed Loading:
  - For fullscreens that display multiple child embeds (e.g., search results)
  - Pass embedIds prop (pipe-separated string or array) to auto-load children
  - Child embeds are fetched from embedStore and TOON content is decoded
  - Optional childEmbedTransformer function to transform raw embed data
  - Children are passed to content snippet as { children, isLoadingChildren }
  
  Similar to UnifiedEmbedPreview but for fullscreen views.
-->

<script lang="ts">
  import { onMount, onDestroy, tick } from 'svelte';
  import { text } from '@repo/ui';
  import BasicInfosBar from './BasicInfosBar.svelte';
  import { panelState } from '../../stores/panelStateStore';
  import { settingsDeepLink } from '../../stores/settingsDeepLinkStore';
  import { settingsMenuVisible } from '../Settings.svelte';
  import { resolveEmbed, decodeToonContent } from '../../services/embedResolver';
  import { chatSyncService } from '../../services/chatSyncService';
  
  // Animation state: controls both open and close animations via CSS classes
  // - false: collapsed state (initial + closing)
  // - true: expanded state (after mount animation completes)
  let isAnimatingIn = $state(false);
  
  // Track if we're in the process of closing (for animation timing)
  let isClosing = $state(false);
  
  /**
   * Context passed to the content snippet when child embeds are used
   * Provides loaded children and loading state
   * 
   * Note: children is typed as unknown[] because Svelte props don't support
   * TypeScript generics properly. Each fullscreen component should cast
   * children to their specific result type.
   */
  export interface ChildEmbedContext {
    /** Array of loaded child embeds (transformed if transformer provided) */
    children: unknown[];
    /** Whether child embeds are still loading */
    isLoadingChildren: boolean;
    /** Legacy results prop for backwards compatibility */
    legacyResults?: unknown[];
  }
  
  /**
   * Props interface for unified embed fullscreen
   * 
   * Child Embed Loading:
   * - Pass embedIds to automatically load child embeds from embedStore
   * - Optionally provide childEmbedTransformer to transform raw embed data
   * - Children are available in content snippet via context parameter
   */
  interface Props {
    /** App identifier (e.g., 'web', 'videos', 'code') - used for icon display */
    appId: string;
    /** Skill identifier (e.g., 'search', 'get_transcript') */
    skillId?: string;
    /** Fullscreen title */
    title: string;
    /** Close handler */
    onClose: () => void;
    /** Optional copy handler (for copy button) - copies text version of embed */
    onCopy?: () => void;
    /** Optional download handler (for download button) - downloads the embed */
    onDownload?: () => void;
    /** Optional share handler - opens share menu for the embed */
    onShare?: () => void;
    /**
     * Whether to show the share button (default: true).
     * Set to false to hide it for embeds that cannot be shared (e.g. non-uploaded images).
     */
    showShare?: boolean;
    /** Snippet for header extra content (optional) */
    headerExtra?: import('svelte').Snippet<[]>;
    /** 
     * Snippet for main content
     * When embedIds is provided, receives ChildEmbedContext with loaded children
     * Otherwise receives empty context for backwards compatibility
     */
    content?: import('svelte').Snippet<[ChildEmbedContext]>;
    /** Snippet for bottom bar (optional, defaults to basic infos bar) */
    bottomBar?: import('svelte').Snippet<[]>;
    
    /* ============================================
       Child Embed Loading Props
       ============================================ */
    
    /** 
     * Pipe-separated embed IDs or array of child embed IDs to load
     * When provided, child embeds are automatically fetched from embedStore
     */
    embedIds?: string | string[];
    
    /**
     * Optional transformer function to convert raw embed data to desired format
     * Receives embed_id and decoded content, returns transformed object
     * If not provided, returns raw { embed_id, content, embed_type } objects
     */
    childEmbedTransformer?: (embedId: string, content: Record<string, unknown>) => unknown;
    
    /**
     * Legacy results prop for backwards compatibility
     * If embedIds not provided, these are passed through to content snippet
     */
    legacyResults?: unknown[];

    /**
     * Optional callback fired when child embeds finish loading.
     * Use this to trigger side effects (e.g. map initialization) that depend on
     * loaded children, avoiding the anti-pattern of mutating state inside the template.
     */
    onChildrenLoaded?: (children: unknown[]) => void;
    
    /* ============================================
       BasicInfosBar Props (when bottomBar not provided)
       ============================================ */
    
    /** Skill icon name for BasicInfosBar */
    skillIconName?: string;
    /** Processing status for BasicInfosBar */
    status?: 'processing' | 'finished' | 'error';
    /** Skill display name for BasicInfosBar */
    skillName?: string;
    /** Task ID for BasicInfosBar */
    taskId?: string;
    /** Click handler for BasicInfosBar */
    onBasicInfosBarClick?: () => void;
    /** Custom favicon URL for BasicInfosBar */
    faviconUrl?: string;
    /** Whether favicon should be circular (for channel thumbnails, profile pics) */
    faviconIsCircular?: boolean;
    /** Whether to show skill icon in BasicInfosBar */
    showSkillIcon?: boolean;
    /** Custom status text for BasicInfosBar */
    customStatusText?: string;
    /** Whether to show status text in BasicInfosBar */
    showStatus?: boolean;
    
    /* ============================================
       Embed Navigation Props
       ============================================ */
    
    /** Whether there is a previous embed to navigate to */
    hasPreviousEmbed?: boolean;
    /** Whether there is a next embed to navigate to */
    hasNextEmbed?: boolean;
    /** Handler to navigate to the previous embed */
    onNavigatePrevious?: () => void;
    /** Handler to navigate to the next embed */
    onNavigateNext?: () => void;
    
    /* ============================================
       Embed Data Update Props (for reactive updates during streaming)
       ============================================ */
    
    /**
     * Current embed ID being displayed (for subscription to updates)
     * When provided, subscribes to embedUpdated events for this embed
     * and calls onEmbedDataUpdated when data changes
     */
    currentEmbedId?: string;
    
    /**
     * Callback when embed data is updated (e.g., during streaming)
     * Called with decoded content when the embed is updated
     * Similar to UnifiedEmbedPreview's onEmbedDataUpdated
     */
    onEmbedDataUpdated?: (data: { status: string; decodedContent: Record<string, unknown>; results?: unknown[] }) => void;
    
    /* ============================================
       Chat Toggle Props (for side-by-side mode)
       ============================================ */
    
    /**
     * Whether to show the "chat" button to restore chat visibility
     * Only shown when chat is hidden (forceOverlayMode is true on ultra-wide screens)
     */
    showChatButton?: boolean;
    
    /**
     * Callback when user clicks the "chat" button to restore chat visibility
     * This toggles forceOverlayMode back to false in ActiveChat
     */
    onShowChat?: () => void;

    /* ============================================
       PII Toggle Props (for sensitive data masking)
       ============================================ */

    /**
     * Whether to show the PII hide/show toggle button in the top bar.
     * Only shown when the embed content contains sensitive PII data.
     */
    showPIIToggle?: boolean;

    /**
     * Whether PII originals are currently revealed (true = sensitive data visible).
     * Controls the active/inactive visual state of the toggle button.
     */
    piiRevealed?: boolean;

    /**
     * Callback when user clicks the PII toggle button.
     * The parent component is responsible for updating piiRevealed state.
     */
    onTogglePII?: () => void;
  }
  
  let {
    appId,
    skillId,
    title,
    onClose,
    onCopy,
    onDownload,
    onShare,
    showShare = true,
    headerExtra,
    content,
    bottomBar,
    // Child embed loading props
    embedIds,
    childEmbedTransformer,
    legacyResults,
    // BasicInfosBar props
    skillIconName = '',
    status = 'finished',
    skillName,
    taskId,
    onBasicInfosBarClick,
    faviconUrl,
    faviconIsCircular = false,
    showSkillIcon = true,
    customStatusText,
    showStatus = true,
    // Embed navigation props
    hasPreviousEmbed = false,
    hasNextEmbed = false,
    onNavigatePrevious,
    onNavigateNext,
    // Child embed loading callback
    onChildrenLoaded,
    // Embed data update props
    currentEmbedId,
    onEmbedDataUpdated,
    // Chat toggle props (for side-by-side mode)
    showChatButton = false,
    onShowChat,
    // PII toggle props (for sensitive data masking)
    showPIIToggle = false,
    piiRevealed = false,
    onTogglePII
  }: Props = $props();
  
  // ============================================
  // Child Embed Loading State
  // ============================================
  
  /** Loaded child embeds (transformed if transformer provided) */
  let loadedChildren = $state<unknown[]>([]);
  
  /** Whether child embeds are currently being loaded */
  let isLoadingChildren = $state(false);
  
  /**
   * Load child embeds from embedStore
   * Parses embedIds, fetches each embed, decodes TOON content, and optionally transforms
   */
  async function loadChildEmbeds() {
    // Parse embed_ids - can be pipe-separated string or array
    let embedIdList: string[] = [];
    if (typeof embedIds === 'string' && embedIds.trim()) {
      embedIdList = embedIds.split('|').filter(id => id.trim());
    } else if (Array.isArray(embedIds)) {
      embedIdList = embedIds.filter(id => id && typeof id === 'string');
    }
    
    // If no embed IDs, skip loading (use legacyResults if provided)
    if (embedIdList.length === 0) {
      console.debug('[UnifiedEmbedFullscreen] ⚠️ No embedIds to load - checking why:', {
        appId,
        skillId,
        embedIdsProp: embedIds,
        embedIdsPropType: typeof embedIds,
        embedIdsPropLength: Array.isArray(embedIds) ? embedIds.length : (typeof embedIds === 'string' ? embedIds.length : 0),
        legacyResultsCount: legacyResults?.length || 0
      });
      isLoadingChildren = false;
      return;
    }
    
    isLoadingChildren = true;
    console.debug('[UnifiedEmbedFullscreen] Loading child embeds:', {
      appId,
      skillId,
      embedIdCount: embedIdList.length
    });
    
    const children: unknown[] = [];
    
    for (const childEmbedId of embedIdList) {
      try {
        // Fetch embed using resolveEmbed which checks BOTH:
        // - Regular embedStore (for encrypted user embeds)
        // - communityDemoStore (for cleartext demo chat embeds)
        // This is critical for demo chats where embeds are stored separately.
        const embedData = await resolveEmbed(childEmbedId);
        if (!embedData) {
          console.warn('[UnifiedEmbedFullscreen] Child embed not found:', childEmbedId);
          continue;
        }
        
        // Decode TOON content if needed
        // decodedContent starts as string (TOON-encoded) and gets decoded to object
        let decodedContent: Record<string, unknown> | null = null;
        
        // Debug: Log raw content before decoding
        console.debug('[UnifiedEmbedFullscreen] Child embed raw content:', {
          childEmbedId,
          contentType: typeof embedData.content,
          isString: typeof embedData.content === 'string',
          contentPreview: typeof embedData.content === 'string' ? embedData.content.substring(0, 200) : 'not a string'
        });
        
        if (typeof embedData.content === 'string') {
          decodedContent = await decodeToonContent(embedData.content);
        } else if (typeof embedData.content === 'object' && embedData.content !== null) {
          // Content might already be decoded (e.g., from demo embeds)
          decodedContent = embedData.content as Record<string, unknown>;
        }
        
        // Debug: Log decoded content
        console.debug('[UnifiedEmbedFullscreen] Child embed decoded content:', {
          childEmbedId,
          contentKeys: decodedContent ? Object.keys(decodedContent) : [],
          extra_snippets: decodedContent?.extra_snippets,
          extra_snippets_type: typeof decodedContent?.extra_snippets
        });
        
        if (!decodedContent) {
          console.warn('[UnifiedEmbedFullscreen] Failed to decode child embed content:', childEmbedId);
          continue;
        }
        
        // Transform or create raw ChildEmbed
        if (childEmbedTransformer) {
          // Use custom transformer
          const transformed = childEmbedTransformer(childEmbedId, decodedContent);
          children.push(transformed);
        } else {
          // Return raw embed data object
          const childEmbed = {
            embed_id: childEmbedId,
            content: decodedContent,
            embed_type: embedData.type // Use 'type' from EmbedData (not 'embed_type')
          };
          children.push(childEmbed);
        }
        
        console.debug('[UnifiedEmbedFullscreen] Loaded child embed:', childEmbedId);
      } catch (error) {
        console.error('[UnifiedEmbedFullscreen] Error loading child embed:', childEmbedId, error);
      }
    }
    
    loadedChildren = children;
    isLoadingChildren = false;
    console.debug('[UnifiedEmbedFullscreen] Finished loading', children.length, 'child embeds');

    // Notify parent component that children finished loading (e.g. for map initialization)
    if (children.length > 0 && onChildrenLoaded) {
      onChildrenLoaded(children);
    }
  }
  
  // ============================================
  // Embed Data Update Subscription (for reactive updates during streaming)
  // ============================================
  
  /** Event listener for embed updates - stored for cleanup */
  let embedUpdateListener: ((e: CustomEvent) => void) | null = null;
  
  /**
   * Handle embed updates from chatSyncService
   * When an embedUpdated event fires for the current embed ID, refetch data from store
   * and notify the parent component via onEmbedDataUpdated callback
   */
  function handleEmbedUpdate(event: CustomEvent) {
    // Check if this update is for our embed
    const { embed_id, contentRef, status: newStatus } = event.detail;
    const matchesEmbedId = embed_id === currentEmbedId;
    const matchesContentRef = contentRef === `embed:${currentEmbedId}`;
    
    if (!matchesEmbedId && !matchesContentRef) {
      return;
    }
    
    console.debug(`[UnifiedEmbedFullscreen] 🔄 Received embedUpdated for ${currentEmbedId}:`, {
      newStatus,
      embed_id,
      contentRef
    });
    
    // Refetch from store to get full data and notify parent component
    refetchCurrentEmbed();
  }
  
  /**
   * Refetch current embed data from the store and notify parent via callback
   * This ensures we have the latest data after an update during streaming
   * 
   * NOTE: Uses resolveEmbed() which checks BOTH:
   * - Regular embedStore (for encrypted user embeds)
   * - communityDemoStore (for cleartext demo chat embeds)
   * This is critical for demo chats where embeds are stored separately.
   */
  async function refetchCurrentEmbed() {
    if (!currentEmbedId || !onEmbedDataUpdated) {
      return;
    }
    
    try {
      const embedData = await resolveEmbed(currentEmbedId);
      if (!embedData) {
        console.warn(`[UnifiedEmbedFullscreen] Embed not found in store: ${currentEmbedId}`);
        return;
      }
      
      console.debug(`[UnifiedEmbedFullscreen] Refetched data from store for ${currentEmbedId}:`, {
        status: embedData.status,
        hasContent: !!embedData.content
      });
      
      // Decode TOON content if needed
      // decodedContent starts as string (TOON-encoded) and gets decoded to object
      let decodedContent: Record<string, unknown> | null = null;
      if (typeof embedData.content === 'string') {
        decodedContent = await decodeToonContent(embedData.content);
      } else if (typeof embedData.content === 'object' && embedData.content !== null) {
        // Content might already be decoded (e.g., from demo embeds)
        decodedContent = embedData.content as Record<string, unknown>;
      }
      
      // Notify parent component with decoded content and results
      // Results are extracted from the decoded content (embed_ids field)
      if (decodedContent) {
        onEmbedDataUpdated({
          status: embedData.status || 'processing',
          decodedContent: decodedContent,
          results: (decodedContent?.results as unknown[]) || undefined
        });
      }
    } catch (error) {
      console.error(`[UnifiedEmbedFullscreen] Error refetching from store for ${currentEmbedId}:`, error);
    }
  }
  
  /**
   * Context object passed to content snippet
   * Contains loaded children and loading state
   */
  let childEmbedContext = $derived<ChildEmbedContext>({
    children: loadedChildren,
    isLoadingChildren,
    legacyResults
  });
  
  // DEBUG: Log when content snippet is missing - this helps identify which embed is broken
  $effect(() => {
    if (!content) {
      console.error('[UnifiedEmbedFullscreen] MISSING content snippet! This will cause rendering issues.', {
        appId,
        skillId,
        title
      });
    }
  });
  
  // Handle smooth closing animation
  // Uses CSS class-based animation for consistent behavior
  // The animation is controlled by removing the 'animating-in' class
  function handleClose() {
    // Prevent double-close
    if (isClosing) return;
    isClosing = true;
    
    // Toggle animation state to trigger CSS transition (scale down + fade out)
    isAnimatingIn = false;
    
    // Wait for animation to complete before calling onClose
    // Animation duration is 300ms (matches CSS transition)
    setTimeout(() => {
      onClose();
    }, 300);
  }
  
  /**
   * Built-in share handler: opens the share settings panel for this embed.
   * If a custom onShare handler is provided by the parent, it delegates to that.
   * Otherwise, it uses appId, skillId, and currentEmbedId to construct the
   * embed share context automatically. This avoids duplicating the same share
   * boilerplate in every fullscreen component.
   */
  async function handleShare() {
    // Delegate to custom handler if provided
    if (onShare) {
      onShare();
      return;
    }
    
    // Built-in share: requires currentEmbedId to generate an encrypted share link
    if (!currentEmbedId) {
      console.debug('[UnifiedEmbedFullscreen] Share action skipped - no currentEmbedId available');
      return;
    }
    
    try {
      console.debug('[UnifiedEmbedFullscreen] Opening share settings for embed:', {
        embedId: currentEmbedId,
        appId,
        skillId
      });
      
      // Import navigateToSettings dynamically (only needed on share click)
      const { navigateToSettings } = await import('../../stores/settingsNavigationStore');
      
      // Build embed context with available metadata
      const embedContext: Record<string, unknown> = {
        type: `${appId}_${skillId || 'embed'}`,
        embed_id: currentEmbedId
      };
      
      // Store embed context on window for SettingsShare to pick up
      (window as unknown as { __embedShareContext?: unknown }).__embedShareContext = embedContext;
      
      // Build a translation key for the share title (e.g., 'settings.share.share_images_generate')
      const shareTranslationKey = `settings.share.share_${appId}_${skillId || 'embed'}`;
      const shareTitle = `Share ${appId} ${skillId || 'embed'}`;
      
      // Navigate to share settings
      navigateToSettings('shared/share', shareTitle, 'share', shareTranslationKey);
      
      // CRITICAL: Set settingsMenuVisible FIRST so the Settings component syncs
      // its local isMenuVisible state and sets the grace period for the
      // click-outside handler. Without this, on mobile the tap event that
      // triggered this share handler will bubble to the document click-outside
      // handler, which sees the click originated outside the settings DOM and
      // immediately closes the panel.
      settingsMenuVisible.set(true);
      
      // Also open via panelState for consistency
      panelState.openSettings();
      
      // Wait for store update to propagate and DOM to update before setting
      // the deep link. This ensures the Settings component's effect has time
      // to sync isMenuVisible and the menu is actually visible in the DOM.
      await tick();
      await new Promise(resolve => setTimeout(resolve, 100));
      
      // Set deep link AFTER the menu is open to ensure proper navigation
      settingsDeepLink.set('shared/share');
      
      console.debug('[UnifiedEmbedFullscreen] Opened share settings for embed');
    } catch (error) {
      console.error('[UnifiedEmbedFullscreen] Error opening share settings:', error);
    }
  }
  
  // Handle copy action - copies text version of embed to clipboard
  function handleCopy() {
    if (onCopy) {
      onCopy();
    } else {
      console.debug('[UnifiedEmbedFullscreen] Copy action (no handler provided)');
    }
  }
  
  // Handle download action - downloads the embed
  function handleDownload() {
    if (onDownload) {
      onDownload();
    } else {
      console.debug('[UnifiedEmbedFullscreen] Download action (no handler provided)');
    }
  }
  
  // Handle navigate to previous embed
  function handleNavigatePrevious() {
    if (onNavigatePrevious && hasPreviousEmbed) {
      console.debug('[UnifiedEmbedFullscreen] Navigating to previous embed');
      onNavigatePrevious();
    }
  }
  
  // Handle navigate to next embed
  function handleNavigateNext() {
    if (onNavigateNext && hasNextEmbed) {
      console.debug('[UnifiedEmbedFullscreen] Navigating to next embed');
      onNavigateNext();
    }
  }
  
  // Handle show chat action - restores chat visibility in side-by-side mode
  // Called when user clicks the "chat" button to toggle back to side-by-side layout
  function handleShowChatClick() {
    if (onShowChat) {
      console.debug('[UnifiedEmbedFullscreen] Show chat button clicked - restoring chat visibility');
      onShowChat();
    } else {
      console.debug('[UnifiedEmbedFullscreen] Show chat action (no handler provided)');
    }
  }
  
  // Handle report issue action - opens settings with report issue page
  // The SettingsReportIssue component will auto-generate the embed share URL
  async function handleReportIssue() {
    console.debug('[UnifiedEmbedFullscreen] Opening report issue settings');
    
    // Open settings menu
    panelState.openSettings();
    
    // Wait for settings to open, then navigate to report issue page
    await new Promise(resolve => setTimeout(resolve, 100));
    
    // Set deep link to report issue page
    // SettingsReportIssue will auto-generate the embed share URL from activeEmbedStore
    settingsDeepLink.set('report_issue');
    
    console.debug('[UnifiedEmbedFullscreen] Report issue settings opened');
  }
  
  // Close fullscreen when user switches to a different chat
  function handleChatSelected() {
    console.debug('[UnifiedEmbedFullscreen] Chat selected, closing fullscreen');
    onClose(); // Close immediately without animation for smoother UX
  }
  
  onMount(() => {
    // Listen for chat selection events to close fullscreen
    window.addEventListener('globalChatSelected', handleChatSelected);
    
    // Subscribe to embed updates if currentEmbedId is provided
    // This enables reactive updates during streaming
    if (currentEmbedId && onEmbedDataUpdated) {
      console.debug(`[UnifiedEmbedFullscreen] Subscribing to embedUpdated for ${currentEmbedId}`);
      embedUpdateListener = handleEmbedUpdate;
      // Type-safe event listener subscription
      const service = chatSyncService as unknown as { 
        addEventListener: (type: string, listener: (e: CustomEvent) => void) => void 
      };
      service.addEventListener('embedUpdated', embedUpdateListener);
      
      // Initial fetch to ensure we have the latest data
      refetchCurrentEmbed();
    }
    
    // Load child embeds if embedIds is provided
    if (embedIds) {
      loadChildEmbeds();
    }
    
    // Trigger opening animation after a brief delay to ensure initial styles are applied
    // This creates a smooth scale-up animation from the preview position
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        isAnimatingIn = true;
      });
    });
  });
  
  onDestroy(() => {
    window.removeEventListener('globalChatSelected', handleChatSelected);
    
    // Clean up embed update listener
    if (embedUpdateListener) {
      const service = chatSyncService as unknown as { 
        removeEventListener: (type: string, listener: (e: CustomEvent) => void) => void 
      };
      service.removeEventListener('embedUpdated', embedUpdateListener);
      embedUpdateListener = null;
    }
  });
</script>

<div
  class="unified-embed-fullscreen-overlay"
  class:animating-in={isAnimatingIn}
  style="--preview-center-x: var(--preview-center-x, 50vw); --preview-center-y: var(--preview-center-y, 50vh);"
>
  <div class="fullscreen-container">
    <!-- Top bar with action buttons -->
    <div class="top-bar">
      <!-- Left side: Chat button (when hidden), Previous button, Share, Copy, Download, Report Issue buttons -->
      <div class="top-bar-left">
        <!-- Show Chat button - only shown when chat is hidden (forceOverlayMode active on ultra-wide) -->
        <!-- Allows user to restore the side-by-side layout -->
        {#if showChatButton && onShowChat}
          <div class="button-wrapper">
            <button
              class="action-button chat-button"
              onclick={handleShowChatClick}
              aria-label={$text('chat.show_chat')}
              title={$text('chat.show_chat')}
            >
              <span class="clickable-icon icon_chat"></span>
            </button>
          </div>
        {/if}
        <!-- Previous embed navigation button - only shown if there is a previous embed -->
        {#if hasPreviousEmbed && onNavigatePrevious}
          <div class="button-wrapper nav-button-wrapper">
            <button
              class="action-button nav-button nav-previous"
              onclick={handleNavigatePrevious}
              aria-label="Previous embed"
              title="Previous embed"
            >
              <span class="clickable-icon icon_back"></span>
            </button>
          </div>
        {/if}
        <!-- Share button - shown by default, can be hidden via showShare=false -->
        {#if showShare}
          <div class="button-wrapper">
            <button
              class="action-button share-button"
              onclick={handleShare}
              aria-label={$text('chat.share')}
              title={$text('chat.share')}
            >
              <span class="clickable-icon icon_share"></span>
            </button>
          </div>
        {/if}
        <!-- Copy button -->
        {#if onCopy}
          <div class="button-wrapper">
            <button
              class="action-button copy-button"
              onclick={handleCopy}
              aria-label="Copy"
              title="Copy"
            >
              <span class="clickable-icon icon_copy"></span>
            </button>
          </div>
        {/if}
        <!-- Download button -->
        {#if onDownload}
          <div class="button-wrapper">
            <button
              class="action-button download-button"
              onclick={handleDownload}
              aria-label="Download"
              title="Download"
            >
              <span class="clickable-icon icon_download"></span>
            </button>
          </div>
        {/if}
          <!-- Report Issue button - always shown -->
          <div class="button-wrapper">
            <button
              class="action-button report-issue-button"
              onclick={handleReportIssue}
              aria-label={$text('header.report_issue')}
              title={$text('header.report_issue')}
            >
              <span class="clickable-icon icon_bug"></span>
            </button>
          </div>
          <!-- PII hide/show toggle - only shown when embed has sensitive data -->
          {#if showPIIToggle && onTogglePII}
            <div class="button-wrapper">
              <button
                class="action-button pii-toggle-button"
                class:pii-toggle-active={piiRevealed}
                onclick={onTogglePII}
                aria-label={piiRevealed ? $text('embeds.pii_hide') : $text('embeds.pii_show')}
                title={piiRevealed ? $text('embeds.pii_hide') : $text('embeds.pii_show')}
              >
                <span class="clickable-icon {piiRevealed ? 'icon_visible' : 'icon_hidden'}"></span>
              </button>
            </div>
          {/if}
      </div>
      
      <!-- Right side: Next button and Minimize button -->
      <div class="top-bar-right">
        <!-- Next embed navigation button - only shown if there is a next embed -->
        {#if hasNextEmbed && onNavigateNext}
          <div class="button-wrapper nav-button-wrapper">
            <button
              class="action-button nav-button nav-next"
              onclick={handleNavigateNext}
              aria-label="Next embed"
              title="Next embed"
            >
              <span class="clickable-icon icon_back icon_forward"></span>
            </button>
          </div>
        {/if}
        <div class="button-wrapper">
          <button
            class="action-button minimize-button"
            onclick={handleClose}
            aria-label="Minimize"
            title="Minimize"
          >
            <span class="clickable-icon icon_minimize"></span>
          </button>
        </div>
      </div>
    </div>
    
    <!-- Header with title and optional extra content (only show if title is provided and not empty) -->
    {#if title?.trim() && headerExtra}
      <div class="header">
        <div class="title">{title}</div>
        {@render headerExtra()}
      </div>
    {:else if title?.trim()}
      <div class="header">
        <div class="title">{title}</div>
      </div>
    {/if}
    
    <!-- Main content area (scrollable) - with defensive guard -->
    <div class="content-area">
      {#if content}
        <!-- Pass child embed context to content snippet -->
        {@render content(childEmbedContext)}
      {:else}
        <!-- Fallback when content snippet is missing -->
        <div class="missing-content-fallback">
          <p>Content unavailable</p>
        </div>
      {/if}
    </div>
    
    <!-- Bottom gradient and BasicInfosBar -->
    <div class="bottom-gradient-wrapper">
      <!-- Gradient fade from transparent to grey-0 -->
      <div class="bottom-gradient"></div>
      
      <!-- Bottom bar (BasicInfosBar or custom) -->
      <div class="bottom-bar-container">
        {#if bottomBar}
          {@render bottomBar()}
        {:else if skillName && skillId}
          <!-- Default BasicInfosBar with same content as embed preview -->
          {#if onBasicInfosBarClick}
            <button 
              class="basic-infos-bar-wrapper clickable"
              onclick={onBasicInfosBarClick}
              type="button"
            >
              <BasicInfosBar
                {appId}
                {skillId}
                skillIconName={skillIconName || skillId}
                {status}
                {skillName}
                {taskId}
                {faviconUrl}
                {faviconIsCircular}
                {showSkillIcon}
                {customStatusText}
                {showStatus}
              />
            </button>
          {:else}
            <div class="basic-infos-bar-wrapper">
              <BasicInfosBar
                {appId}
                {skillId}
                skillIconName={skillIconName || skillId}
                {status}
                {skillName}
                {taskId}
                {faviconUrl}
                {faviconIsCircular}
                {showSkillIcon}
                {customStatusText}
                {showStatus}
              />
            </div>
          {/if}
        {/if}
      </div>
    </div>
  </div>
</div>

<style>
  /* ===========================================
     Unified Embed Fullscreen - Base Container
     =========================================== */
  
  .unified-embed-fullscreen-overlay {
    position: absolute;
    /* Fill the entire parent container - no margins needed */
    /* In overlay mode, this fills the ActiveChat container */
    /* In side-panel mode, this fills the fullscreen-embed-container */
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    background-color: var(--color-grey-20);
    border-radius: 17px;
    box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3);
    z-index: 100;
    display: flex;
    flex-direction: column;
    /* Use CSS variables from preview click position for origin-based animations */
    /* These are set by UnifiedEmbedPreview when opening fullscreen */
    transform-origin: var(--preview-center-x, 50%) var(--preview-center-y, 50%);
    transition: transform 300ms cubic-bezier(0.4, 0, 0.2, 1),
                opacity 300ms cubic-bezier(0.4, 0, 0.2, 1);
    overflow: hidden;
    
    /* Enable container queries so child components can detect their container width */
    container-type: inline-size;
    container-name: fullscreen;
    
    /* Initial state: collapsed and slightly transparent */
    /* This creates the starting point for the opening animation */
    transform: scale(0.5);
    opacity: 0.5;
  }
  
  /* Animated-in state: fully expanded and opaque */
  /* Applied after mount via JS to trigger the opening transition */
  .unified-embed-fullscreen-overlay.animating-in {
    transform: scale(1);
    opacity: 1;
  }
  
  .fullscreen-container {
    display: flex;
    flex-direction: column;
    height: 100%;
    position: relative;
  }
  
  /* Top bar with action buttons - ABSOLUTE position within fullscreen overlay.
     z-index: 1000 ensures it stays above Leaflet map panes (z-index 400+) and
     any other high-z-index children that embed fullscreens may render. */
  .top-bar {
    position: absolute;
    top: 16px;
    left: 16px;
    right: 16px;
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    z-index: 1000;
    pointer-events: none;
  }
  
  .top-bar-left {
    display: flex;
    gap: 8px;
    align-items: center;
    pointer-events: auto;
  }
  
  .top-bar-right {
    display: flex;
    gap: 8px;
    align-items: center;
    pointer-events: auto;
  }
  
  /* Button wrapper - matches new-chat-button-wrapper design from ActiveChat.svelte */
  .button-wrapper {
    background-color: var(--color-grey-10);
    border-radius: 40px;
    padding: 5.5px;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
    display: flex;
    align-items: center;
    justify-content: center;
  }
  
  .action-button {
    width: 40px;
    height: 40px;
    min-width: 40px;
    border: none;
    border-radius: 50%;
    cursor: pointer;
    padding: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    background: transparent;
    transition: background-color 0.2s;
  }
  
  .action-button:hover {
    background-color: rgba(0, 0, 0, 0.05);
  }
  
  /* Icon styling inside action buttons */
  .action-button .clickable-icon {
    width: 24px;
    height: 24px;
  }
  
  /* Navigation buttons - using back icon, forward icon is rotated 180deg */
  .nav-button .icon_forward {
    transform: rotate(180deg);
  }

  /* PII toggle button: subtle orange/amber tint when PII is revealed (warns sensitive data exposed) */
  .pii-toggle-button.pii-toggle-active {
    background-color: rgba(245, 158, 11, 0.3) !important;
  }

  .pii-toggle-button.pii-toggle-active:hover {
    background-color: rgba(245, 158, 11, 0.45) !important;
  }
  
  /* Hide navigation button wrappers on narrow screens (< 500px) to prevent UI crowding */
  /* Uses container query since container-type: inline-size is set on the overlay */
  /* Target the wrapper (not just the button) to hide the entire container including background */
  @container fullscreen (max-width: 500px) {
    .nav-button-wrapper {
      display: none;
    }
  }
  
  /* Header section */
  .header {
    margin-top: 16px;
    margin-bottom: 16px;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  
  .title {
    font-size: 18px;
    font-weight: 500;
    color: var(--color-font-primary);
    line-height: 1.4;
    word-break: break-word;
  }
  
  /* Main content area (scrollable) - scrollable behind the fixed top and bottom bars */
  .content-area {
    flex: 1;
    overflow-y: auto;
    overflow-x: hidden;
    padding-right: 8px;
    margin-right: -8px;
    padding-bottom: 120px; /* Space for absolute positioned bottom bar and gradient */
    scrollbar-width: thin;
    scrollbar-color: rgba(128, 128, 128, 0.2) transparent;
    transition: scrollbar-color 0.2s ease;
  }
  
  .content-area:hover {
    scrollbar-color: rgba(128, 128, 128, 0.5) transparent;
  }
  
  .content-area::-webkit-scrollbar {
    width: 8px;
  }
  
  .content-area::-webkit-scrollbar-track {
    background: transparent;
  }
  
  .content-area::-webkit-scrollbar-thumb {
    background-color: rgba(128, 128, 128, 0.2);
    border-radius: 4px;
    border: 2px solid transparent;
    transition: background-color 0.2s ease;
  }
  
  .content-area:hover::-webkit-scrollbar-thumb {
    background-color: rgba(128, 128, 128, 0.5);
  }
  
  .content-area::-webkit-scrollbar-thumb:hover {
    background-color: rgba(128, 128, 128, 0.7);
  }
  
  /* Bottom gradient and bar wrapper - ABSOLUTE positioned at bottom */
  .bottom-gradient-wrapper {
    position: absolute;
    bottom: 0;
    left: 0;
    right: 0;
    z-index: 3;
    pointer-events: none;
  }
  
  /* Gradient fade from transparent (0%) to grey-20 (100% opacity) - matches fullscreen background */
  .bottom-gradient {
    position: absolute;
    bottom: 0;
    left: 0;
    right: 0;
    height: 120px;
    background: linear-gradient(
      to bottom,
      transparent 0%,
      var(--color-grey-20) 100%
    );
    pointer-events: none;
  }
  
  /* Bottom bar container - centered, full width with 10px padding on each side */
  .bottom-bar-container {
    position: absolute;
    bottom: 0;
    left: 0;
    right: 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 16px 10px;
    pointer-events: auto;
  }
  
  /* BasicInfosBar wrapper - max-width 300px, centered, full viewport width - 20px */
  .basic-infos-bar-wrapper {
    width: calc(100% - 0px); /* Account for parent padding of 10px on each side */
    max-width: 300px;
    border: none;
    background: transparent;
    padding: 0;
    cursor: default;
  }
  
  /* Ensure BasicInfosBar inside wrapper respects max-width and has proper styling */
  .basic-infos-bar-wrapper :global(.basic-infos-bar) {
    width: 100%;
    max-width: 300px;
  }
  
  .basic-infos-bar-wrapper.clickable {
    cursor: pointer;
    transition: opacity 0.2s;
  }
  
  .basic-infos-bar-wrapper.clickable:hover {
    opacity: 0.9;
  }
  
  /* ===========================================
     Fallback for Missing Content Snippet
     =========================================== */
  
  .missing-content-fallback {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 200px;
    color: var(--color-grey-70);
    font-size: 16px;
    text-align: center;
  }
</style>


