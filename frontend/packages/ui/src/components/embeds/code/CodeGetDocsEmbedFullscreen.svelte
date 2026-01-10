<!--
  frontend/packages/ui/src/components/embeds/code/CodeGetDocsEmbedFullscreen.svelte
  
  Fullscreen view for Code Get Docs skill embeds.
  Uses UnifiedEmbedFullscreen as base and provides get_docs-specific content.
  
  Supports both contexts:
  - Skill preview context: receives previewData from skillPreviewService
  - Embed context: receives results directly
  
  Layout (similar to WebSearchEmbedFullscreen pattern):
  - Header at top: library title (large text), library ID below, "Open on Context7" button
  - "Documentation preview, via Context7: X words" label (text only, no icon)
  - White content card with rendered markdown documentation
  - Bottom bar: code icon + docs icon + "Get Docs" / "Completed"
  
  Data Flow:
  - Receives results from backend GetDocsSkill which returns GetDocsResponse
  - Library info contains id (e.g., "/sveltejs/svelte"), title, description
  - Documentation is markdown text from Context7 API
-->

<script lang="ts">
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import BasicInfosBar from '../BasicInfosBar.svelte';
  import type { CodeGetDocsSkillPreviewData, CodeGetDocsResult } from '../../../types/appSkills';
  import { text } from '@repo/ui';
  
  /**
   * Props for code get docs embed fullscreen
   * Supports both skill preview data format and direct embed format
   */
  interface Props {
    /** Get docs results (direct format) */
    results?: CodeGetDocsResult[];
    /** Library name from request */
    library?: string;
    /** Skill preview data (skill preview context) */
    previewData?: CodeGetDocsSkillPreviewData;
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
    library: libraryProp,
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
  let localResults = $state<CodeGetDocsResult[]>([]);
  let localLibrary = $state<string>('');
  
  // Initialize local state from props
  $effect(() => {
    // Initialize from previewData or direct props
    if (previewData) {
      localResults = previewData.results || [];
      localLibrary = previewData.library || '';
    } else {
      localResults = resultsProp || [];
      localLibrary = libraryProp || '';
    }
  });
  
  // Use local state as the source of truth (allows updates from embed events)
  let results = $derived(localResults);
  
  // Get first result for main display (may be undefined if results are empty)
  let firstResult = $derived(results[0]);
  
  /**
   * Handle embed data updates from UnifiedEmbedFullscreen
   * Called when the parent component receives and decodes updated embed data
   * This is the CENTRALIZED way to receive updates - no need for custom subscription
   */
  function handleEmbedDataUpdated(data: { status: string; decodedContent: Record<string, unknown>; results?: unknown[] }) {
    console.debug(`[CodeGetDocsEmbedFullscreen] 🔄 Received embed data update for ${embedId}:`, {
      status: data.status,
      hasContent: !!data.decodedContent,
      hasResults: !!data.results,
      resultsCount: data.results?.length || 0
    });
    
    // Update get-docs-specific fields from decoded content or results
    if (data.results && Array.isArray(data.results) && data.results.length > 0) {
      console.debug(`[CodeGetDocsEmbedFullscreen] ✅ Updated results from callback:`, data.results.length);
      localResults = data.results as CodeGetDocsResult[];
    } else if (data.decodedContent?.results && Array.isArray(data.decodedContent.results)) {
      console.debug(`[CodeGetDocsEmbedFullscreen] ✅ Updated results from decodedContent:`, data.decodedContent.results.length);
      localResults = data.decodedContent.results as CodeGetDocsResult[];
    }
    
    // Update library if available
    if (data.decodedContent?.library && typeof data.decodedContent.library === 'string') {
      localLibrary = data.decodedContent.library;
    }
  }
  
  // ===========================================
  // Display Values
  // ===========================================
  
  // Display title: library title > library ID > requested library name > fallback
  let displayTitle = $derived.by(() => {
    if (firstResult?.library?.title) {
      return firstResult.library.title;
    }
    if (firstResult?.library?.id) {
      // Extract library name from ID (e.g., "/sveltejs/svelte" -> "svelte")
      const parts = firstResult.library.id.split('/');
      return parts[parts.length - 1] || firstResult.library.id;
    }
    if (localLibrary) {
      return localLibrary;
    }
    return 'Documentation';
  });
  
  // Library ID for display and Context7 URL (e.g., "/sveltejs/svelte")
  let libraryId = $derived(firstResult?.library?.id || '');
  
  // Context7 URL for "Open on Context7" button
  // Format: https://context7.com{libraryId}
  let context7Url = $derived.by(() => {
    if (libraryId) {
      return `https://context7.com${libraryId}`;
    }
    return 'https://context7.com';
  });
  
  /**
   * Calculate word count from documentation
   */
  let wordCount = $derived.by(() => {
    if (!firstResult?.documentation) return 0;
    const words = firstResult.documentation.trim().split(/\s+/).filter(Boolean);
    return words.length;
  });
  
  // Skill name from translations
  let skillName = $derived($text('embeds.get_docs.text') || 'Get Docs');
  
  // "Open on Context7" button text
  let openButtonText = $derived($text('embeds.open_on_provider.text').replace('{provider}', 'Context7'));
  
  // Store rendered HTML for markdown
  // CRITICAL: Using object instead of Map for proper Svelte 5 reactivity
  // Map.set() mutations don't trigger re-renders, but object property assignments do
  let renderedMarkdown = $state<string>('');
  let isRenderingMarkdown = $state(false);
  
  // Debug logging
  $effect(() => {
    console.debug('[CodeGetDocsEmbedFullscreen] Rendering with:', {
      resultsCount: results.length,
      displayTitle,
      libraryId,
      wordCount,
      hasPreviewData: !!previewData,
      hasDocumentation: !!firstResult?.documentation
    });
  });
  
  /**
   * Render markdown to HTML using markdown-it
   * 
   * SECURITY: Uses DOMPurify to sanitize rendered HTML against XSS attacks.
   * Context7 documentation is from trusted sources (official library docs),
   * but we still sanitize for defense in depth.
   */
  async function renderDocumentation(markdown: string): Promise<void> {
    console.debug(`[CodeGetDocsEmbedFullscreen] renderDocumentation called, markdown length: ${markdown?.length || 0}`);
    
    if (!markdown) {
      renderedMarkdown = '';
      return;
    }
    
    isRenderingMarkdown = true;
    
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
      // Add hook to process attributes after sanitization
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
          // Links (images not needed for documentation)
          'a',
          // Block elements
          'div', 'span', 'blockquote', 'q', 'cite', 'abbr', 'address',
          // Details/Summary (collapsible content)
          'details', 'summary'
        ],
        ALLOWED_ATTR: [
          'href', 'title',
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
      
      // Remove hook after use to prevent memory leaks
      DOMPurify.removeHook('afterSanitizeAttributes');
      
      console.debug(`[CodeGetDocsEmbedFullscreen] ✅ Rendered & sanitized markdown, HTML length: ${sanitizedHtml.length}`);
      
      renderedMarkdown = sanitizedHtml;
    } catch (error) {
      console.error('[CodeGetDocsEmbedFullscreen] Error rendering markdown:', error);
      // Fallback: escape HTML and preserve line breaks (safe by default)
      const html = markdown
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/\n/g, '<br>');
      renderedMarkdown = html;
    } finally {
      isRenderingMarkdown = false;
    }
  }
  
  // Render markdown when documentation changes
  $effect(() => {
    const documentation = firstResult?.documentation;
    if (documentation && !renderedMarkdown) {
      renderDocumentation(documentation);
    }
  });
  
  /**
   * Handle opening Context7 in a new tab
   */
  function handleOpenContext7() {
    if (context7Url) {
      window.open(context7Url, '_blank', 'noopener,noreferrer');
    }
  }
  
  /**
   * Handle copy - copies documentation as formatted markdown
   */
  async function handleCopy() {
    try {
      const documentation = firstResult?.documentation;
      if (documentation) {
        let content = '';
        if (displayTitle) {
          content += `# ${displayTitle}\n\n`;
        }
        if (libraryId) {
          content += `Library: ${libraryId}\n`;
          content += `Source: Context7 (${context7Url})\n\n`;
        }
        content += `---\n\n`;
        content += documentation;
        
        await navigator.clipboard.writeText(content);
        console.debug('[CodeGetDocsEmbedFullscreen] Copied documentation to clipboard');
        // Show success notification
        const { notificationStore } = await import('../../../stores/notificationStore');
        notificationStore.success('Documentation copied to clipboard');
      }
    } catch (error) {
      console.error('[CodeGetDocsEmbedFullscreen] Failed to copy documentation:', error);
      const { notificationStore } = await import('../../../stores/notificationStore');
      notificationStore.error('Failed to copy documentation to clipboard');
    }
  }
  
  /**
   * Handle download - downloads documentation as markdown file
   */
  function handleDownload() {
    try {
      const documentation = firstResult?.documentation;
      if (documentation) {
        let content = '';
        if (displayTitle) {
          content += `# ${displayTitle}\n\n`;
        }
        if (libraryId) {
          content += `Library: ${libraryId}\n`;
          content += `Source: Context7 (${context7Url})\n\n`;
        }
        content += `---\n\n`;
        content += documentation;
        
        const blob = new Blob([content], { type: 'text/markdown' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        // Create filename from library name
        const filename = displayTitle.replace(/[^a-z0-9]/gi, '_').toLowerCase();
        a.download = `${filename}_docs.md`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        console.debug('[CodeGetDocsEmbedFullscreen] Downloaded documentation as markdown');
      }
    } catch (error) {
      console.error('[CodeGetDocsEmbedFullscreen] Failed to download documentation:', error);
    }
  }
  
  /**
   * Handle share button click
   */
  async function handleShare() {
    try {
      console.debug('[CodeGetDocsEmbedFullscreen] Opening share settings:', { embedId, libraryId });
      
      if (!embedId) {
        console.warn('[CodeGetDocsEmbedFullscreen] No embed_id available - cannot create share link');
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
        type: 'get_docs',
        embed_id: embedId,
        library: displayTitle,
        libraryId: libraryId,
        source: 'Context7'
      };
      
      (window as unknown as { __embedShareContext?: unknown }).__embedShareContext = embedContext;
      
      // Navigate to share settings
      navigateToSettings('shared/share', 'Share', 'share', 'settings.share.text');
      settingsDeepLink.set('shared/share');
      panelState.openSettings();
      
    } catch (error) {
      console.error('[CodeGetDocsEmbedFullscreen] Error opening share settings:', error);
      const { notificationStore } = await import('../../../stores/notificationStore');
      notificationStore.error('Failed to open share menu. Please try again.');
    }
  }
</script>

<UnifiedEmbedFullscreen
  appId="code"
  skillId="get_docs"
  title=""
  {onClose}
  onCopy={handleCopy}
  onDownload={handleDownload}
  onShare={handleShare}
  skillIconName="docs"
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
    <div class="get-docs-fullscreen-content">
      <!-- Header with library title and ID - similar to WebSearchEmbedFullscreen -->
      <div class="fullscreen-header">
        <div class="library-title">{displayTitle}</div>
        {#if libraryId}
          <div class="library-id">{libraryId}</div>
        {/if}
        <!-- CTA Button: "Open on Context7" -->
        {#if libraryId}
          <button 
            class="open-context7-btn"
            onclick={handleOpenContext7}
            type="button"
          >
            {openButtonText}
          </button>
        {/if}
      </div>
      
      <!-- "Documentation preview, via Context7: X words" label - only show if we have content -->
      {#if wordCount > 0}
        <div class="text-preview-label">
          <span>{$text('embeds.get_docs_preview.text')}</span>
          <span>via Context7: {wordCount.toLocaleString()} words</span>
        </div>
      {/if}
      
      <!-- Content card with rendered markdown -->
      {#if results.length === 0 || !firstResult?.documentation}
        <!-- No results yet - show placeholder -->
        <div class="no-results">
          {#if firstResult?.error}
            <div class="error-content">
              <p class="error-message">{firstResult.error}</p>
            </div>
          {:else if localLibrary}
            <div class="pending-content">
              <p class="pending-library">{localLibrary}</p>
              <p class="pending-message">{$text('embeds.get_docs_loading.text')}</p>
            </div>
          {:else}
            <p>{$text('embeds.get_docs_no_content.text')}</p>
          {/if}
        </div>
      {:else}
        <div class="content-card">
          <div class="result-content">
            {#if renderedMarkdown}
              <div class="markdown-content">
                <!-- SECURITY: Safe - content sanitized with DOMPurify before rendering -->
                <!-- eslint-disable-next-line svelte/no-at-html-tags -->
                {@html renderedMarkdown}
              </div>
            {:else if isRenderingMarkdown}
              <div class="markdown-loading">
                <p>{$text('embeds.get_docs_loading.text')}</p>
              </div>
            {:else}
              <div class="no-content">
                <p>{$text('embeds.get_docs_no_content.text')}</p>
              </div>
            {/if}
          </div>
        </div>
      {/if}
    </div>
  {/snippet}
  
  {#snippet bottomBar()}
    <!-- Wrapper to match UnifiedEmbedFullscreen's .basic-infos-bar-wrapper styling (300px max-width) -->
    <div class="basic-infos-bar-wrapper">
      <BasicInfosBar
        appId="code"
        skillId="get_docs"
        skillIconName="docs"
        status="finished"
        {skillName}
        showStatus={true}
      />
    </div>
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  /* ===========================================
     Get Docs Fullscreen Content
     =========================================== */
  
  .get-docs-fullscreen-content {
    display: flex;
    flex-direction: column;
    align-items: center;
    padding-top: 60px; /* Space for top action buttons */
    padding-bottom: 120px; /* Space for bottom bar */
  }
  
  /* ===========================================
     Fullscreen Header - Library Title and ID
     Uses container queries for responsive sizing
     =========================================== */
  
  .fullscreen-header {
    margin-top: 60px;
    margin-bottom: 40px;
    padding: 0 16px;
    text-align: center;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 8px;
  }
  
  .library-title {
    font-size: 24px;
    font-weight: 600;
    color: var(--color-font-primary);
    line-height: 1.3;
    word-break: break-word;
    /* Limit to 3 lines with ellipsis */
    display: -webkit-box;
    -webkit-line-clamp: 3;
    line-clamp: 3;
    -webkit-box-orient: vertical;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  
  .library-id {
    font-size: 16px;
    color: var(--color-font-secondary);
    font-family: 'SF Mono', 'Monaco', 'Inconsolata', 'Fira Mono', 'Consolas', monospace;
  }
  
  .open-context7-btn {
    margin-top: 8px;
    padding: 10px 20px;
    background: linear-gradient(133.68deg, rgba(89, 81, 208, 1) 9.04%, rgba(125, 116, 255, 1) 90.06%);
    color: white;
    border: none;
    border-radius: 20px;
    font-size: 14px;
    font-weight: 600;
    cursor: pointer;
    transition: transform 0.15s ease, box-shadow 0.15s ease;
  }
  
  .open-context7-btn:hover {
    transform: scale(1.02);
    box-shadow: 0 4px 12px rgba(89, 81, 208, 0.3);
  }
  
  .open-context7-btn:active {
    transform: scale(0.98);
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
  
  /* Error content display */
  .error-content {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 12px;
    padding: 24px;
    background-color: rgba(var(--color-error-rgb), 0.1);
    border: 1px solid var(--color-error);
    border-radius: 16px;
    max-width: 400px;
  }
  
  .error-message {
    font-size: 14px;
    color: var(--color-error);
    word-break: break-word;
  }
  
  /* Pending content display when library is specified but results haven't loaded */
  .pending-content {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 12px;
  }
  
  .pending-library {
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
  
  /* Code blocks with syntax highlighting */
  .markdown-content :global(code) {
    background-color: var(--color-grey-20);
    padding: 2px 6px;
    border-radius: 4px;
    font-family: 'SF Mono', 'Monaco', 'Inconsolata', 'Fira Mono', 'Consolas', monospace;
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
    font-size: 13px;
    line-height: 1.5;
  }
  
  .markdown-content :global(blockquote) {
    border-left: 3px solid var(--color-grey-40);
    padding-left: 16px;
    margin: 16px 0;
    color: var(--color-grey-80);
    font-style: italic;
  }
  
  /* Tables */
  .markdown-content :global(table) {
    width: 100%;
    border-collapse: collapse;
    margin: 16px 0;
  }
  
  .markdown-content :global(th),
  .markdown-content :global(td) {
    border: 1px solid var(--color-grey-30);
    padding: 8px 12px;
    text-align: left;
  }
  
  .markdown-content :global(th) {
    background-color: var(--color-grey-10);
    font-weight: 700;
  }
  
  /* ===========================================
     Container Query Responsive Adjustments
     =========================================== */
  
  /* Container query: smaller text on narrow containers */
  @container fullscreen (max-width: 500px) {
    .get-docs-fullscreen-content {
      padding-top: 70px;
    }
    
    .fullscreen-header {
      margin-top: 70px; /* More space for action buttons */
      margin-bottom: 24px;
    }
    
    .library-title {
      font-size: 20px;
    }
    
    .library-id {
      font-size: 14px;
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
     Skill Icon Styling (docs icon)
     =========================================== */
  
  /* Get Docs skill icon - "docs" icon for documentation */
  :global(.basic-infos-bar .skill-icon[data-skill-icon="docs"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/docs.svg');
    mask-image: url('@openmates/ui/static/icons/docs.svg');
  }
</style>
