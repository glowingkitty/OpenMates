<!--
  frontend/packages/ui/src/components/app_skills/VideoTranscriptSkillFullscreen.svelte
  
  Fullscreen view for Video Transcript skill results.
  Shows video metadata, full transcript, and allows viewing both summary and original transcript.
  
  According to videos.md architecture:
  - Shows video title, channel, duration, views, likes
  - Full transcript text in scrollable view
  - Metadata display (title, description, channel, etc.)
  - "Open on YouTube" button
-->

<script lang="ts">
  import AppSkillFullscreenBase from './AppSkillFullscreenBase.svelte';
  import type { VideoTranscriptSkillPreviewData, VideoTranscriptResult } from '../../types/appSkills';
  
  // Props using Svelte 5 runes
  let {
    previewData,
    onClose
  }: {
    previewData: VideoTranscriptSkillPreviewData;
    onClose: () => void;
  } = $props();
  
  // Get results (should always be present in fullscreen view)
  let results = $derived(previewData.results || []);
  
  // Get first result for main display
  let firstResult = $derived(results[0]);
  
  // Format display title
  let displayTitle = $derived(
    firstResult?.metadata?.title || 
    firstResult?.url || 
    'Video Transcript'
  );
  
  // Type assertion for base component prop compatibility
  let previewDataForBase = $derived(previewData as any);
  
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
  
  // Format numbers with commas
  function formatNumber(num?: number): string {
    if (num === undefined || num === null) return 'N/A';
    return num.toLocaleString();
  }
  
  // Handle opening video on YouTube
  function handleOpenOnYouTube() {
    if (firstResult?.url) {
      window.open(firstResult.url, '_blank', 'noopener,noreferrer');
    }
  }
  
  // Handle share action (override base)
  function handleShare() {
    handleOpenOnYouTube();
  }
</script>

<!-- @ts-ignore - Svelte 5 type inference issue with component props -->
<AppSkillFullscreenBase 
  previewData={previewData as any} 
  title={displayTitle} 
  onClose={onClose} 
  onShare={handleShare}
>
  {#snippet headerExtra()}
    {#if results.length > 1}
      <div class="results-indicator">
        <div class="icon_rounded videos"></div>
        <span class="results-count">+{results.length - 1} more</span>
      </div>
    {/if}
    
    <!-- @ts-expect-error - onclick is valid Svelte 5 syntax -->
    <button class="open-button" onclick={handleOpenOnYouTube}>
      Open on YouTube
    </button>
  {/snippet}
  
  {#snippet content({ previewData })}
    {#if results.length === 0}
      <div class="no-results">
        <p>No transcript results available.</p>
      </div>
    {:else}
      {#each results as result, index}
        <div class="video-result">
          <!-- Video metadata section -->
          {#if result.metadata}
            <div class="metadata-section">
              {#if result.metadata.thumbnail_url}
                <div class="thumbnail-container">
                  <img 
                    src={result.metadata.thumbnail_url} 
                    alt={result.metadata.title || 'Video thumbnail'}
                    class="thumbnail"
                  />
                </div>
              {/if}
              
              <div class="metadata-content">
                {#if result.metadata.channel_title}
                  <div class="channel-name">{result.metadata.channel_title}</div>
                {/if}
                
                {#if result.metadata.view_count !== undefined || result.metadata.like_count !== undefined}
                  <div class="stats">
                    {#if result.metadata.view_count !== undefined}
                      <span class="stat-item">
                        <span class="stat-label">Views:</span> {formatNumber(result.metadata.view_count)}
                      </span>
                    {/if}
                    {#if result.metadata.like_count !== undefined}
                      <span class="stat-item">
                        <span class="stat-label">Likes:</span> {formatNumber(result.metadata.like_count)}
                      </span>
                    {/if}
                    {#if result.metadata.comment_count !== undefined}
                      <span class="stat-item">
                        <span class="stat-label">Comments:</span> {formatNumber(result.metadata.comment_count)}
                      </span>
                    {/if}
                    {#if result.metadata.duration}
                      <span class="stat-item">
                        <span class="stat-label">Duration:</span> {formatDuration(result.metadata.duration)}
                      </span>
                    {/if}
                  </div>
                {/if}
                
                {#if result.metadata.published_at}
                  <div class="published-date">
                    Published: {new Date(result.metadata.published_at).toLocaleDateString()}
                  </div>
                {/if}
              </div>
            </div>
          {/if}
          
          <!-- Transcript section -->
          {#if result.success && result.transcript}
            <div class="transcript-section">
              <div class="transcript-header">
                <h3>Transcript</h3>
                {#if result.word_count}
                  <span class="word-count">{result.word_count.toLocaleString()} words</span>
                {/if}
                {#if result.language}
                  <span class="language">Language: {result.language}</span>
                {/if}
                {#if result.is_generated}
                  <span class="generated-badge">Auto-generated</span>
                {/if}
              </div>
              
              <div class="transcript-content">
                {result.transcript}
              </div>
            </div>
          {:else if result.error}
            <div class="error-section">
              <p class="error-message">Failed to fetch transcript: {result.error}</p>
            </div>
          {/if}
          
          <!-- Video URL link -->
          {#if result.url}
            <div class="video-link">
              <a href={result.url} target="_blank" rel="noopener noreferrer" class="youtube-link">
                Watch on YouTube →
              </a>
            </div>
          {/if}
        </div>
        
        {#if index < results.length - 1}
          <hr class="result-divider" />
        {/if}
      {/each}
    {/if}
  {/snippet}
</AppSkillFullscreenBase>

<style>
  .results-indicator {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-top: 8px;
  }
  
  .results-count {
    font-size: 14px;
    color: var(--color-font-secondary);
  }
  
  .open-button {
    margin-top: 12px;
    padding: 12px 24px;
    background-color: var(--color-error);
    color: white;
    border: none;
    border-radius: 20px;
    font-size: 16px;
    font-weight: 500;
    cursor: pointer;
    transition: background-color 0.2s, transform 0.2s;
  }
  
  .open-button:hover {
    background-color: var(--color-error-dark);
    transform: translateY(-2px);
  }
  
  .no-results {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 200px;
    color: var(--color-font-secondary);
  }
  
  .video-result {
    margin-bottom: 32px;
  }
  
  /* Metadata section */
  .metadata-section {
    display: flex;
    gap: 16px;
    margin-bottom: 24px;
    padding: 16px;
    background-color: var(--color-grey-15);
    border-radius: 12px;
  }
  
  .thumbnail-container {
    flex-shrink: 0;
  }
  
  .thumbnail {
    width: 200px;
    height: 112px;
    object-fit: cover;
    border-radius: 8px;
    background-color: var(--color-grey-20);
  }
  
  .metadata-content {
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  
  .channel-name {
    font-size: 16px;
    font-weight: 500;
    color: var(--color-font-primary);
  }
  
  .stats {
    display: flex;
    flex-wrap: wrap;
    gap: 16px;
    font-size: 14px;
    color: var(--color-font-secondary);
  }
  
  .stat-item {
    display: flex;
    gap: 4px;
  }
  
  .stat-label {
    font-weight: 500;
  }
  
  .published-date {
    font-size: 14px;
    color: var(--color-font-tertiary);
  }
  
  /* Transcript section */
  .transcript-section {
    margin-bottom: 24px;
  }
  
  .transcript-header {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 16px;
    flex-wrap: wrap;
  }
  
  .transcript-header h3 {
    font-size: 20px;
    font-weight: 600;
    color: var(--color-font-primary);
    margin: 0;
  }
  
  .word-count {
    font-size: 14px;
    color: var(--color-font-secondary);
    background-color: var(--color-grey-15);
    padding: 4px 12px;
    border-radius: 12px;
  }
  
  .language {
    font-size: 14px;
    color: var(--color-font-secondary);
    background-color: var(--color-grey-15);
    padding: 4px 12px;
    border-radius: 12px;
  }
  
  .generated-badge {
    font-size: 12px;
    color: var(--color-font-secondary);
    background-color: var(--color-grey-20);
    padding: 4px 8px;
    border-radius: 8px;
  }
  
  .transcript-content {
    background-color: var(--color-grey-15);
    border-radius: 12px;
    padding: 20px;
    font-size: 15px;
    line-height: 1.6;
    color: var(--color-font-primary);
    white-space: pre-wrap;
    word-wrap: break-word;
    max-height: 600px;
    overflow-y: auto;
  }
  
  .transcript-content::-webkit-scrollbar {
    width: 8px;
  }
  
  .transcript-content::-webkit-scrollbar-track {
    background: transparent;
  }
  
  .transcript-content::-webkit-scrollbar-thumb {
    background-color: rgba(128, 128, 128, 0.3);
    border-radius: 4px;
  }
  
  /* Error section */
  .error-section {
    padding: 16px;
    background-color: rgba(var(--color-error-rgb), 0.1);
    border: 1px solid var(--color-error);
    border-radius: 12px;
    margin-bottom: 24px;
  }
  
  .error-message {
    color: var(--color-error);
    margin: 0;
  }
  
  /* Video link */
  .video-link {
    margin-top: 16px;
    text-align: center;
  }
  
  .youtube-link {
    color: var(--color-primary);
    text-decoration: none;
    font-size: 16px;
    font-weight: 500;
    transition: color 0.2s;
  }
  
  .youtube-link:hover {
    color: var(--color-primary-dark);
    text-decoration: underline;
  }
  
  /* Result divider */
  .result-divider {
    border: none;
    border-top: 1px solid var(--color-grey-20);
    margin: 32px 0;
  }
  
  /* Responsive adjustments */
  @media (max-width: 768px) {
    .metadata-section {
      flex-direction: column;
    }
    
    .thumbnail {
      width: 100%;
      height: auto;
      aspect-ratio: 16 / 9;
    }
    
    .stats {
      flex-direction: column;
      gap: 8px;
    }
  }
</style>

