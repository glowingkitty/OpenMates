<!--
  frontend/packages/ui/src/components/embeds/UnifiedEmbedFullscreen.svelte
  
  Unified base component for all embed fullscreen views (app skills, websites, etc.)
  
  Structure:
  - EmbedTopBar — action buttons (share, copy, download, close …) in normal flow
  - EmbedHeader — gradient banner (scrolls with content, same as ChatHeader)
  - Scrollable content area
  
  The top bar is in normal document flow (not absolutely positioned) so the
  gradient banner always starts below it, keeping the header fully visible on
  every screen size — mirroring how ChatHeader sits above chat messages.
  
  Animations:
  - Opening: Slides up from the bottom of the container at full size (translateY 100% → 0)
  - Closing: Slides back down off-screen (translateY 0 → 100%)
  - No scale change — the card appears at its final size throughout the animation
  
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
  import { panelState } from '../../stores/panelStateStore';
  import { settingsDeepLink } from '../../stores/settingsDeepLinkStore';
  import { settingsMenuVisible } from '../Settings.svelte';
  import { resolveEmbed, decodeToonContent } from '../../services/embedResolver';
  import { chatSyncService } from '../../services/chatSyncService';
  import { searchTextHighlightStore } from '../../stores/messageHighlightStore';
  import EmbedTopBar from './EmbedTopBar.svelte';
  import EmbedHeader from './EmbedHeader.svelte';
  
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
    /** App identifier (e.g., 'web', 'videos', 'code') - used for gradient background */
    appId: string;
    /** Skill identifier (e.g., 'search', 'get_transcript') */
    skillId?: string;
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
    /** 
     * Snippet for main content
     * When embedIds is provided, receives ChildEmbedContext with loaded children
     * Otherwise receives empty context for backwards compatibility
     */
    content?: import('svelte').Snippet<[ChildEmbedContext]>;

    /**
     * Optional snippet rendered at the bottom of the gradient header banner.
     * Use this for CTA buttons (e.g. "Book on Condor", "Open on zapier.com")
     * and badges (CO2, trip type) that belong visually inside the banner.
     * The snippet receives no arguments.
     */
    embedHeaderCta?: import('svelte').Snippet;
    
    /* ============================================
       Embed Header Props (gradient banner at top)
       ============================================ */
    
    /**
     * Main title displayed in the gradient header banner.
     * Shown bold and white, centered below the icon.
     */
    embedHeaderTitle?: string;
    
    /**
     * Subtitle displayed below the title in the header banner.
     * Shown smaller and at 0.85 opacity (e.g. "via Brave Search", "Data from 2025/03/27").
     */
    embedHeaderSubtitle?: string;
    
    /**
     * Favicon/logo URL shown as a small image next to the title text.
     * Used for website/news embeds where the source favicon is meaningful.
     */
    embedHeaderFaviconUrl?: string;
    
    /**
     * Whether the favicon should be circular (for channel thumbnails, profile pics).
     * Default: false (rounded square).
     */
    embedHeaderFaviconIsCircular?: boolean;
    
    /**
     * Icon name for the skill icon shown in the header.
     * When set, shows a CSS mask-image icon (same as BasicInfosBar).
     * When empty/undefined, shows the app icon (icon_rounded class).
     */
    skillIconName?: string;
    
    /**
     * Whether to show the skill icon (true) or app icon (false) in the header.
     * When false, always uses app icon regardless of skillIconName.
     * Default: true.
     */
    showSkillIcon?: boolean;
    
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
     * The snippet receives no arguments.
     */
    onChildrenLoaded?: (children: unknown[]) => void;
    
    /**
     * Child embed ID to auto-open on mount (set when arriving from an inline badge click).
     * When provided together with onAutoOpenChild, the fullscreen will automatically
     * open the child overlay for this embed_id once children finish loading.
     * 
     * This eliminates the need for each consumer to duplicate the _autoOpenFired +
     * $effect + findIndex boilerplate — the logic lives here in the base component.
     */
    initialChildEmbedId?: string;
    
    /**
     * Callback invoked when initialChildEmbedId matches a loaded child embed.
     * The consumer should open the appropriate child overlay at the given index.
     * 
     * @param index - The index of the matching child in the loaded children array
     * @param children - The full array of loaded children (for navigation context)
     * 
     * Fired at most once per mount. If the child is not found, a console warning
     * is logged but no callback is invoked.
     */
    onAutoOpenChild?: (index: number, children: unknown[]) => void;
    
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
    /** Direction of the navigation that triggered this fullscreen mount (unused for animation, kept for API compat). */
    navigateDirection?: 'next' | 'previous' | null;
    
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
    onClose,
    onCopy,
    onDownload,
    onShare,
    showShare = true,
    content,
    embedHeaderCta,
    // Embed header props
    embedHeaderTitle = '',
    embedHeaderSubtitle = '',
    embedHeaderFaviconUrl,
    embedHeaderFaviconIsCircular = false,
    skillIconName = '',
    showSkillIcon = true,
    // Child embed loading props
    embedIds,
    childEmbedTransformer,
    legacyResults,
    // Embed navigation props
    hasPreviousEmbed = false,
    hasNextEmbed = false,
    onNavigatePrevious,
    onNavigateNext,
    // Child embed loading callback
    onChildrenLoaded,
    // Auto-open child embed props (inline badge click → child overlay)
    initialChildEmbedId,
    onAutoOpenChild,
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
  
  /** Guard: prevent auto-open from firing more than once per mount */
  let _autoOpenChildFired = $state(false);
  
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
    
    // Auto-open a specific child embed if initialChildEmbedId was set (inline badge click).
    // Fires at most once (guarded by _autoOpenChildFired) to prevent re-opening after close.
    if (initialChildEmbedId && onAutoOpenChild && !_autoOpenChildFired && children.length > 0) {
      const idx = children.findIndex((child: unknown) => {
        if (child && typeof child === 'object' && 'embed_id' in child) {
          return (child as { embed_id: string }).embed_id === initialChildEmbedId;
        }
        return false;
      });
      if (idx >= 0) {
        _autoOpenChildFired = true;
        console.debug('[UnifiedEmbedFullscreen] Auto-opening child overlay for initialChildEmbedId:', initialChildEmbedId, 'at index', idx);
        onAutoOpenChild(idx, children);
      } else {
        console.warn(
          '[UnifiedEmbedFullscreen] initialChildEmbedId not found in loaded children:',
          initialChildEmbedId,
          'available embed_ids:',
          children
            .filter((c: unknown): c is { embed_id: string } => !!c && typeof c === 'object' && 'embed_id' in c)
            .map((c) => c.embed_id)
        );
      }
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
        embedHeaderTitle
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

  /**
   * Deep-link from the embed header icon to the app-store skill settings page.
   * Falls back to the app page when skillId is unavailable.
   *
   * Virtual embed types (e.g. "sheets", "docs" as direct embed) have an appId
   * that does NOT correspond to a real app in appsMetadata. For those, we link
   * to the app_store root instead of a non-existent app page.
   */
  async function handleEmbedHeaderIconClick() {
    try {
      const { navigateToSettings } = await import('../../stores/settingsNavigationStore');
      const { appsMetadata } = await import('../../data/appsMetadata');

      // Check if the appId corresponds to a real registered app.
      // Virtual embed types (sheets, docs-as-embed, etc.) won't have an entry.
      const isRealApp = appId in appsMetadata;

      let targetPath: string;
      if (isRealApp && skillId) {
        // Real app with a specific skill → deep-link to the skill settings page
        targetPath = `app_store/${appId}/skill/${skillId}`;
      } else if (isRealApp) {
        // Real app, no specific skill → app details page
        targetPath = `app_store/${appId}`;
      } else {
        // Virtual/direct embed type (e.g. "sheets") → app store root
        targetPath = 'app_store';
      }

      navigateToSettings(targetPath, 'App Store', appId || 'app_store');
      settingsMenuVisible.set(true);
      panelState.openSettings();

      await tick();
      await new Promise(resolve => setTimeout(resolve, 100));

      settingsDeepLink.set(targetPath);
      console.debug('[UnifiedEmbedFullscreen] Opened settings deep-link from header icon:', targetPath);
    } catch (error) {
      console.error('[UnifiedEmbedFullscreen] Failed to open settings from header icon:', error);
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
    
    // Trigger opening animation.
    // Also reset scroll to top: on mobile, browsers can initialise a scrollable
    // container at a non-zero offset (e.g. after keyboard events), which would
    // hide the gradient header banner that is now part of the scrollable flow.
    //
    // Scale-up from the preview card origin.
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        isAnimatingIn = true;
        if (contentAreaElement) {
          contentAreaElement.scrollTop = 0;
        }
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

  // ============================================
  // Search Text Highlighting (in embed fullscreen)
  // ============================================

  /** Reference to the scrollable content area — TreeWalker is rooted here */
  let contentAreaElement = $state<HTMLElement | undefined>(undefined);

  /**
   * Search text highlighting for embed fullscreen.
   * When search is open and has a query, walks all text nodes inside the .content-area
   * and wraps matches in <mark class="search-match"> elements (same as ChatMessage).
   *
   * Embed content often loads asynchronously (markdown-it, highlight.js, etc.), so we
   * use a MutationObserver to re-apply highlights whenever child nodes change. The observer
   * is debounced with requestAnimationFrame to avoid excessive re-runs on rapid DOM mutations.
   */
  $effect(() => {
    const query = $searchTextHighlightStore;
    const container = contentAreaElement;

    function removeExistingMarks(el: HTMLElement) {
      const marks = Array.from(el.querySelectorAll('mark.search-match'));
      for (const mark of marks) {
        const parent = mark.parentNode;
        if (parent) {
          parent.replaceChild(document.createTextNode(mark.textContent || ''), mark);
          parent.normalize();
        }
      }
    }

    function applyHighlights(el: HTMLElement, q: string) {
      if (!el.isConnected) return;
      removeExistingMarks(el);
      if (!q || !q.trim()) return;

      const lowerQuery = q.toLowerCase().trim();

      const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT, null);
      const textNodes: Text[] = [];
      let node: Node | null;
      while ((node = walker.nextNode())) {
        // Skip aria-hidden elements (e.g. doc page-break spacers, line number columns)
        let ancestor = node.parentElement;
        let skip = false;
        while (ancestor && ancestor !== el) {
          if (ancestor.getAttribute('aria-hidden') === 'true') { skip = true; break; }
          ancestor = ancestor.parentElement;
        }
        if (!skip) textNodes.push(node as Text);
      }

      for (const textNode of textNodes) {
        const textContent = textNode.textContent || '';
        const lowerContent = textContent.toLowerCase();
        if (lowerContent.indexOf(lowerQuery) === -1) continue;

        const fragment = document.createDocumentFragment();
        let lastIdx = 0;
        let searchFrom = 0;

        while (searchFrom < lowerContent.length) {
          const idx = lowerContent.indexOf(lowerQuery, searchFrom);
          if (idx === -1) break;
          if (idx > lastIdx) {
            fragment.appendChild(document.createTextNode(textContent.slice(lastIdx, idx)));
          }
          const mark = document.createElement('mark');
          mark.className = 'search-match';
          mark.textContent = textContent.slice(idx, idx + lowerQuery.length);
          fragment.appendChild(mark);
          lastIdx = idx + lowerQuery.length;
          searchFrom = lastIdx;
        }

        if (lastIdx < textContent.length) {
          fragment.appendChild(document.createTextNode(textContent.slice(lastIdx)));
        }

        textNode.parentNode?.replaceChild(fragment, textNode);
      }
    }

    if (!container) return;

    if (!query || !query.trim()) {
      removeExistingMarks(container);
      return;
    }

    // Apply highlights immediately (covers content already in DOM)
    let rafHandle: number | null = null;
    rafHandle = requestAnimationFrame(() => {
      applyHighlights(container, query);
    });

    // MutationObserver: re-apply highlights when embed content loads/changes asynchronously
    // (e.g. markdown-it, highlight.js, or async embed child loading updating the DOM).
    // Debounce via rAF to avoid excessive re-runs on rapid DOM mutations.
    let mutationRafHandle: number | null = null;
    const observer = new MutationObserver(() => {
      if (mutationRafHandle !== null) return; // already pending
      mutationRafHandle = requestAnimationFrame(() => {
        mutationRafHandle = null;
        applyHighlights(container, query);
      });
    });
    observer.observe(container, { childList: true, subtree: true, characterData: true });

    return () => {
      if (rafHandle !== null) cancelAnimationFrame(rafHandle);
      if (mutationRafHandle !== null) cancelAnimationFrame(mutationRafHandle);
      observer.disconnect();
      if (container.isConnected) removeExistingMarks(container);
    };
  });

</script>

<div
  class="unified-embed-fullscreen-overlay"
  class:animating-in={isAnimatingIn}
>
  <div class="fullscreen-container">

    <!-- ── Scrollable content area (header banner + embed content) ──
         Fills the full container height. EmbedTopBar overlays the top
         via position: absolute so no space is reserved for it here. -->
    <div class="content-area" bind:this={contentAreaElement}>

      <!-- ── Gradient Header Banner (EmbedHeader) ──
           Scrolls with content — fixed height (never grows).
           EmbedTopBar floats above it as a transparent overlay.
           If a CTA is present it pokes out from the banner's bottom edge
           and the embed content must provide enough top spacing to clear it. -->
      <EmbedHeader
        {appId}
        {skillIconName}
        {showSkillIcon}
        onHeaderIconClick={handleEmbedHeaderIconClick}
        title={embedHeaderTitle}
        subtitle={embedHeaderSubtitle}
        faviconUrl={embedHeaderFaviconUrl}
        faviconIsCircular={embedHeaderFaviconIsCircular}
        hasCta={!!embedHeaderCta}
        {embedHeaderCta}
        {hasPreviousEmbed}
        {hasNextEmbed}
        onNavigatePrevious={handleNavigatePrevious}
        onNavigateNext={handleNavigateNext}
      />

      <!-- ── Embed-specific content ── -->
      {#if content}
        {@render content(childEmbedContext)}
      {:else}
        <div class="missing-content-fallback">
          <p>Content unavailable</p>
        </div>
      {/if}

    </div>
    <!-- end .content-area -->

    <!-- ── Action buttons (transparent overlay, positioned over the header) ──
         position: absolute so it does not push the content area down.
         The gradient header is visible through the semi-transparent buttons. -->
    <EmbedTopBar
      {showChatButton}
      {showShare}
      showCopy={!!onCopy}
      showDownload={!!onDownload}
      {showPIIToggle}
      {piiRevealed}
      onClose={handleClose}
      onShare={handleShare}
      onCopy={handleCopy}
      onDownload={handleDownload}
      onReportIssue={handleReportIssue}
      onShowChat={handleShowChatClick}
      {onTogglePII}
    />

  </div>
</div>

<style>
  /* ===========================================
     Unified Embed Fullscreen - Overlay + Container
     =========================================== */

  .unified-embed-fullscreen-overlay {
    position: absolute;
    /* Fills the parent container (ActiveChat in overlay mode, side panel otherwise) */
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
    /* Slide-up-from-bottom animation — starts off-screen at the bottom */
    transition: transform 320ms cubic-bezier(0.32, 0, 0.2, 1);
    overflow: hidden;
    /* Container queries so child components can detect their available width */
    container-type: inline-size;
    container-name: fullscreen;
    /* Initial (hidden) state: pushed below the visible area */
    transform: translateY(100%);
  }

  /* ── Expanded state: slide up to fill the container ── */
  .unified-embed-fullscreen-overlay.animating-in {
    transform: translateY(0);
  }

  /* position: relative so EmbedTopBar (position: absolute) is contained here */
  .fullscreen-container {
    display: flex;
    flex-direction: column;
    height: 100%;
    position: relative;
  }

  /* Bottom scroll gradient — visual cue that content continues below.
     Sits above the scrollable area (z-index 999), pointer-events none. */
  .fullscreen-container::after {
    content: '';
    position: absolute;
    bottom: 0;
    left: 0;
    right: 0;
    height: 48px;
    background: linear-gradient(to bottom, transparent, var(--color-grey-20));
    z-index: 999;
    pointer-events: none;
    border-radius: 0 0 17px 17px;
  }

  /* ===========================================
     Scrollable Content Area
     =========================================== */

  /* Fills the full container height. EmbedTopBar overlays via position: absolute. */
  .content-area {
    flex: 1;
    overflow-y: auto;
    overflow-x: hidden;
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

  /* ===========================================
     Search Text Highlighting inside embed fullscreen
     =========================================== */

  /* <mark class="search-match"> injected by the search highlight $effect.
   * Must reset -webkit-text-fill-color to override the gradient-text rule
   * in fonts.css which would otherwise make highlighted text invisible. */
  .content-area :global(mark.search-match) {
    background: none;
    background-color: rgba(255, 213, 0, 0.4);
    -webkit-background-clip: unset;
    background-clip: unset;
    -webkit-text-fill-color: unset;
    color: inherit;
    font-weight: inherit;
    border-radius: 2px;
    padding: 1px 0;
  }
</style>
