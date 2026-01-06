<!--
  frontend/packages/ui/src/components/embeds/web/WebReadEmbedPreview.svelte
  
  Preview component for Web Read skill embeds.
  Uses UnifiedEmbedPreview as base and provides web read-specific details content.
  
  Supports both contexts:
  - Skill preview context: receives previewData from skillPreviewService
  - Embed context: receives results directly
  
  Data sources (in priority order):
  1. results[0] - Contains full read results with markdown (from finished embed)
  2. url prop - Direct URL from embed content (from processing placeholder)
  
  Layout (per Figma design):
  - Details section:
    - Favicon (rounded, top-left of title)
    - Title: page title or hostname
    - Subtitle: "via Firecrawl: {wordCount} words"
  - Basic infos bar:
    - Web app icon (gradient circle)
    - Text skill icon
    - "Read" / "Completed" (or "Processing")
-->

<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { chatSyncService } from '../../../services/chatSyncService';
  import type { BaseSkillPreviewData } from '../../../types/appSkills';
  // @ts-expect-error - @repo/ui module exists at runtime
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
   * Props for web read embed preview
   * Supports both skill preview data format and direct embed format
   */
  interface Props {
    /** Unique embed ID */
    id: string;
    /** Processing status */
    status?: 'processing' | 'finished' | 'error';
    /** Web read results (from finished embed) */
    results?: WebReadResult[];
    /** Direct URL from embed content (from processing placeholder) */
    url?: string;
    /** Task ID for cancellation */
    taskId?: string;
    /** Skill preview data (skill preview context) */
    previewData?: WebReadPreviewData;
    /** Whether to use mobile layout */
    isMobile?: boolean;
    /** Click handler for fullscreen */
    onFullscreen?: () => void;
  }
  
  let {
    id,
    status: statusProp,
    results: resultsProp,
    url: urlProp,
    taskId: taskIdProp,
    previewData,
    isMobile = false,
    onFullscreen
  }: Props = $props();
  
  // Extract values from either previewData (skill preview context) or direct props (embed context)
  let status = $derived(previewData?.status || statusProp || 'processing');
  let results = $derived(previewData?.results || resultsProp || []);
  let taskId = $derived(previewData?.task_id || taskIdProp);
  
  // Get first result for main display (may be undefined if results are empty)
  let firstResult = $derived(results[0]);
  
  // Get URL from multiple sources (priority: results > previewData > direct prop)
  // CRITICAL: Even if results are empty, we may have URL from the processing placeholder
  let effectiveUrl = $derived(
    firstResult?.url || 
    previewData?.url || 
    urlProp || 
    ''
  );
  
  /**
   * Safely extract hostname from URL
   * Falls back to stripping the scheme if URL parsing fails
   */
  function safeHostname(url?: string): string {
    if (!url) return '';
    try {
      return new URL(url).hostname;
    } catch {
      // Fallback: try to strip scheme if present, then take host part.
      const withoutScheme = url.replace(/^[a-zA-Z]+:\/\//, '');
      return withoutScheme.split('/')[0] || '';
    }
  }
  
  // Extract hostname from effective URL
  let hostname = $derived(safeHostname(effectiveUrl));
  
  // Display title: page title from results, or fallback to hostname
  // CRITICAL: Use effectiveUrl-derived hostname if results are empty
  let displayTitle = $derived(
    firstResult?.title || 
    hostname || 
    ($text('embeds.web_read.text') || 'Web Read')
  );
  
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
   * Word count is used in the "via Firecrawl: X words" subtitle
   */
  let totalWordCount = $derived(() => {
    let count = 0;
    for (const result of results) {
      if (result.markdown) {
        // Simple word count: split on whitespace and count non-empty strings
        const words = result.markdown.trim().split(/\s+/).filter(Boolean);
        count += words.length;
      }
    }
    return count;
  });
  
  // Subtitle text: "via Firecrawl: X words" (matches Figma design)
  let subtitleText = $derived(() => {
    const wordCount = totalWordCount();
    if (wordCount > 0) {
      return `via Firecrawl:\n${wordCount.toLocaleString()} words`;
    }
    return 'via Firecrawl';
  });
  
  // Skill icon name - "text" icon as per Figma design
  const skillIconName = 'text';
  
  // Skill display name from translations
  let skillName = $derived($text('embeds.web_read.text') || 'Read');
  
  // Debug logging to help trace data flow issues
  $effect(() => {
    console.debug('[WebReadEmbedPreview] Rendering with:', {
      id,
      status,
      resultsCount: results.length,
      effectiveUrl,
      hostname,
      displayTitle,
      wordCount: totalWordCount(),
      hasPreviewData: !!previewData,
      hasUrlProp: !!urlProp
    });
  });
  
  /**
   * Handle stop button click - cancel the running task
   */
  async function handleStop() {
    if (status === 'processing' && taskId) {
      try {
        await chatSyncService.sendCancelAiTask(taskId);
        console.debug(`[WebReadEmbedPreview] Sent cancel request for task ${taskId}`);
      } catch (error) {
        console.error(`[WebReadEmbedPreview] Failed to cancel task ${taskId}:`, error);
      }
    }
  }
</script>

<UnifiedEmbedPreview
  {id}
  appId="web"
  skillId="read"
  {skillIconName}
  {status}
  {skillName}
  {taskId}
  {isMobile}
  {onFullscreen}
  onStop={handleStop}
  faviconUrl={faviconUrl()}
>
  {#snippet details({ isMobile: isMobileLayout })}
    <div class="web-read-details" class:mobile={isMobileLayout}>
      <!-- Title row with favicon -->
      <div class="title-row">
        {#if faviconUrl()}
          <img 
            src={faviconUrl()} 
            alt="" 
            class="title-favicon"
            onerror={(e) => { (e.currentTarget as HTMLImageElement).style.display = 'none'; }}
          />
        {/if}
        <div class="read-title">{displayTitle}</div>
      </div>
      
      <!-- Subtitle: "via Firecrawl: X words" -->
      <div class="read-subtitle">{subtitleText()}</div>
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  /* ===========================================
     Web Read Details Content
     =========================================== */
  
  .web-read-details {
    display: flex;
    flex-direction: column;
    gap: 6px;
    height: 100%;
  }
  
  /* Desktop layout: vertically centered content */
  .web-read-details:not(.mobile) {
    justify-content: center;
  }
  
  /* Mobile layout: top-aligned content */
  .web-read-details.mobile {
    justify-content: flex-start;
  }
  
  /* Title row with favicon and title text */
  .title-row {
    display: flex;
    align-items: flex-start;
    gap: 8px;
  }
  
  /* Favicon next to title - rounded with white border */
  .title-favicon {
    width: 19px;
    height: 19px;
    min-width: 19px;
    border-radius: 9.5px;
    border: 1px solid white;
    background-color: white;
    object-fit: cover;
    flex-shrink: 0;
    margin-top: 2px; /* Align with first line of title */
  }
  
  /* Page title */
  .read-title {
    font-size: 16px;
    font-weight: 700;
    color: var(--color-grey-100);
    line-height: 1.3;
    /* Limit to 2 lines with ellipsis */
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
    text-overflow: ellipsis;
    word-break: break-word;
  }
  
  .web-read-details.mobile .read-title {
    font-size: 14px;
    -webkit-line-clamp: 3;
    line-clamp: 3;
  }
  
  /* Subtitle: "via Firecrawl: X words" */
  .read-subtitle {
    font-size: 14px;
    font-weight: 700;
    color: var(--color-grey-70);
    line-height: 1.4;
    white-space: pre-line; /* Preserve line breaks */
  }
  
  .web-read-details.mobile .read-subtitle {
    font-size: 12px;
  }
  
  /* ===========================================
     Skill Icon Styling (text icon)
     =========================================== */
  
  /* Web Read skill icon - "text" icon as per Figma design */
  :global(.unified-embed-preview .skill-icon[data-skill-icon="text"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/text.svg');
    mask-image: url('@openmates/ui/static/icons/text.svg');
  }
  
  :global(.unified-embed-preview.mobile .skill-icon[data-skill-icon="text"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/text.svg');
    mask-image: url('@openmates/ui/static/icons/text.svg');
  }
</style>
