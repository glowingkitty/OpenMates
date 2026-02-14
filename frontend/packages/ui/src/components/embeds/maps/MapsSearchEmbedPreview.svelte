<!--
  frontend/packages/ui/src/components/embeds/MapsSearchEmbedPreview.svelte
  
  Preview component for Maps Search skill embeds.
  Uses UnifiedEmbedPreview as base and provides skill-specific details content.
  
  Details content structure:
  - Processing: query text + "via {provider}"
  - Finished: query text + "via {provider}" + place count
  
  NOTE: Real-time updates are handled by UnifiedEmbedPreview via embedUpdated events.
  This component implements onEmbedDataUpdated to update its specific data.
-->

<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  // @ts-ignore - @repo/ui module exists at runtime
  import { text } from '@repo/ui';
  import { chatSyncService } from '../../../services/chatSyncService';
  
  /**
   * Place search result interface
   */
  interface PlaceSearchResult {
    displayName?: string;
    formattedAddress?: string;
    location?: {
      latitude?: number;
      longitude?: number;
    };
    rating?: number;
    userRatingCount?: number;
  }
  
  /**
   * Props for maps search embed preview
   */
  interface Props {
    /** Unique embed ID */
    id: string;
    /** Search query */
    query: string;
    /** Search provider (e.g., 'Google') */
    provider: string;
    /** Processing status */
    status: 'processing' | 'finished' | 'error';
    /** Search results (for finished state) */
    results?: PlaceSearchResult[];
    /** Task ID for cancellation of entire AI response */
    taskId?: string;
    /** Skill task ID for cancellation of just this skill (allows AI to continue) */
    skillTaskId?: string;
    /** Whether to use mobile layout */
    isMobile?: boolean;
    /** Click handler for fullscreen */
    onFullscreen?: () => void;
  }
  
  let {
    id,
    query: queryProp,
    provider: providerProp,
    status: statusProp,
    results: resultsProp = [],
    taskId: taskIdProp,
    skillTaskId: skillTaskIdProp,
    isMobile = false,
    onFullscreen
  }: Props = $props();
  
  // Local reactive state for embed data
  let localQuery = $state<string>('');
  let localProvider = $state<string>('Google');
  let localStatus = $state<'processing' | 'finished' | 'error'>('processing');
  let localResults = $state<PlaceSearchResult[]>([]);
  let localTaskId = $state<string | undefined>(undefined);
  let localSkillTaskId = $state<string | undefined>(undefined);
  
  // Initialize local state from props
  $effect(() => {
    localQuery = queryProp || '';
    localProvider = providerProp || 'Google';
    localStatus = statusProp || 'processing';
    localResults = resultsProp || [];
    localTaskId = taskIdProp;
    localSkillTaskId = skillTaskIdProp;
  });
  
  // Use local state as the source of truth
  let query = $derived(localQuery);
  let provider = $derived(localProvider);
  let status = $derived(localStatus);
  let results = $derived(localResults);
  let taskId = $derived(localTaskId);
  let skillTaskId = $derived(localSkillTaskId);
  
  /**
   * Handle embed data updates from UnifiedEmbedPreview
   */
  function handleEmbedDataUpdated(data: { status: string; decodedContent: any }) {
    console.debug(`[MapsSearchEmbedPreview] 🔄 Received embed data update for ${id}`);
    
    if (data.status === 'processing' || data.status === 'finished' || data.status === 'error') {
      localStatus = data.status;
    }
    
    const content = data.decodedContent;
    if (content) {
      if (content.query) localQuery = content.query;
      if (content.provider) localProvider = content.provider;
      if (content.results && Array.isArray(content.results)) {
        localResults = content.results;
      }
      // Extract skill_task_id for individual skill cancellation
      if (content.skill_task_id) {
        localSkillTaskId = content.skill_task_id;
      }
    }
  }
  
  // Get skill name from translations
  let skillName = $derived($text('embeds.search'));
  
  // Map skillId to icon name - this is skill-specific logic
  const skillIconName = 'search';
  
  // Get "via {provider}" text from translations
  let viaProvider = $derived(
    `${$text('embeds.via')} ${provider}`
  );
  
  // Get results count
  let resultsCount = $derived(results?.length || 0);
  
  // Handle stop button click - cancels this specific skill, not the entire AI response
  async function handleStop() {
    if (status !== 'processing') return;
    
    if (skillTaskId) {
      try {
        await chatSyncService.sendCancelSkill(skillTaskId, id);
        console.debug(`[MapsSearchEmbedPreview] Sent cancel_skill request for skill_task_id ${skillTaskId}`);
      } catch (error) {
        console.error(`[MapsSearchEmbedPreview] Failed to cancel skill ${skillTaskId}:`, error);
      }
    } else if (taskId) {
      console.warn(`[MapsSearchEmbedPreview] No skill_task_id, falling back to task cancellation`);
      try {
        await chatSyncService.sendCancelAiTask(taskId);
        console.debug(`[MapsSearchEmbedPreview] Sent cancel request for task ${taskId}`);
      } catch (error) {
        console.error(`[MapsSearchEmbedPreview] Failed to cancel task ${taskId}:`, error);
      }
    }
  }
</script>

<UnifiedEmbedPreview
  {id}
  appId="maps"
  skillId="search"
  skillIconName={skillIconName}
  {status}
  {skillName}
  {taskId}
  {isMobile}
  {onFullscreen}
  onStop={handleStop}
  onEmbedDataUpdated={handleEmbedDataUpdated}
>
  {#snippet details({ isMobile: isMobileLayout })}
    <div class="maps-search-details" class:mobile={isMobileLayout}>
      <!-- Query text -->
      <div class="search-query">{query}</div>
      
      <!-- Provider subtitle -->
      <div class="search-provider">{viaProvider}</div>
      
      <!-- Finished state: show results count -->
      {#if status === 'finished' && resultsCount > 0}
        <div class="search-results-info">
          <span class="results-count">
            {resultsCount} {resultsCount === 1 ? $text('embeds.place') : $text('embeds.places')}
          </span>
        </div>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  /* ===========================================
     Maps Search Details Content
     =========================================== */
  
  .maps-search-details {
    display: flex;
    flex-direction: column;
    gap: 4px;
    height: 100%;
  }
  
  /* Desktop layout: vertically centered content */
  .maps-search-details:not(.mobile) {
    justify-content: center;
  }
  
  /* Mobile layout: top-aligned content */
  .maps-search-details.mobile {
    justify-content: flex-start;
  }
  
  /* Query text */
  .search-query {
    font-size: 16px;
    font-weight: 600;
    color: var(--color-grey-100);
    line-height: 1.3;
    /* Limit to 3 lines with ellipsis */
    display: -webkit-box;
    -webkit-line-clamp: 3;
    line-clamp: 3;
    -webkit-box-orient: vertical;
    overflow: hidden;
    text-overflow: ellipsis;
    word-break: break-word;
  }
  
  .maps-search-details.mobile .search-query {
    font-size: 14px;
    -webkit-line-clamp: 4;
    line-clamp: 4;
  }
  
  /* Provider subtitle */
  .search-provider {
    font-size: 14px;
    color: var(--color-grey-70);
    line-height: 1.3;
  }
  
  .maps-search-details.mobile .search-provider {
    font-size: 12px;
  }
  
  /* Search results info (results count) */
  .search-results-info {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-top: 4px;
  }
  
  .maps-search-details.mobile .search-results-info {
    margin-top: 2px;
  }
  
  /* Results count */
  .results-count {
    font-size: 14px;
    color: var(--color-grey-70);
    font-weight: 500;
  }
  
  .maps-search-details.mobile .results-count {
    font-size: 12px;
  }
  
  /* ===========================================
     Skill Icon Styling (skill-specific)
     =========================================== */
  
  /* Maps Search skill icon - this is skill-specific and belongs here, not in UnifiedEmbedPreview */
  :global(.unified-embed-preview .skill-icon[data-skill-icon="search"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/search.svg');
    mask-image: url('@openmates/ui/static/icons/search.svg');
  }
  
  :global(.unified-embed-preview.mobile .skill-icon[data-skill-icon="search"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/search.svg');
    mask-image: url('@openmates/ui/static/icons/search.svg');
  }
</style>

