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
  import VideoEmbedPreview from './VideoEmbedPreview.svelte';
  import type { VideoMetadata } from './VideoEmbedPreview.svelte';
  // @ts-expect-error - @repo/ui module exists at runtime
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
    /** Optional: Embed ID for sharing (from embed:{embed_id} contentRef) */
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
  let localResults = $state<VideoTranscriptResult[]>([]);
  
  // Initialize local state from props
  $effect(() => {
    // Initialize from previewData or direct props
    if (previewData) {
      localResults = previewData.results || [];
    } else {
      localResults = resultsProp || [];
    }
  });
  
  // Use local state as the source of truth (allows updates from embed events)
  let results = $derived(localResults);
  
  /**
   * Handle embed data updates from UnifiedEmbedFullscreen
   * Called when the parent component receives and decodes updated embed data
   * This is the CENTRALIZED way to receive updates - no need for custom subscription
   */
  function handleEmbedDataUpdated(data: { status: string; decodedContent: Record<string, unknown>; results?: unknown[] }) {
    console.debug(`[VideoTranscriptEmbedFullscreen] 🔄 Received embed data update for ${embedId}:`, {
      status: data.status,
      hasContent: !!data.decodedContent,
      hasResults: !!data.results,
      resultsCount: data.results?.length || 0
    });
    
    // Update video-transcript-specific fields from decoded content or results
    if (data.results && Array.isArray(data.results) && data.results.length > 0) {
      console.debug(`[VideoTranscriptEmbedFullscreen] ✅ Updated results from callback:`, data.results.length);
      localResults = data.results as VideoTranscriptResult[];
    } else if (data.decodedContent?.results && Array.isArray(data.decodedContent.results)) {
      console.debug(`[VideoTranscriptEmbedFullscreen] ✅ Updated results from decodedContent:`, data.decodedContent.results.length);
      localResults = data.decodedContent.results as VideoTranscriptResult[];
    }
  }
  
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
  let transcriptSkillName = $derived($text('embeds.transcript') || 'Transcript');
  
  // Format video title for top BasicInfosBar (video embed preview style)
  let videoTitle = $derived(
    firstResult?.metadata?.title || 
    'YouTube Video'
  );
  
  // Get video URL for opening video
  let videoUrl = $derived(firstResult?.url || '');
  
  // Get video ID from first result
  let videoId = $derived(firstResult?.video_id || '');
  
  // Get metadata from first result for VideoEmbedPreview
  // Maps the transcript metadata format to VideoEmbedPreview props
  let channelName = $derived(firstResult?.metadata?.channel_title || '');
  let channelId = $derived(firstResult?.metadata?.channel_id || '');
  let thumbnail = $derived(firstResult?.metadata?.thumbnail_url || '');
  let publishedAt = $derived(firstResult?.metadata?.published_at || '');
  let viewCount = $derived(firstResult?.metadata?.view_count);
  let likeCount = $derived(firstResult?.metadata?.like_count);
  
  // Parse duration string (e.g., "PT20M26S") to seconds and formatted string
  let durationData = $derived.by(() => {
    const durationStr = firstResult?.metadata?.duration;
    if (!durationStr) return undefined;
    
    // Parse ISO 8601 duration format (PT#H#M#S)
    const match = durationStr.match(/PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?/);
    if (!match) return undefined;
    
    const hours = parseInt(match[1] || '0', 10);
    const minutes = parseInt(match[2] || '0', 10);
    const seconds = parseInt(match[3] || '0', 10);
    
    const totalSeconds = hours * 3600 + minutes * 60 + seconds;
    
    // Format as HH:MM:SS or MM:SS
    let formatted: string;
    if (hours > 0) {
      formatted = `${hours}:${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
    } else {
      formatted = `${minutes}:${seconds.toString().padStart(2, '0')}`;
    }
    
    return { totalSeconds, formatted };
  });
  
  // Calculate total word count across all results
  let totalWordCount = $derived(
    results.reduce((sum, result) => sum + (result.word_count || 0), 0)
  );
  
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
  // Called by VideoEmbedPreview's onFullscreen callback with the fetched metadata
  // Dispatches embedfullscreen event with videos-video embed type
  // ActiveChat will handle closing current fullscreen and opening new one
  function handleVideoFullscreen(metadata: VideoMetadata) {
    if (!videoUrl) {
      console.debug('[VideoTranscriptEmbedFullscreen] No video URL available');
      return;
    }
    
    try {
      // Dispatch event to open video fullscreen
      // ActiveChat will handle closing the current fullscreen and opening the new one
      // Pass the full metadata from VideoEmbedPreview so fullscreen can display it
      const event = new CustomEvent('embedfullscreen', {
        detail: {
          embedType: 'videos-video',
          attrs: {
            url: videoUrl,
            title: metadata.title || videoTitle
          },
          decodedContent: {
            url: videoUrl,
            title: metadata.title || videoTitle,
            // Pass metadata to fullscreen view
            channelName: metadata.channelName,
            channelThumbnail: metadata.channelThumbnail,
            thumbnailUrl: metadata.thumbnailUrl,
            duration: metadata.duration,
            viewCount: metadata.viewCount,
            likeCount: metadata.likeCount,
            publishedAt: metadata.publishedAt
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
  
  // Handle copy - copies transcript as formatted markdown (same as download)
  async function handleCopy() {
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
        await navigator.clipboard.writeText(transcriptText);
        console.debug('[VideoTranscriptEmbedFullscreen] Copied transcript to clipboard');
        // Show success notification
        const { notificationStore } = await import('../../../stores/notificationStore');
        notificationStore.success('Transcript copied to clipboard');
      }
    } catch (error) {
      console.error('[VideoTranscriptEmbedFullscreen] Failed to copy transcript:', error);
      const { notificationStore } = await import('../../../stores/notificationStore');
      notificationStore.error('Failed to copy transcript to clipboard');
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
  
  // Handle share - opens share settings menu for this specific video transcript embed
  async function handleShare() {
    try {
      console.debug('[VideoTranscriptEmbedFullscreen] Opening share settings for video transcript embed:', {
        embedId,
        videoUrl,
        videoTitle,
        transcriptLength: transcriptText.length
      });

      // Check if we have embed_id for proper sharing
      if (!embedId) {
        console.warn('[VideoTranscriptEmbedFullscreen] No embed_id available - cannot create encrypted share link');
        const { notificationStore } = await import('../../../stores/notificationStore');
        notificationStore.error('Unable to share this video transcript embed. Missing embed ID.');
        return;
      }

      // Import required modules
      const { navigateToSettings } = await import('../../../stores/settingsNavigationStore');
      const { settingsDeepLink } = await import('../../../stores/settingsDeepLinkStore');
      const { panelState } = await import('../../../stores/panelStateStore');

      // Set embed context with embed_id for proper encrypted sharing
      const embedContext = {
        type: 'video-transcript',
        embed_id: embedId,
        url: videoUrl,
        title: videoTitle,
        transcript: transcriptText,
        wordCount: totalWordCount,
        metadata: firstResult?.metadata
      };

      // Store embed context for SettingsShare
      (window as any).__embedShareContext = embedContext;

      // Navigate to share settings
      navigateToSettings('shared/share', $text('settings.share.share_transcript', { default: 'Share Video Transcript' }), 'share', 'settings.share.share_transcript');
      
      // Also set settingsDeepLink to ensure Settings component navigates properly
      settingsDeepLink.set('shared/share');

      // Open settings panel
      panelState.openSettings();

      console.debug('[VideoTranscriptEmbedFullscreen] Opened share settings for video transcript embed');
    } catch (error) {
      console.error('[VideoTranscriptEmbedFullscreen] Error opening share settings:', error);
      const { notificationStore } = await import('../../../stores/notificationStore');
      notificationStore.error('Failed to open share menu. Please try again.');
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
  currentEmbedId={embedId}
  onEmbedDataUpdated={handleEmbedDataUpdated}
  showSkillIcon={true}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
  {showChatButton}
  {onShowChat}
>
  {#snippet content()}
    {#if results.length === 0}
      <div class="no-results">
        <p>No transcript results available.</p>
      </div>
    {:else}
      <div class="transcript-container">
        <!-- Top: Fully rendered VideoEmbedPreview - clickable to open video fullscreen -->
        <!-- Passes metadata from transcript results to VideoEmbedPreview -->
        {#if videoUrl}
          <div class="video-preview-wrapper">
            <VideoEmbedPreview
              id={`transcript-video-${embedId || 'preview'}`}
              url={videoUrl}
              title={videoTitle}
              status="finished"
              onFullscreen={handleVideoFullscreen}
              {videoId}
              {channelName}
              {channelId}
              {thumbnail}
              {publishedAt}
              {viewCount}
              {likeCount}
              durationSeconds={durationData?.totalSeconds}
              durationFormatted={durationData?.formatted}
            />
          </div>
        {/if}
        
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
  
  /* Video preview wrapper - centers the VideoEmbedPreview component */
  /* VideoEmbedPreview is 300x200px by default */
  .video-preview-wrapper {
    display: flex;
    justify-content: center;
    margin-bottom: 8px;
  }
  
  /* Remove the 3D tilt effect from the video preview in fullscreen context */
  /* The tilt effect looks odd when clicking opens another fullscreen layer */
  .video-preview-wrapper :global(.unified-embed-preview) {
    /* Keep the hover scale effect but reduce the tilt */
    transition: transform 0.15s ease-out, box-shadow 0.2s ease-out;
  }
  
  .video-preview-wrapper :global(.unified-embed-preview:hover) {
    box-shadow: 0 8px 20px rgba(0, 0, 0, 0.25);
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

