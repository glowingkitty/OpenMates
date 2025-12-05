<!--
  frontend/packages/ui/src/components/embeds/videos/VideoTranscriptEmbedFullscreen.svelte
  
  Fullscreen view for Video Transcript skill embeds.
  Uses UnifiedEmbedFullscreen as base and provides video transcript-specific content.
  
  Supports both contexts:
  - Skill preview context: receives previewData from skillPreviewService
  - Embed context: receives results directly
  
  Shows video metadata, full transcript, and allows viewing both summary and original transcript.
-->

<script lang="ts">
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import BasicInfosBar from '../BasicInfosBar.svelte';
  // @ts-ignore - @repo/ui module exists at runtime
  import { text } from '@repo/ui';
  import type { VideoTranscriptSkillPreviewData, VideoTranscriptResult } from '../../../types/appSkills';
  
  /**
   * Props for video transcript embed fullscreen
   * Supports both skill preview data format and direct embed format
   */
  interface Props {
    /** Video transcript results (direct format) */
    results?: VideoTranscriptResult[];
    /** Skill preview data (skill preview context) */
    previewData?: VideoTranscriptSkillPreviewData;
    /** Close handler */
    onClose: () => void;
    /** Optional embed ID for the video embed (used to open video fullscreen) */
    videoEmbedId?: string;
  }
  
  let {
    results: resultsProp,
    previewData,
    onClose,
    videoEmbedId
  }: Props = $props();
  
  // Extract values from either previewData (skill preview context) or direct props (embed context)
  let results = $derived(previewData?.results || resultsProp || []);
  
  // DEBUG: Log results to understand data format
  $effect(() => {
    console.debug('[VideoTranscriptEmbedFullscreen] Results:', {
      resultsLength: results?.length,
      previewData: previewData,
      resultsProp: resultsProp,
      firstResult: results?.[0]
    });
  });
  
  // Get first result for main display
  let firstResult = $derived(results[0]);
  
  // Get skill name for bottom BasicInfosBar (same as VideoTranscriptEmbedPreview)
  // This should show "Transcript" not the URL
  let transcriptSkillName = $derived($text('embeds.transcript.text') || 'Transcript');
  
  // Format video title for top BasicInfosBar (video embed preview style)
  let videoTitle = $derived(
    firstResult?.metadata?.title || 
    'YouTube Video'
  );
  
  // Get video URL for opening video
  let videoUrl = $derived(firstResult?.url || '');
  
  // Calculate total word count across all results
  let totalWordCount = $derived(
    results.reduce((sum, result) => sum + (result.word_count || 0), 0)
  );
  
  // Format duration (ISO 8601 to readable format)
  function formatDuration(duration?: string): string {
    if (!duration) return '';
    
    // Parse ISO 8601 duration (e.g., PT9M41S)
    const match = duration.match(/PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?/);
    if (!match) return duration;
    
    const hours = parseInt(match[1] || '0', 10);
    const minutes = parseInt(match[2] || '0', 10);
    const seconds = parseInt(match[3] || '0', 10);
    
    if (hours > 0) {
      return `${hours}:${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
    }
    return `${minutes}:${seconds.toString().padStart(2, '0')}`;
  }
  
  // Format date for top BasicInfosBar (from metadata.published_at)
  let formattedDate = $derived.by(() => {
    if (firstResult?.metadata?.published_at) {
      const date = new Date(firstResult.metadata.published_at);
      return date.toLocaleDateString('en-US', { 
        month: 'short', 
        day: 'numeric', 
        year: 'numeric' 
      });
    }
    return '';
  });
  
  // Format duration for top BasicInfosBar
  let formattedDuration = $derived(
    firstResult?.metadata?.duration ? formatDuration(firstResult.metadata.duration) : ''
  );
  
  // Format date and duration string for top BasicInfosBar (e.g., "29:26, Jul 31, 2025")
  let dateDurationString = $derived.by(() => {
    const parts = [];
    if (formattedDuration) {
      parts.push(formattedDuration);
    }
    if (formattedDate) {
      parts.push(formattedDate);
    }
    return parts.join(', ');
  });
  
  // Get transcript text from results (handles both formats)
  let transcriptText = $derived.by(() => {
    if (!results || results.length === 0) {
      console.debug('[VideoTranscriptEmbedFullscreen] No results available');
      return '';
    }
    
    // Try to get transcript from first result
    const result = results[0] as any;
    
    // Check various possible field names for transcript
    if (result?.transcript) {
      console.debug('[VideoTranscriptEmbedFullscreen] Found transcript field');
      return result.transcript;
    }
    
    // Try formatted_transcript if available
    if (result?.formatted_transcript) {
      console.debug('[VideoTranscriptEmbedFullscreen] Found formatted_transcript field');
      return result.formatted_transcript;
    }
    
    // Try text field
    if (result?.text) {
      console.debug('[VideoTranscriptEmbedFullscreen] Found text field');
      return result.text;
    }
    
    // Try content field
    if (result?.content) {
      console.debug('[VideoTranscriptEmbedFullscreen] Found content field');
      return result.content;
    }
    
    console.debug('[VideoTranscriptEmbedFullscreen] No transcript text found in result:', result);
    return '';
  });
  
  /**
   * Parse transcript text into HTML with styled timestamps.
   * Timestamps like [00:00:00.240] are wrapped in span.timestamp (without brackets).
   * Regular text keeps its formatting.
   * Newlines are preserved with CSS white-space: pre-wrap.
   */
  function parseTranscriptToHtml(text: string): string {
    if (!text) return '';
    
    // Escape HTML special characters to prevent XSS
    let escaped = text
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
    
    // Match timestamps like [00:00:00.240] or [00:00:05.123] or [0:00:00.000]
    // Replace with styled spans - timestamp without brackets
    return escaped.replace(
      /\[(\d{1,2}:\d{2}:\d{2}(?:\.\d+)?)\]/g,
      '<span class="timestamp">$1</span>'
    );
  }
  
  // Parsed transcript HTML for styled rendering
  let parsedTranscriptHtml = $derived(parseTranscriptToHtml(transcriptText));
  
  // Handle opening video embed in fullscreen mode
  // Dispatches embedfullscreen event with videos-video embed type
  // Note: This will close the current transcript fullscreen and open video fullscreen
  async function handleVideoFullscreen() {
    if (!videoUrl) {
      console.debug('[VideoTranscriptEmbedFullscreen] No video URL available');
      return;
    }
    
    try {
      // Close the current transcript fullscreen first
      onClose();
      
      // Wait a brief moment for the close animation
      await new Promise(resolve => setTimeout(resolve, 100));
      
      // Dispatch event to open video fullscreen
      const event = new CustomEvent('embedfullscreen', {
        detail: {
          embedType: 'videos-video',
          attrs: {
            url: videoUrl,
            title: videoTitle
          },
          decodedContent: {
            url: videoUrl,
            title: videoTitle
          },
          onClose: () => {
            console.debug('[VideoTranscriptEmbedFullscreen] Video fullscreen closed');
          }
        },
        bubbles: true
      });
      
      document.dispatchEvent(event);
      console.debug('[VideoTranscriptEmbedFullscreen] Dispatched video embed fullscreen event with URL:', videoUrl);
    } catch (error) {
      console.error('[VideoTranscriptEmbedFullscreen] Error opening video embed fullscreen:', error);
      // Final fallback: open video URL in new tab
      if (videoUrl) {
        window.open(videoUrl, '_blank', 'noopener,noreferrer');
      }
    }
  }
  
  // Handle copy - copies transcript text to clipboard
  async function handleCopy() {
    try {
      const transcriptText = results
        .filter(r => r.transcript)
        .map(r => r.transcript)
        .join('\n\n');
      
      if (transcriptText) {
        await navigator.clipboard.writeText(transcriptText);
        console.debug('[VideoTranscriptEmbedFullscreen] Copied transcript to clipboard');
      }
    } catch (error) {
      console.error('[VideoTranscriptEmbedFullscreen] Failed to copy transcript:', error);
    }
  }
  
  // Handle download - downloads transcript as markdown file
  function handleDownload() {
    try {
      const transcriptText = results
        .filter(r => r.transcript)
        .map((r, index) => {
          let content = '';
          if (r.metadata?.title) {
            content += `# ${r.metadata.title}\n\n`;
          }
          if (r.url) {
            content += `Source: ${r.url}\n\n`;
          }
          if (r.word_count) {
            content += `Word count: ${r.word_count.toLocaleString()}\n\n`;
          }
          content += r.transcript || '';
          return content;
        })
        .join('\n\n---\n\n');
      
      if (transcriptText) {
        const blob = new Blob([transcriptText], { type: 'text/markdown' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `${videoTitle.replace(/[^a-z0-9]/gi, '_').toLowerCase()}_transcript.md`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        console.debug('[VideoTranscriptEmbedFullscreen] Downloaded transcript as markdown');
      }
    } catch (error) {
      console.error('[VideoTranscriptEmbedFullscreen] Failed to download transcript:', error);
    }
  }
  
  // Handle share - opens share menu (placeholder for now)
  function handleShare() {
    // TODO: Implement share functionality for video transcript embeds
    console.debug('[VideoTranscriptEmbedFullscreen] Share action (not yet implemented)');
  }
  
  // Handle opening video on YouTube
  function handleOpenOnYouTube() {
    if (firstResult?.url) {
      window.open(firstResult.url, '_blank', 'noopener,noreferrer');
    }
  }
</script>

<UnifiedEmbedFullscreen
  appId="videos"
  skillId="get_transcript"
  title=""
  {onClose}
  onCopy={handleCopy}
  onDownload={handleDownload}
  onShare={handleShare}
  skillIconName="transcript"
  status="finished"
  skillName={transcriptSkillName}
  showSkillIcon={true}
>
  {#snippet content()}
    {#if results.length === 0}
      <div class="no-results">
        <p>No transcript results available.</p>
      </div>
    {:else}
      <div class="transcript-container">
        <!-- Top: Clickable VideoEmbedPreview-style BasicInfosBar (max-width 300px) -->
        <button 
          class="video-basic-infos-bar-wrapper"
          onclick={handleVideoFullscreen}
          type="button"
        >
          <BasicInfosBar
            appId="videos"
            skillId="video"
            skillIconName="video"
            status="finished"
            skillName={videoTitle}
            showSkillIcon={false}
            showStatus={false}
          />
        </button>
        
        <!-- Word count centered above transcript -->
        {#if totalWordCount > 0}
          <div class="word-count-header">
            {totalWordCount.toLocaleString()} words:
          </div>
        {/if}
        
        <!-- Transcript content box with styled timestamps -->
        <div class="transcript-box">
          {#if parsedTranscriptHtml}
            <!-- Render transcript with styled timestamps using @html -->
            <div class="transcript-content">{@html parsedTranscriptHtml}</div>
          {:else if transcriptText}
            <!-- Fallback: render plain text if parsing failed -->
            <div class="transcript-content">{transcriptText}</div>
          {:else}
            <!-- Try to render each result's transcript -->
            {#each results as result, index}
              {@const resultAny = result as any}
              {#if result.transcript}
                <div class="transcript-content">{@html parseTranscriptToHtml(result.transcript)}</div>
              {:else if resultAny.formatted_transcript}
                <div class="transcript-content">{@html parseTranscriptToHtml(resultAny.formatted_transcript)}</div>
              {:else if result.error}
                <div class="error-section">
                  <p class="error-message">Failed to fetch transcript: {result.error}</p>
                </div>
              {:else if result.success === false}
                <div class="error-section">
                  <p class="error-message">Transcript unavailable</p>
                </div>
              {:else}
                <div class="error-section">
                  <p class="error-message">No transcript content available</p>
                </div>
              {/if}
            {/each}
          {/if}
        </div>
      </div>
    {/if}
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  /* ===========================================
     Video Transcript Fullscreen - Layout
     =========================================== */
  
  .no-results {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 200px;
    color: var(--color-font-secondary);
  }
  
  /* Transcript container - centers all content */
  .transcript-container {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 16px;
    width: 100%;
    margin-top: 80px;
  }
  
  /* Video BasicInfosBar wrapper - full width but max 300px */
  .video-basic-infos-bar-wrapper {
    width: 100%;
    max-width: 300px;
    display: flex;
    justify-content: flex-start;
    margin-bottom: 8px;
    background: transparent;
    border: none;
    padding: 0;
    cursor: pointer;
    transition: opacity 0.2s;
  }
  
  /* Ensure BasicInfosBar inside wrapper respects max-width and has grey-30 background */
  .video-basic-infos-bar-wrapper :global(.basic-infos-bar) {
    width: 100%;
    max-width: 300px;
    background-color: var(--color-grey-30) !important;
  }
  
  /* Ensure text is left-aligned in the BasicInfosBar */
  .video-basic-infos-bar-wrapper :global(.basic-infos-bar .status-text) {
    text-align: left;
    align-items: flex-start;
  }
  
  .video-basic-infos-bar-wrapper :global(.basic-infos-bar .status-label) {
    text-align: left;
    justify-content: flex-start;
  }
  
  .video-basic-infos-bar-wrapper:hover {
    opacity: 0.9;
  }
  
  /* Word count header - centered above transcript */
  .word-count-header {
    font-weight: 600;
    color: var(--color-font-primary);
    width: 100%;
    max-width: 722px;
    text-align: center;
  }
  
  /* Transcript box - rounded edges, drop shadow, grey-10 background */
  .transcript-box {
    width: auto;
    max-width: 722px;
    background-color: var(--color-grey-10);
    border-radius: 16px;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
    padding: 20px;
  }
  
  /* Transcript content - selectable text with preserved whitespace */
  .transcript-content {
    line-height: 1.8;
    width: 100%;
    user-select: text;
    -webkit-user-select: text;
    -moz-user-select: text;
    -ms-user-select: text;
    cursor: text;
    white-space: pre-wrap;
    word-wrap: break-word;
    color: var(--color-grey-100);
  }
  
  /* Timestamp styling - grey-80, no brackets */
  .transcript-content :global(.timestamp) {
    color: var(--color-grey-80);
    font-family: monospace;
    margin-right: 10px;
  }
  
  /* Error section */
  .error-section {
    padding: 16px;
    background-color: rgba(var(--color-error-rgb), 0.1);
    border: 1px solid var(--color-error);
    border-radius: 12px;
    width: 100%;
  }
  
  .error-message {
    color: var(--color-error);
    margin: 0;
  }
  
  /* ===========================================
     Skill Icon Styling (skill-specific)
     =========================================== */
  
  /* Video Transcript skill icon - this is skill-specific and belongs here, not in UnifiedEmbedFullscreen */
  /* Add styles for both the bottom BasicInfosBar and any skill icons in the content area */
  :global(.unified-embed-fullscreen-overlay .skill-icon[data-skill-icon="transcript"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/transcript.svg');
    mask-image: url('@openmates/ui/static/icons/transcript.svg');
  }
</style>

