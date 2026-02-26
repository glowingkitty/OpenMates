<!--
  frontend/packages/ui/src/components/embeds/UnifiedEmbedFullscreen.svelte
  
  Unified base component for all embed fullscreen views (app skills, websites, etc.)
  
  Structure:
  - Top bar with action buttons (share, close) — absolute, always on top
  - Gradient banner header (scrolls with content, like ChatHeader)
    - App/skill gradient background using CSS variable --color-app-{appId}
    - Decorative large icons (left/right edges, same as ChatHeader)
    - Center: small icon (38×38) + title + subtitle
    - Navigation arrows at left/right edges of the banner
  - Main content area (scrollable)
  
  Animations:
  - Opening: Scale up from 0.5 to 1.0 with opacity fade (originates from preview position)
  - Closing: Scale down to 0.5 with opacity fade (back to preview position)
  - CSS variables --preview-center-x and --preview-center-y set by UnifiedEmbedPreview
    determine the transform-origin for smooth origin-based animations
  
  Header Icon Logic:
  - skillIconName is set AND showSkillIcon is true → skill icon (CSS mask-image SVG)
  - Otherwise → app icon (icon_rounded CSS class)
  
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
  import { panelState } from '../../stores/panelStateStore';
  import { settingsDeepLink } from '../../stores/settingsDeepLinkStore';
  import { settingsMenuVisible } from '../Settings.svelte';
  import { resolveEmbed, decodeToonContent } from '../../services/embedResolver';
  import { chatSyncService } from '../../services/chatSyncService';
  import { searchTextHighlightStore } from '../../stores/messageHighlightStore';
  
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
     */
    onChildrenLoaded?: (children: unknown[]) => void;
    
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
    onClose,
    onCopy,
    onDownload,
    onShare,
    showShare = true,
    content,
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

  // ============================================
  // Header derived state
  // ============================================

  /**
   * Whether to use the skill icon (CSS mask-image) or the app icon (icon_rounded class).
   * skill icon = when skillIconName is set AND showSkillIcon is true
   * app icon = when showSkillIcon is false OR skillIconName is empty
   */
  let useSkillIcon = $derived(showSkillIcon && !!skillIconName);
</script>

<div
  class="unified-embed-fullscreen-overlay"
  class:animating-in={isAnimatingIn}
  style="--preview-center-x: var(--preview-center-x, 50vw); --preview-center-y: var(--preview-center-y, 50vh);"
>
  <div class="fullscreen-container">
    <!-- ── Top bar with action buttons ──
         Absolutely positioned over the header banner + content.
         Stays fixed at top during scroll. -->
    <div class="top-bar">
      <!-- Left side: Chat button, Share, Copy, Download, Report Issue, PII toggle -->
      <div class="top-bar-left">
        <!-- Show Chat button - only shown when chat is hidden (forceOverlayMode active on ultra-wide) -->
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
      
      <!-- Right side: Minimize button -->
      <div class="top-bar-right">
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

    <!-- ── Scrollable content area (header banner + embed content) ── -->
    <div class="content-area" bind:this={contentAreaElement}>

      <!-- ── Gradient Header Banner ──
           Scrolls with content (not fixed), identical design to ChatHeader.
           Background: app gradient from CSS variable --color-app-{appId}.
           Large decorative icons at edges, navigation arrows, center content. -->
      <div
        class="embed-header-banner"
        style="background: var(--color-app-{appId});"
      >
        <!-- Large decorative icons at left and right edges (126×126px, 0.4 opacity).
             Same animation as ChatHeader: fade up from +50px below. -->
        <div class="deco-icon deco-icon-left">
          {#if useSkillIcon}
            <div class="deco-skill-icon" data-skill-icon={skillIconName}></div>
          {:else}
            <div class="deco-app-icon icon_rounded {appId}"></div>
          {/if}
        </div>
        <div class="deco-icon deco-icon-right">
          {#if useSkillIcon}
            <div class="deco-skill-icon" data-skill-icon={skillIconName}></div>
          {:else}
            <div class="deco-app-icon icon_rounded {appId}"></div>
          {/if}
        </div>

        <!-- Center content: small icon + title + subtitle -->
        <div class="header-center">
          <!-- Small icon (38×38px, white) -->
          <div class="header-icon">
            {#if useSkillIcon}
              <div class="header-skill-icon" data-skill-icon={skillIconName}></div>
            {:else}
              <div class="header-app-icon icon_rounded {appId}"></div>
            {/if}
          </div>

          <!-- Title (bold, white) -->
          {#if embedHeaderTitle}
            <div class="header-title">
              {#if embedHeaderFaviconUrl}
                <img
                  src={embedHeaderFaviconUrl}
                  alt=""
                  class="header-favicon"
                  class:circular={embedHeaderFaviconIsCircular}
                  crossorigin="anonymous"
                  onerror={(e) => { (e.target as HTMLImageElement).style.display = 'none'; }}
                />
              {/if}
              <span class="header-title-text">{embedHeaderTitle}</span>
            </div>
          {/if}

          <!-- Subtitle (e.g. "via Brave Search", "Data from 2025/03/27") -->
          {#if embedHeaderSubtitle}
            <div class="header-subtitle">{embedHeaderSubtitle}</div>
          {/if}
        </div>

        <!-- Navigation arrows at banner edges — same style as ChatHeader nav-arrows.
             Previous embed (left) and next embed (right).
             Using prev/next inline here rather than the top-bar since they
             belong visually to the header carousel. -->
        {#if hasPreviousEmbed && onNavigatePrevious}
          <button
            class="nav-arrow nav-arrow-left"
            onclick={handleNavigatePrevious}
            aria-label="Previous embed"
            type="button"
          >
            <span class="nav-chevron nav-chevron-left"></span>
          </button>
        {/if}
        {#if hasNextEmbed && onNavigateNext}
          <button
            class="nav-arrow nav-arrow-right"
            onclick={handleNavigateNext}
            aria-label="Next embed"
            type="button"
          >
            <span class="nav-chevron nav-chevron-right"></span>
          </button>
        {/if}
      </div>

      <!-- ── Embed-specific content ── -->
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
    <!-- end .content-area -->

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

  /* ===========================================
     Top Bar (absolute, always on top)
     =========================================== */

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
    width: 30px;
    height: 30px;
    min-width: 30px;
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
    width: 22px;
    height: 22px;
  }

  /* PII toggle button: subtle orange/amber tint when PII is revealed (warns sensitive data exposed) */
  .pii-toggle-button.pii-toggle-active {
    background-color: rgba(245, 158, 11, 0.3) !important;
  }

  .pii-toggle-button.pii-toggle-active:hover {
    background-color: rgba(245, 158, 11, 0.45) !important;
  }

  /* ===========================================
     Scrollable Content Area
     =========================================== */
  
  /* Main content area: takes remaining height, scrollable */
  .content-area {
    flex: 1;
    overflow-y: auto;
    overflow-x: hidden;
    padding-right: 8px;
    margin-right: -8px;
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
     Gradient Header Banner (scrolls with content)
     Matches ChatHeader design exactly.
     =========================================== */

  .embed-header-banner {
    position: relative;
    width: 100%;
    height: 240px;
    /* Bottom corners rounded; top corners flush with overlay's top-left/top-right border-radius */
    border-radius: 0 0 14px 14px;
    overflow: hidden;
    display: flex;
    align-items: center;
    justify-content: center;
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.25);
    /* Non-interactive background; arrows/buttons override with pointer-events:auto */
    pointer-events: none;
    user-select: none;
    /* Ensure top-bar buttons render above the banner */
    z-index: 1;
  }

  /* ── Decorative large icons (126×126px) at banner edges ── */

  .deco-icon {
    position: absolute;
    width: 126px;
    height: 126px;
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 1;
    pointer-events: none;
    /* Entrance: fade up from +50px below */
    animation: decoIconEnter 0.6s ease-out 0.1s both;
  }

  .deco-icon-left {
    left: calc(50% - 240px - 106px);
    bottom: -15px;
    transform: rotate(-15deg);
    --deco-rotate: -15deg;
  }

  .deco-icon-right {
    right: calc(50% - 240px - 106px);
    bottom: -15px;
    transform: rotate(15deg);
    --deco-rotate: 15deg;
  }

  @keyframes decoIconEnter {
    from {
      opacity: 0;
      transform: translateY(50px) rotate(var(--deco-rotate, 0deg));
    }
    to {
      opacity: 0.4;
      transform: translateY(0) rotate(var(--deco-rotate, 0deg));
    }
  }

  /* Decorative skill icon: CSS mask-image, white fill, large size */
  .deco-skill-icon {
    width: 126px;
    height: 126px;
    background-color: white;
    -webkit-mask-position: center;
    mask-position: center;
    -webkit-mask-repeat: no-repeat;
    mask-repeat: no-repeat;
    -webkit-mask-size: contain;
    mask-size: contain;
  }

  /* Decorative app icon: uses icon_rounded system, white, large size */
  .deco-app-icon {
    width: 80px;
    height: 80px;
    position: relative;
    bottom: auto;
    left: auto;
    z-index: auto;
  }

  /* Force app icon to render white (not gradient) inside decorative container */
  .deco-app-icon::after {
    filter: brightness(0) invert(1) !important;
    background-size: 60px 60px !important;
  }

  /* ── Center content ── */

  .header-center {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 4px;
    z-index: 2;
    padding: 16px 24px;
    /* Narrow block so it doesn't stretch the full banner width */
    max-width: 480px;
    width: 100%;
    animation: fadeIn 0.35s ease-out;
  }

  @keyframes fadeIn {
    from { opacity: 0; }
    to   { opacity: 1; }
  }

  /* Small icon container (38×38px) */
  .header-icon {
    width: 38px;
    height: 38px;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
  }

  /* Small skill icon (38×38px white) */
  .header-skill-icon {
    width: 38px;
    height: 38px;
    background-color: white;
    -webkit-mask-position: center;
    mask-position: center;
    -webkit-mask-repeat: no-repeat;
    mask-repeat: no-repeat;
    -webkit-mask-size: contain;
    mask-size: contain;
  }

  /* Small app icon (38×38px white) */
  .header-app-icon {
    width: 30px;
    height: 30px;
    position: relative;
    bottom: auto;
    left: auto;
    z-index: auto;
  }

  .header-app-icon::after {
    filter: brightness(0) invert(1) !important;
    background-size: 20px 20px !important;
  }

  /* Title row: optional favicon + text, clamped to 2 lines */
  .header-title {
    display: flex;
    align-items: center;
    gap: 8px;
    max-width: 100%;
    margin-top: 2px;
  }

  .header-favicon {
    width: 20px;
    height: 20px;
    border-radius: 4px;
    flex-shrink: 0;
    object-fit: cover;
  }

  .header-favicon.circular {
    width: 26px;
    height: 26px;
    border-radius: 50%;
  }

  .header-title-text {
    font-size: 20px;
    font-weight: 700;
    color: #ffffff;
    text-align: center;
    line-height: 1.3;
    /* Clamp to 2 lines */
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }

  /* Subtitle: smaller, slightly transparent */
  .header-subtitle {
    font-size: 14px;
    font-weight: 500;
    color: rgba(255, 255, 255, 0.85);
    text-align: center;
    margin-top: 2px;
    animation: fadeIn 0.4s ease-out 0.15s both;
    /* Clamp to 2 lines */
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }

  /* ── Navigation arrows ──
     Positioned at the outer edges of the banner.
     Identical to ChatHeader nav-arrow style. */

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
    transition: background-color 0.15s ease;
    z-index: 20;
    pointer-events: auto; /* Re-enable interactivity (banner has pointer-events:none) */
    flex-shrink: 0;
  }

  .nav-arrow:hover {
    background-color: rgba(255, 255, 255, 0.1) !important;
    scale: none !important;
  }

  .nav-arrow:active {
    background-color: rgba(255, 255, 255, 0.18) !important;
    scale: none !important;
    filter: none !important;
  }

  .nav-arrow-left {
    left: 0;
    border-radius: 0 10px 10px 0 !important;
  }

  .nav-arrow-right {
    right: 0;
    border-radius: 10px 0 0 10px !important;
  }

  /* Chevron icons for nav arrows — CSS triangles using borders */
  .nav-chevron {
    display: block;
    width: 10px;
    height: 10px;
    border-top: 2.5px solid rgba(255, 255, 255, 0.85);
    border-right: 2.5px solid rgba(255, 255, 255, 0.85);
    flex-shrink: 0;
  }

  .nav-chevron-left {
    transform: rotate(-135deg);
    margin-left: 4px; /* optical center */
  }

  .nav-chevron-right {
    transform: rotate(45deg);
    margin-right: 4px;
  }

  /* ── Skill icon mask-images (same set as BasicInfosBar) ── */

  /* Applied to both .deco-skill-icon and .header-skill-icon via data-skill-icon attr */

  :global([data-skill-icon="search"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/search.svg');
    mask-image: url('@openmates/ui/static/icons/search.svg');
  }

  :global([data-skill-icon="videos"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/videos.svg');
    mask-image: url('@openmates/ui/static/icons/videos.svg');
  }

  :global([data-skill-icon="video"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/videos.svg');
    mask-image: url('@openmates/ui/static/icons/videos.svg');
  }

  :global([data-skill-icon="book"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/book.svg');
    mask-image: url('@openmates/ui/static/icons/book.svg');
  }

  :global([data-skill-icon="visible"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/visible.svg');
    mask-image: url('@openmates/ui/static/icons/visible.svg');
  }

  :global([data-skill-icon="reminder"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/reminder.svg');
    mask-image: url('@openmates/ui/static/icons/reminder.svg');
  }

  :global([data-skill-icon="image"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/image.svg');
    mask-image: url('@openmates/ui/static/icons/image.svg');
  }

  :global([data-skill-icon="ai"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/ai.svg');
    mask-image: url('@openmates/ui/static/icons/ai.svg');
  }

  :global([data-skill-icon="focus"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/insight.svg');
    mask-image: url('@openmates/ui/static/icons/insight.svg');
  }

  :global([data-skill-icon="pin"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/pin.svg');
    mask-image: url('@openmates/ui/static/icons/pin.svg');
  }

  :global([data-skill-icon="text"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/docs.svg');
    mask-image: url('@openmates/ui/static/icons/docs.svg');
  }

  :global([data-skill-icon="transcript"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/docs.svg');
    mask-image: url('@openmates/ui/static/icons/docs.svg');
  }

  :global([data-skill-icon="website"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/web.svg');
    mask-image: url('@openmates/ui/static/icons/web.svg');
  }

  :global([data-skill-icon="coding"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/coding.svg');
    mask-image: url('@openmates/ui/static/icons/coding.svg');
  }

  /* ===========================================
     Mobile adjustments (≤730px)
     =========================================== */

  @media (max-width: 730px) {
    .embed-header-banner {
      height: 190px;
    }

    .header-center {
      padding: 12px 20px;
      max-width: 360px;
    }

    .header-icon {
      width: 32px;
      height: 32px;
    }

    .header-skill-icon {
      width: 32px;
      height: 32px;
    }

    .header-title-text {
      font-size: 17px;
    }

    .header-subtitle {
      font-size: 13px;
    }

    .deco-icon {
      width: 90px;
      height: 90px;
    }

    .deco-skill-icon {
      width: 90px;
      height: 90px;
    }

    .deco-icon-left {
      left: calc(50% - 180px - 70px);
    }

    .deco-icon-right {
      right: calc(50% - 180px - 70px);
    }
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

  /* ============================================
     Search Text Highlighting inside embed fullscreen
     ============================================ */

  /* <mark class="search-match"> injected via DOM TreeWalker from the search highlight $effect.
   * Yellow background highlight, matching in-chat search marks in ChatMessage.svelte.
   * Must override the global `mark` rule in fonts.css which uses -webkit-text-fill-color:transparent
   * (gradient text effect). That property takes priority over `color` in WebKit/Blink, making
   * text invisible unless we explicitly reset -webkit-text-fill-color here. */
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
