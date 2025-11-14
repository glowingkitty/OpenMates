<!--
  frontend/packages/ui/src/components/app_skills/WebSearchSkillPreview.svelte
  
  Preview component for Web Search skill execution.
  Shows processing state and finished state with results preview.
  
  Matches Figma designs:
  - Processing: Shows search query, "via Brave Search", status bar with "Search Processing..."
  - Finished: Shows search query, result count, small overlapping preview images, "Search Completed"
  - Includes stop button during processing that cancels the task via WebSocket
-->

<script lang="ts">
  import AppSkillPreviewBase from './AppSkillPreviewBase.svelte';
  import type { WebSearchSkillPreviewData } from '../../types/appSkills';
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
    previewData: WebSearchSkillPreviewData;
    isMobile?: boolean;
    onFullscreen?: () => void;
  } = $props();
  
  // Format the search query
  let queryTitle = $derived(previewData.query);
  
  // Format the provider subtitle
  let providerSubtitle = $derived(
    `${$text('embeds.via.text')} ${previewData.provider}`
  );
  
  // Get result count for display
  let resultCount = $derived(
    previewData.results?.length || 0
  );
  
  // Format status text based on state
  let statusLabel = $derived($text('embeds.search.text'));
  let statusText = $derived(() => {
    if (previewData.status === 'processing') {
      return $text('embeds.processing.text');
    } else if (previewData.status === 'finished') {
      return $text('embeds.completed.text');
    }
    return 'Error';
  });
  
  // Get first few results for preview images (max 3 for overlapping display)
  let previewImageResults = $derived(
    previewData.results?.filter(r => r.preview_image_url).slice(0, 3) || []
  );
  
  // Get additional results count (excluding the first one shown)
  let additionalResultsCount = $derived(
    resultCount > 1 ? resultCount - 1 : 0
  );
  
  // Handle stop button click - cancel the skill execution
  async function handleStop() {
    if (previewData.status === 'processing' && previewData.task_id) {
      try {
        await chatSyncService.sendCancelAiTask(previewData.task_id);
        console.debug(`[WebSearchSkillPreview] Sent cancel request for task ${previewData.task_id}`);
      } catch (error) {
        console.error(`[WebSearchSkillPreview] Failed to cancel task ${previewData.task_id}:`, error);
      }
    }
  }
  
  // Prevent event propagation when clicking stop button
  function handleStopClick(e: MouseEvent) {
    e.stopPropagation();
    handleStop();
  }
</script>

<!-- @ts-ignore - Svelte 5 type inference issue with component props -->
<AppSkillPreviewBase 
    id={id}
    previewData={previewData}
    isMobile={isMobile}
    onFullscreen={onFullscreen}
>
  <svelte:fragment slot="content" let:useMobileLayout>
    {#if useMobileLayout}
      <!-- Mobile layout: vertical card matching Figma design -->
      <div class="mobile-content">
        <!-- Title section -->
        <div class="title-section">
          <div class="title">{queryTitle}</div>
          <div class="subtitle">{providerSubtitle}</div>
        </div>
        
        <!-- Preview images (only when finished, overlapping small circles) -->
        {#if previewData.status === 'finished' && previewImageResults.length > 0}
          <div class="preview-images">
            {#each previewImageResults as result, index}
              <div 
                class="preview-image-circle" 
                style="left: {13 + index * 11}px; z-index: {previewImageResults.length - index};"
              >
                <img 
                  src={result.preview_image_url} 
                  alt={result.title}
                />
              </div>
            {/each}
          </div>
        {/if}
        
        <!-- Results count indicator (only when finished) -->
        {#if previewData.status === 'finished' && additionalResultsCount > 0}
          <div class="results-indicator">
            {$text('embeds.more_results.text', { values: { count: additionalResultsCount } })}
          </div>
        {/if}
        
        <!-- Status bar -->
        <div class="status-bar">
          <div class="icon_rounded search"></div>
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
        <!-- Web icon -->
        <div class="icon_rounded web"></div>
        
        <!-- Title section -->
        <div class="title-section">
          <div class="title">{queryTitle}</div>
          <div class="subtitle">{providerSubtitle}</div>
        </div>
        
        <!-- Status bar -->
        <div class="status-bar">
          <div class="icon_rounded search"></div>
          <div class="status-content">
            <span class="status-label">{statusLabel}</span>
            <span class="status-text">{statusText}</span>
          </div>
        </div>
        
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
        
        <!-- Preview images (only when finished, overlapping small circles) -->
        {#if previewData.status === 'finished' && previewImageResults.length > 0}
          <div class="preview-images">
            {#each previewImageResults as result, index}
              <div 
                class="preview-image-circle" 
                style="left: {13 + index * 11}px; z-index: {previewImageResults.length - index};"
              >
                <img 
                  src={result.preview_image_url} 
                  alt={result.title}
                />
              </div>
            {/each}
          </div>
        {/if}
        
        <!-- Results count indicator (only when finished) -->
        {#if previewData.status === 'finished' && additionalResultsCount > 0}
          <div class="results-indicator">
            {$text('embeds.more_results.text', { values: { count: additionalResultsCount } })}
          </div>
        {/if}
      </div>
    {/if}
  </svelte:fragment>
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
  
  .mobile-content .preview-images {
    position: relative;
    height: 19px;
    margin: 8px 0;
  }
  
  .mobile-content .preview-image-circle {
    position: absolute;
    width: 19px;
    height: 19px;
    border-radius: 9.5px;
    border: 1px solid white;
    overflow: hidden;
    background: white;
  }
  
  .mobile-content .preview-image-circle img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    object-position: center;
  }
  
  .mobile-content .results-indicator {
    font-size: 14px;
    font-weight: bold;
    color: #898989;
    margin: 8px 0;
    text-align: center;
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
  
  .desktop-content .icon_rounded.web {
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
  
  .desktop-content .preview-images {
    position: relative;
    height: 19px;
    width: 52px;
    flex-shrink: 0;
  }
  
  .desktop-content .preview-image-circle {
    position: absolute;
    width: 19px;
    height: 19px;
    border-radius: 9.5px;
    border: 1px solid white;
    overflow: hidden;
    background: white;
  }
  
  .desktop-content .preview-image-circle img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    object-position: center;
  }
  
  .desktop-content .results-indicator {
    font-size: 14px;
    font-weight: bold;
    color: #898989;
    flex-shrink: 0;
  }
</style>

