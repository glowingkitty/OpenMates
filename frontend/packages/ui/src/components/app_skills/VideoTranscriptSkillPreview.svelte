<!--
  frontend/packages/ui/src/components/app_skills/VideoTranscriptSkillPreview.svelte
  
  Preview component for Video Transcript skill execution.
  Shows processing state and finished state with video transcript preview.
  
  Matches Figma designs:
  - Processing: Shows video title, "via YouTube Transcript API", status bar with "Transcript Processing..."
  - Finished: Shows video title, transcript word count, "Transcript Completed"
  - Includes stop button during processing that cancels the task via WebSocket
-->

<script lang="ts">
  import AppSkillPreviewBase from './AppSkillPreviewBase.svelte';
  import type { VideoTranscriptSkillPreviewData } from '../../types/appSkills';
  // @ts-ignore - @repo/ui module exists at runtime
  import { text } from '@repo/ui';
  import { chatSyncService } from '../../services/chatSyncService';
  
  // Props using Svelte 5 runes
  let {
    id,
    previewData,
    isMobile = false,
    onFullscreen
  }: {
    id: string;
    previewData: VideoTranscriptSkillPreviewData;
    isMobile?: boolean;
    onFullscreen?: () => void;
  } = $props();
  
  // Get first video result for display
  let firstResult = $derived(previewData.results?.[0]);
  
  // Format the video title (from metadata or URL)
  let videoTitle = $derived(
    firstResult?.metadata?.title || 
    firstResult?.url || 
    'Video Transcript'
  );
  
  // Format the provider subtitle
  let providerSubtitle = $derived(
    `${$text('embeds.via.text')} YouTube Transcript API`
  );
  
  // Get transcript word count for display
  let wordCount = $derived(
    firstResult?.word_count || 0
  );
  
  // Format status text based on state
  let statusLabel = $derived($text('embeds.transcript.text'));
  let statusText = $derived(() => {
    if (previewData.status === 'processing') {
      return $text('embeds.processing.text');
    } else if (previewData.status === 'finished') {
      return $text('embeds.completed.text');
    }
    return 'Error';
  });
  
  // Get video count for display
  let videoCount = $derived(
    previewData.video_count || previewData.results?.length || 0
  );
  
  // Handle stop button click - cancel the skill execution
  async function handleStop() {
    if (previewData.status === 'processing' && previewData.task_id) {
      try {
        await chatSyncService.sendCancelAiTask(previewData.task_id);
        console.debug(`[VideoTranscriptSkillPreview] Sent cancel request for task ${previewData.task_id}`);
      } catch (error) {
        console.error(`[VideoTranscriptSkillPreview] Failed to cancel task ${previewData.task_id}:`, error);
      }
    }
  }
  
  // Prevent event propagation when clicking stop button
  function handleStopClick(e: MouseEvent) {
    e.stopPropagation();
    handleStop();
  }
</script>

<!-- Content snippet for AppSkillPreviewBase -->
{#snippet content({ useMobileLayout })}
  {#if useMobileLayout}
    <!-- Mobile layout: vertical card matching Figma design -->
    <div class="mobile-content">
      <!-- Title section -->
      <div class="title-section">
        <div class="title">{videoTitle}</div>
        <div class="subtitle">{providerSubtitle}</div>
      </div>
      
      <!-- Word count indicator (only when finished) -->
      {#if previewData.status === 'finished' && wordCount > 0}
        <div class="word-count-indicator">
          {wordCount.toLocaleString()} {wordCount === 1 ? 'word' : 'words'}
        </div>
      {/if}
      
      <!-- Video count indicator (when multiple videos) -->
      {#if previewData.status === 'finished' && videoCount > 1}
        <div class="video-count-indicator">
          {videoCount} {videoCount === 1 ? 'video' : 'videos'}
        </div>
      {/if}
      
      <!-- Status bar -->
      <div class="status-bar">
        <div class="icon_rounded video"></div>
        <div class="status-content">
          <span class="status-label">{statusLabel}</span>
          <span class="status-text">{statusText}</span>
        </div>
      </div>
      
      <!-- Stop button (only when processing) -->
      {#if previewData.status === 'processing'}
        <!-- @ts-expect-error - onclick is valid Svelte 5 syntax -->
        <button 
          class="stop-button"
          onclick={handleStopClick}
          aria-label={$text('embeds.stop.text')}
          title={$text('embeds.stop.text')}
        >
          <span class="clickable-icon icon_stop_processing"></span>
        </button>
      {/if}
    </div>
  {:else}
    <!-- Desktop layout: horizontal card matching Figma design -->
    <div class="desktop-content">
      <!-- Videos icon -->
      <div class="icon_rounded video"></div>
      
      <!-- Title section -->
      <div class="title-section">
        <div class="title">{videoTitle}</div>
        <div class="subtitle">{providerSubtitle}</div>
      </div>
      
      <!-- Status bar -->
      <div class="status-bar">
        <div class="icon_rounded video"></div>
        <div class="status-content">
          <span class="status-label">{statusLabel}</span>
          <span class="status-text">{statusText}</span>
        </div>
      </div>
      
      <!-- Word count indicator (only when finished) -->
      {#if previewData.status === 'finished' && wordCount > 0}
        <div class="word-count-indicator">
          {wordCount.toLocaleString()} {wordCount === 1 ? 'word' : 'words'}
        </div>
      {/if}
      
      <!-- Video count indicator (when multiple videos) -->
      {#if previewData.status === 'finished' && videoCount > 1}
        <div class="video-count-indicator">
          {videoCount} {videoCount === 1 ? 'video' : 'videos'}
        </div>
      {/if}
      
      <!-- Stop button (only when processing, positioned on right) -->
      {#if previewData.status === 'processing'}
        <!-- @ts-expect-error - onclick is valid Svelte 5 syntax -->
        <button 
          class="stop-button"
          onclick={handleStopClick}
          aria-label={$text('embeds.stop.text')}
          title={$text('embeds.stop.text')}
        >
          <span class="clickable-icon icon_stop_processing"></span>
        </button>
      {/if}
    </div>
  {/if}
{/snippet}

<!-- @ts-ignore - Svelte 5 type inference issue with component props -->
<AppSkillPreviewBase 
    id={id}
    previewData={previewData}
    isMobile={isMobile}
    onFullscreen={onFullscreen}
    {content}
>
</AppSkillPreviewBase>

<style>
  /* Mobile layout styles matching Figma design */
  .mobile-content {
    display: flex;
    flex-direction: column;
    width: 100%;
    position: relative;
  }
  
  .mobile-content .title-section {
    display: flex;
    flex-direction: column;
    gap: 0;
    margin-bottom: 8px;
  }
  
  .mobile-content .title {
    font-size: 16px;
    font-weight: bold;
    color: var(--color-font-primary);
    line-height: normal;
    word-break: break-word;
  }
  
  .mobile-content .subtitle {
    font-size: 14px;
    color: #858585;
    line-height: normal;
  }
  
  .mobile-content .word-count-indicator {
    font-size: 14px;
    font-weight: bold;
    color: #898989;
    margin: 8px 0;
  }
  
  .mobile-content .video-count-indicator {
    font-size: 14px;
    font-weight: bold;
    color: #898989;
    margin: 4px 0;
  }
  
  .mobile-content .status-bar {
    display: flex;
    align-items: center;
    gap: 8px;
    background-color: #f8f8f8;
    border: 1px solid #e2e2e2;
    border-radius: 30px;
    padding: 0 16px;
    height: 61px;
    margin-top: auto;
  }
  
  .mobile-content .status-content {
    display: flex;
    flex-direction: column;
    justify-content: center;
    line-height: normal;
  }
  
  .mobile-content .status-label {
    font-size: 16px;
    font-weight: bold;
    color: var(--color-font-primary);
  }
  
  .mobile-content .status-text {
    font-size: 16px;
    font-weight: bold;
    color: #868686;
  }
  
  .mobile-content .stop-button {
    position: absolute;
    bottom: 0;
    left: 50%;
    transform: translateX(-50%);
    width: 35px;
    height: 35px;
    background: none;
    border: none;
    padding: 0;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
  }
  
  .mobile-content .stop-button .clickable-icon.icon_stop_processing {
    width: 35px;
    height: 35px;
    background-color: red;
  }
  
  /* Desktop layout styles matching Figma design */
  .desktop-content {
    display: flex;
    align-items: center;
    gap: 14px;
    width: 100%;
    position: relative;
  }
  
  .desktop-content .icon_rounded.videos {
    width: 26px;
    height: 26px;
    flex-shrink: 0;
  }
  
  .desktop-content .title-section {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 0;
  }
  
  .desktop-content .title {
    font-size: 16px;
    font-weight: bold;
    color: var(--color-font-primary);
    line-height: normal;
    word-break: break-word;
  }
  
  .desktop-content .subtitle {
    font-size: 14px;
    color: #858585;
    line-height: normal;
  }
  
  .desktop-content .status-bar {
    display: flex;
    align-items: center;
    gap: 8px;
    background-color: #f8f8f8;
    border: 1px solid #e2e2e2;
    border-radius: 30px;
    padding: 0 16px;
    height: 61px;
    white-space: nowrap;
  }
  
  .desktop-content .status-content {
    display: flex;
    flex-direction: column;
    justify-content: center;
    line-height: normal;
  }
  
  .desktop-content .status-label {
    font-size: 16px;
    font-weight: bold;
    color: var(--color-font-primary);
  }
  
  .desktop-content .status-text {
    font-size: 16px;
    font-weight: bold;
    color: #868686;
  }
  
  .desktop-content .word-count-indicator {
    font-size: 14px;
    font-weight: bold;
    color: #898989;
    flex-shrink: 0;
  }
  
  .desktop-content .video-count-indicator {
    font-size: 14px;
    font-weight: bold;
    color: #898989;
    flex-shrink: 0;
  }
  
  .desktop-content .stop-button {
    width: 35px;
    height: 35px;
    background: none;
    border: none;
    padding: 0;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
  }
  
  .desktop-content .stop-button .clickable-icon.icon_stop_processing {
    width: 35px;
    height: 35px;
    background-color: red;
  }
</style>

