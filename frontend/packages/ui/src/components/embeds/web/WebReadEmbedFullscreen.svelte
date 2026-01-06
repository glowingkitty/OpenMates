<!--
  frontend/packages/ui/src/components/embeds/web/WebReadEmbedFullscreen.svelte
  
  Fullscreen view for Web Read skill embeds.
  Uses UnifiedEmbedFullscreen as base and provides web read-specific content.
  
  Supports both contexts:
  - Skill preview context: receives previewData from skillPreviewService
  - Embed context: receives results directly
  
  Data sources (in priority order):
  1. results[0] - Contains full read results with markdown (from finished embed)
  2. url prop - Direct URL from embed content (from processing placeholder)
  
  Layout (per Figma design):
  - File widget at top: shows website title with app icon
  - "Full viewing experience:" label with "Open on {hostname}" CTA button
  - "Text only preview, via Firecrawl: {wordCount} words" label
  - White content card with rendered markdown
  - Bottom bar: web icon + text icon + "Read" / "Completed"
-->

<script lang="ts">
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import BasicInfosBar from '../BasicInfosBar.svelte';
  import type { BaseSkillPreviewData } from '../../../types/appSkills';
  import { text } from '@repo/ui';
  
  /**
   * Web read result interface based on read_skill.py
   */
  interface WebReadResult {
    type: string;
    url: string;
    title?: string;
    markdown?: string;
    language?: string;
    favicon?: string;
    og_image?: string;
    og_sitename?: string;
    hash?: string;
  }
  
  /**
   * Preview data interface for web read skill
   */
  interface WebReadPreviewData extends BaseSkillPreviewData {
    results: WebReadResult[];
    url?: string; // URL from processing placeholder content
  }
  
  /**
   * Props for web read embed fullscreen
   * Supports both skill preview data format and direct embed format
   */
  interface Props {
    /** Web read results (direct format) */
    results?: WebReadResult[];
    /** Direct URL from embed content (from processing placeholder) */
    url?: string;
    /** Skill preview data (skill preview context) */
    previewData?: WebReadPreviewData;
    /** Close handler */
    onClose: () => void;
    /** Optional: Embed ID for sharing */
    embedId?: string;
    /** Whether there is a previous embed to navigate to */
    hasPreviousEmbed?: boolean;
    /** Whether there is a next embed to navigate to */
    hasNextEmbed?: boolean;
    /** Handler to navigate to the previous embed */
    onNavigatePrevious?: () => void;
    /** Handler to navigate to the next embed */
    onNavigateNext?: () => void;
    /** Whether to show the "chat" button to restore chat visibility (ultra-wide forceOverlayMode) */
    showChatButton?: boolean;
    /** Callback when user clicks the "chat" button to restore chat visibility */
    onShowChat?: () => void;
  }
  
  let {
    results: resultsProp,
    url: urlProp,
    previewData,
    onClose,
    embedId,
    hasPreviousEmbed = false,
    hasNextEmbed = false,
    onNavigatePrevious,
    onNavigateNext,
    showChatButton = false,
    onShowChat
  }: Props = $props();
  
  // ===========================================
  // Local state for embed data (updated via onEmbedDataUpdated callback)
  // CRITICAL: Using $state allows us to update these values when we receive embed updates
  // via the onEmbedDataUpdated callback from UnifiedEmbedFullscreen
  // ===========================================
  let localResults = $state<WebReadResult[]>([]);
  let localUrl = $state<string>('');
  
  // Initialize local state from props
  $effect(() => {
    // Initialize from previewData or direct props
    if (previewData) {
      localResults = previewData.results || [];
      localUrl = previewData.url || '';
    } else {
      localResults = resultsProp || [];
      localUrl = urlProp || '';
    }
  });
  
  // Use local state as the source of truth (allows updates from embed events)
  let results = $derived(localResults);
  
  // Get first result for main display (may be undefined if results are empty)
  let firstResult = $derived(results[0]);
  
  // Get URL from multiple sources (priority: results > localUrl > previewData > direct prop)
  // CRITICAL: Even if results are empty, we may have URL from the processing placeholder
  let effectiveUrl = $derived(
    firstResult?.url || 
    localUrl ||
    previewData?.url || 
    urlProp || 
    ''
  );
  
  /**
   * Handle embed data updates from UnifiedEmbedFullscreen
   * Called when the parent component receives and decodes updated embed data
   * This is the CENTRALIZED way to receive updates - no need for custom subscription
   */
  function handleEmbedDataUpdated(data: { status: string; decodedContent: Record<string, unknown>; results?: unknown[] }) {
    console.debug(`[WebReadEmbedFullscreen] 🔄 Received embed data update for ${embedId}:`, {
      status: data.status,
      hasContent: !!data.decodedContent,
      hasResults: !!data.results,
      resultsCount: data.results?.length || 0
    });
    
    // Update web-read-specific fields from decoded content or results
    if (data.results && Array.isArray(data.results) && data.results.length > 0) {
      console.debug(`[WebReadEmbedFullscreen] ✅ Updated results from callback:`, data.results.length);
      localResults = data.results as WebReadResult[];
    } else if (data.decodedContent?.results && Array.isArray(data.decodedContent.results)) {
      console.debug(`[WebReadEmbedFullscreen] ✅ Updated results from decodedContent:`, data.decodedContent.results.length);
      localResults = data.decodedContent.results as WebReadResult[];
    }
    
    // Update URL if available
    if (data.decodedContent?.url && typeof data.decodedContent.url === 'string') {
      localUrl = data.decodedContent.url;
    }
  }
  
  /**
   * Safely extract hostname from URL
   * Falls back to stripping the scheme if URL parsing fails
   */
  function safeHostname(url?: string): string {
    if (!url) return '';
    try {
      return new URL(url).hostname;
    } catch {
      const withoutScheme = url.replace(/^[a-zA-Z]+:\/\//, '');
      return withoutScheme.split('/')[0] || '';
    }
  }
  
  // Extract hostname from effective URL
  let hostname = $derived(safeHostname(effectiveUrl));
  
  // Display title: page title from results, or fallback to hostname
  let displayTitle = $derived(
    firstResult?.title || 
    hostname ||
    'Web Read'
  );
  
  // Truncated title for file widget (max ~40 chars)
  let truncatedTitle = $derived(() => {
    const title = displayTitle;
    if (title.length > 40) {
      return title.slice(0, 37) + '...';
    }
    return title;
  });
  
  // Favicon URL for display
  // Priority: result favicon > generated from URL > undefined
  let faviconUrl = $derived(() => {
    if (firstResult?.favicon) {
      return firstResult.favicon;
    }
    // Generate favicon URL from effectiveUrl if available
    if (effectiveUrl) {
      return `https://preview.openmates.org/api/v1/favicon?url=${encodeURIComponent(effectiveUrl)}`;
    }
    return undefined;
  });
  
  /**
   * Calculate total word count across all results
   */
  let totalWordCount = $derived(() => {
    let count = 0;
    for (const result of results) {
      if (result.markdown) {
        const words = result.markdown.trim().split(/\s+/).filter(Boolean);
        count += words.length;
      }
    }
    return count;
  });
  
  // Skill name from translations
  let skillName = $derived($text('embeds.web_read.text'));
  
  // "Open on {hostname}" button text - uses open_on_provider translation with hostname placeholder
  let openButtonText = $derived($text('embeds.open_on_provider.text').replace('{provider}', hostname));
  
  // Store rendered HTML for markdown
  // CRITICAL: Using object instead of Map for proper Svelte 5 reactivity
  // Map.set() mutations don't trigger re-renders, but object property assignments do
  let renderedMarkdowns = $state<Record<number, string>>({});
  
  // Debug logging
  $effect(() => {
    console.debug('[WebReadEmbedFullscreen] Rendering with:', {
      resultsCount: results.length,
      effectiveUrl,
      hostname,
      displayTitle,
      wordCount: totalWordCount(),
      hasPreviewData: !!previewData,
      hasUrlProp: !!urlProp,
      hasLocalResults: localResults.length > 0
    });
  });
  
  /**
   * Render markdown to HTML using markdown-it
   * CRITICAL: Uses object property assignment for proper Svelte 5 reactivity
   * 
   * SECURITY: Uses DOMPurify to sanitize rendered HTML against XSS attacks.
   * Backend sanitization (sanitize_external_content) protects against prompt injection,
   * but does NOT sanitize HTML/JS. DOMPurify is the XSS protection layer.
   */
  async function renderMarkdown(markdown: string, index: number): Promise<void> {
    console.debug(`[WebReadEmbedFullscreen] renderMarkdown called for index ${index}, markdown length: ${markdown?.length || 0}`);
    
    if (!markdown) {
      renderedMarkdowns[index] = '';
      return;
    }
    
    try {
      // Import markdown-it and DOMPurify for XSS protection
      const [MarkdownItModule, DOMPurifyModule] = await Promise.all([
        import('markdown-it'),
        import('dompurify')
      ]);
      const MarkdownIt = MarkdownItModule.default;
      const DOMPurify = DOMPurifyModule.default;
      
      // Use markdown-it for proper markdown rendering
      const md = new MarkdownIt({
        html: true,  // Allow HTML in markdown (will be sanitized by DOMPurify)
        linkify: true,
        typographer: true,
        breaks: false
      });
      
      // Render markdown to HTML
      const rawHtml = md.render(markdown);
      
      // SECURITY: Sanitize HTML to prevent XSS attacks
      // Allow common HTML tags for rich content display, but block scripts/events
      
      // Add hook to force all links to open in new tab
      // This runs after sanitization but before returning the HTML
      DOMPurify.addHook('afterSanitizeAttributes', (node) => {
        // Force all anchor links to open in new tab with proper security attributes
        if (node.tagName === 'A') {
          node.setAttribute('target', '_blank');
          node.setAttribute('rel', 'noopener noreferrer');
        }
      });
      
      const sanitizedHtml = DOMPurify.sanitize(rawHtml, {
        ALLOWED_TAGS: [
          // Text formatting
          'p', 'br', 'hr',
          'strong', 'b', 'em', 'i', 'u', 's', 'strike', 'del', 'ins',
          'mark', 'small', 'sub', 'sup', 'kbd', 'code', 'pre', 'samp', 'var',
          // Headings
          'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
          // Lists
          'ul', 'ol', 'li', 'dl', 'dt', 'dd',
          // Tables
          'table', 'thead', 'tbody', 'tfoot', 'tr', 'th', 'td', 'caption', 'colgroup', 'col',
          // Links and media (images are allowed, will be sandboxed)
          'a', 'img', 'figure', 'figcaption',
          // Block elements
          'div', 'span', 'blockquote', 'q', 'cite', 'abbr', 'address',
          // Details/Summary (collapsible content)
          'details', 'summary'
        ],
        ALLOWED_ATTR: [
          'href', 'src', 'alt', 'title', 'width', 'height',
          'class', 'id', 'name',
          'colspan', 'rowspan', 'scope', 'headers',
          'start', 'type', 'reversed', // List attributes
          'open', // Details attribute
          'datetime', // Time/date attributes
          'lang', 'dir', // Language/direction
          'target', 'rel' // Link security attributes (set by hook)
        ],
        // Forbid dangerous protocols in URLs
        ALLOWED_URI_REGEXP: /^(?:(?:(?:f|ht)tps?|mailto|tel|callto|sms|cid|xmpp):|[^a-z]|[a-z+.-]+(?:[^a-z+.-:]|$))/i
      });
      
      // Remove hook after use to prevent memory leaks and avoid affecting other sanitization calls
      DOMPurify.removeHook('afterSanitizeAttributes');
      
      console.debug(`[WebReadEmbedFullscreen] ✅ Rendered & sanitized markdown for index ${index}, HTML length: ${sanitizedHtml.length}`);
      
      // CRITICAL: Use object property assignment for reactivity (not Map.set)
      renderedMarkdowns[index] = sanitizedHtml;
    } catch (error) {
      console.error('[WebReadEmbedFullscreen] Error rendering markdown:', error);
      // Fallback: escape HTML and preserve line breaks (safe by default)
      const html = markdown
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/\n/g, '<br>');
      renderedMarkdowns[index] = html;
    }
  }
  
  // Render markdown for all results when they change
  // CRITICAL: Uses object property check (index in obj) instead of Map.has()
  $effect(() => {
    console.debug(`[WebReadEmbedFullscreen] Markdown render effect triggered, results count: ${results.length}`);
    results.forEach((result, index) => {
      const alreadyRendered = index in renderedMarkdowns;
      console.debug(`[WebReadEmbedFullscreen] Check index ${index}: hasMarkdown=${!!result.markdown}, alreadyRendered=${alreadyRendered}`);
      if (result.markdown && !alreadyRendered) {
        renderMarkdown(result.markdown, index);
      }
    });
  });
  
  /**
   * Handle opening the website in a new tab
   * Uses effectiveUrl which includes fallback to urlProp
   */
  function handleOpenWebsite() {
    if (effectiveUrl) {
      window.open(effectiveUrl, '_blank', 'noopener,noreferrer');
    }
  }
  
  /**
   * Handle share button click
   */
  async function handleShare() {
    try {
      console.debug('[WebReadEmbedFullscreen] Opening share settings:', { embedId, url: effectiveUrl });
      
      if (!embedId) {
        console.warn('[WebReadEmbedFullscreen] No embed_id available - cannot create share link');
        const { notificationStore } = await import('../../../stores/notificationStore');
        notificationStore.error('Unable to share this embed. Missing embed ID.');
        return;
      }
      
      // Import required modules
      const { navigateToSettings } = await import('../../../stores/settingsNavigationStore');
      const { settingsDeepLink } = await import('../../../stores/settingsDeepLinkStore');
      const { panelState } = await import('../../../stores/panelStateStore');
      
      // Set embed context for SettingsShare
      const embedContext = {
        type: 'web_read',
        embed_id: embedId,
        url: effectiveUrl,
        title: displayTitle
      };
      
      (window as unknown as { __embedShareContext?: unknown }).__embedShareContext = embedContext;
      
      // Navigate to share settings
      navigateToSettings('shared/share', 'Share', 'share', 'settings.share.text');
      settingsDeepLink.set('shared/share');
      panelState.openSettings();
      
    } catch (error) {
      console.error('[WebReadEmbedFullscreen] Error opening share settings:', error);
      const { notificationStore } = await import('../../../stores/notificationStore');
      notificationStore.error('Failed to open share menu. Please try again.');
    }
  }
</script>

<UnifiedEmbedFullscreen
  appId="web"
  skillId="read"
  title=""
  {onClose}
  onShare={handleShare}
  skillIconName="text"
  status="finished"
  currentEmbedId={embedId}
  onEmbedDataUpdated={handleEmbedDataUpdated}
  {skillName}
  showStatus={true}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
  {showChatButton}
  {onShowChat}
>
  {#snippet content()}
    <div class="web-read-fullscreen-content">
      <!-- File widget showing website title (mini preview) -->
      <div class="file-widget">
        <div class="file-widget-icon">
          <div class="icon_rounded web"></div>
        </div>
        {#if faviconUrl()}
          <img 
            src={faviconUrl()} 
            alt="" 
            class="file-widget-favicon"
            onerror={(e) => { (e.currentTarget as HTMLImageElement).style.display = 'none'; }}
          />
        {/if}
        <div class="file-widget-title">{truncatedTitle()}</div>
      </div>
      
      <!-- Show "Full viewing experience" and open button only if we have a URL -->
      {#if effectiveUrl}
        <!-- "Full viewing experience:" label -->
        <div class="full-view-label">
          {$text('embeds.web_read_full_view.text')}
        </div>
        
        <!-- CTA Button: "Open on {hostname}" -->
        <button 
          onclick={handleOpenWebsite}
          type="button"
        >
          {openButtonText}
        </button>
      {/if}
      
      <!-- "Text only preview, via Firecrawl: X words" label - only show if we have content -->
      {#if totalWordCount() > 0}
        <div class="text-preview-label">
          <span>{$text('embeds.web_read_text_preview.text')}</span>
          <span>via Firecrawl: {totalWordCount().toLocaleString()} words</span>
        </div>
      {/if}
      
      <!-- Content card with rendered markdown -->
      {#if results.length === 0}
        <!-- No results yet - show URL info if available, otherwise placeholder -->
        <div class="no-results">
          {#if effectiveUrl}
            <div class="pending-content">
              <p class="pending-url">{effectiveUrl}</p>
              <p class="pending-message">{$text('embeds.web_read_loading_content.text')}</p>
            </div>
          {:else}
            <p>{$text('embeds.web_read_no_content.text')}</p>
          {/if}
        </div>
      {:else}
        <div class="content-card">
          {#each results as result, index}
            <div class="result-content">
              {#if index in renderedMarkdowns && renderedMarkdowns[index]}
                <div class="markdown-content">
                  {@html renderedMarkdowns[index]}
                </div>
              {:else if result.markdown}
                <div class="markdown-loading">
                  <p>{$text('embeds.web_read_loading_content.text')}</p>
                </div>
              {:else}
                <div class="no-content">
                  <p>{$text('embeds.web_read_no_content.text')}</p>
                </div>
              {/if}
            </div>
            
            {#if index < results.length - 1}
              <hr class="result-divider" />
            {/if}
          {/each}
        </div>
      {/if}
    </div>
  {/snippet}
  
  {#snippet bottomBar()}
    <!-- Wrapper to match UnifiedEmbedFullscreen's .basic-infos-bar-wrapper styling (300px max-width) -->
    <div class="basic-infos-bar-wrapper">
      <BasicInfosBar
        appId="web"
        skillId="read"
        skillIconName="text"
        status="finished"
        {skillName}
        showStatus={true}
      />
    </div>
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  /* ===========================================
     Web Read Fullscreen Content
     =========================================== */
  
  .web-read-fullscreen-content {
    display: flex;
    flex-direction: column;
    align-items: center;
    padding-top: 70px; /* Space for top action buttons */
    padding-bottom: 120px; /* Space for bottom bar */
  }
  
  /* ===========================================
     File Widget (mini preview at top)
     =========================================== */
  
  .file-widget {
    display: flex;
    align-items: center;
    gap: 8px;
    background-color: var(--color-grey-30);
    border-radius: 30px;
    height: 61px;
    padding: 0 20px 0 0;
    max-width: 300px;
    width: 100%;
    box-shadow: 0 4px 8px rgba(0, 0, 0, 0.15);
    margin-bottom: 24px;
  }
  
  .file-widget-icon {
    width: 61px;
    height: 61px;
    min-width: 61px;
    border-radius: 50%;
    background: var(--color-app-web);
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
  }
  
  .file-widget-icon .icon_rounded {
    width: 26px;
    height: 26px;
    position: relative;
    bottom: auto;
    left: auto;
    background: transparent !important;
  }
  
  .file-widget-icon .icon_rounded::after {
    filter: brightness(0) invert(1);
  }
  
  .file-widget-favicon {
    width: 19px;
    height: 19px;
    min-width: 19px;
    border-radius: 9.5px;
    border: 1px solid white;
    background-color: white;
    object-fit: cover;
    flex-shrink: 0;
  }
  
  .file-widget-title {
    font-size: 16px;
    font-weight: 700;
    color: var(--color-grey-100);
    line-height: 1.3;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    flex: 1;
    min-width: 0;
  }
  
  /* ===========================================
     Full View Label and CTA Button
     =========================================== */
  
  .full-view-label {
    font-size: 14px;
    font-weight: 700;
    color: var(--color-grey-70);
    text-align: center;
    margin-bottom: 12px;
  }
  /* ===========================================
     Text Preview Label
     =========================================== */
  
  .text-preview-label {
    font-size: 14px;
    font-weight: 700;
    color: var(--color-grey-70);
    text-align: center;
    margin-bottom: 16px;
    display: flex;
    flex-direction: column;
    gap: 2px;
    margin-top: 15px;
  }
  
  /* ===========================================
     Content Card (white background with markdown)
     =========================================== */
  
  .no-results {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 200px;
    color: var(--color-grey-70);
    font-size: 16px;
    text-align: center;
  }
  
  /* Pending content display when URL is available but results haven't loaded */
  .pending-content {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 12px;
  }
  
  .pending-url {
    font-size: 14px;
    color: var(--color-grey-80);
    word-break: break-all;
    max-width: 400px;
  }
  
  .pending-message {
    font-size: 14px;
    color: var(--color-grey-60);
    font-style: italic;
  }
  
  .content-card {
    background-color: var(--color-grey-0);
    border-radius: 30px;
    padding: 24px;
    width: calc(100% - 40px);
    max-width: 722px;
    margin: 0 auto;
    box-shadow: 0 -4px 8px rgba(0, 0, 0, 0.1);
    min-height: 300px;
  }
  
  .result-content {
    margin-bottom: 24px;
  }
  
  .result-content:last-child {
    margin-bottom: 0;
  }
  
  .markdown-loading,
  .no-content {
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 100px;
    color: var(--color-grey-70);
    font-size: 14px;
  }
  
  /* ===========================================
     Markdown Content Styling
     =========================================== */
  
  .markdown-content {
    font-size: 16px;
    line-height: 1.7;
    color: var(--color-grey-100);
    word-wrap: break-word;
  }
  
  .markdown-content :global(h1) {
    font-size: 22px;
    font-weight: 700;
    margin: 20px 0 12px 0;
    color: var(--color-grey-100);
  }
  
  .markdown-content :global(h2) {
    font-size: 18px;
    font-weight: 700;
    margin: 16px 0 10px 0;
    color: var(--color-grey-100);
  }
  
  .markdown-content :global(h3) {
    font-size: 16px;
    font-weight: 700;
    margin: 14px 0 8px 0;
    color: var(--color-grey-100);
  }
  
  .markdown-content :global(p) {
    margin: 12px 0;
  }
  
  .markdown-content :global(strong) {
    font-weight: 700;
    color: var(--color-grey-100);
  }
  
  .markdown-content :global(em) {
    font-style: italic;
  }
  
  /* Links styled with purple gradient (matches Figma design) */
  .markdown-content :global(a) {
    background: linear-gradient(133.68deg, rgba(89, 81, 208, 1) 9.04%, rgba(125, 116, 255, 1) 90.06%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    text-decoration: none;
    font-weight: 700;
  }
  
  .markdown-content :global(a:hover) {
    text-decoration: underline;
  }
  
  .markdown-content :global(ul),
  .markdown-content :global(ol) {
    margin: 12px 0;
    padding-left: 24px;
  }
  
  .markdown-content :global(li) {
    margin: 6px 0;
  }
  
  .markdown-content :global(code) {
    background-color: var(--color-grey-20);
    padding: 2px 6px;
    border-radius: 4px;
    font-family: 'Courier New', monospace;
    font-size: 14px;
  }
  
  .markdown-content :global(pre) {
    background-color: var(--color-grey-20);
    padding: 16px;
    border-radius: 8px;
    overflow-x: auto;
    margin: 16px 0;
  }
  
  .markdown-content :global(pre code) {
    background-color: transparent;
    padding: 0;
  }
  
  .markdown-content :global(blockquote) {
    border-left: 3px solid var(--color-grey-40);
    padding-left: 16px;
    margin: 16px 0;
    color: var(--color-grey-80);
    font-style: italic;
  }
  
  /* Images - constrain large images, keep small ones at natural size */
  .markdown-content :global(img) {
    max-width: 100%;
    border-radius: 10px;
    height: auto;
    display: block;
    margin: 16px 0;
  }
  
  /* Result divider */
  .result-divider {
    border: none;
    border-top: 1px solid var(--color-grey-30);
    margin: 24px 0;
  }
  
  /* ===========================================
     Container Query Responsive Adjustments
     =========================================== */
  
  @container fullscreen (max-width: 500px) {
    .web-read-fullscreen-content {
      padding-top: 80px;
    }
    
    .file-widget {
      max-width: 280px;
    }
    
    .content-card {
      width: calc(100% - 20px);
      padding: 16px;
    }
    
    .markdown-content {
      font-size: 15px;
    }
  }
  
  /* ===========================================
     BasicInfosBar Wrapper (matches UnifiedEmbedFullscreen styling)
     =========================================== */
  
  /* BasicInfosBar wrapper - max-width 300px, centered */
  .basic-infos-bar-wrapper {
    width: 100%;
    max-width: 300px;
    border: none;
    background: transparent;
    padding: 0;
    cursor: default;
  }
  
  /* Ensure BasicInfosBar inside wrapper respects max-width */
  .basic-infos-bar-wrapper :global(.basic-infos-bar) {
    width: 100%;
    max-width: 300px;
  }
  
  /* ===========================================
     Skill Icon Styling (text icon)
     =========================================== */
  
  /* Web Read skill icon - "text" icon as per Figma design */
  :global(.basic-infos-bar .skill-icon[data-skill-icon="text"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/text.svg');
    mask-image: url('@openmates/ui/static/icons/text.svg');
  }
</style>
