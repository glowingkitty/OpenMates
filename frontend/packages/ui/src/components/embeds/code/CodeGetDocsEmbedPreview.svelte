<!--
  frontend/packages/ui/src/components/embeds/code/CodeGetDocsEmbedPreview.svelte
  
  Preview component for Code Get Docs skill embeds.
  Uses UnifiedEmbedPreview as base and provides get_docs-specific details content.
  
  Displays (similar to WebSearchEmbedPreview pattern):
  - Library title as the main title
  - "via Context7" as subtitle text (no icon)
  - Word count when finished
  
  Layout follows the same pattern as WebSearchEmbedPreview:
  - Title (library name)
  - Provider subtitle ("via Context7")
  - Word count info when finished
  
  Data Flow:
  - Receives results from backend GetDocsSkill which returns GetDocsResponse
  - Library info contains id (e.g., "/sveltejs/svelte"), title, description
  - Documentation is markdown text with word count
-->

<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { chatSyncService } from '../../../services/chatSyncService';
  import type { CodeGetDocsSkillPreviewData, CodeGetDocsResult, SkillExecutionStatus } from '../../../types/appSkills';
  import { text } from '@repo/ui';
  
  // ===========================================
  // Types
  // ===========================================
  
  /**
   * Props for code get docs embed preview
   * Supports both skill preview data format and direct embed format
   */
  interface Props {
    /** Unique embed ID */
    id: string;
    /** Processing status (direct format) */
    status?: 'processing' | 'finished' | 'error';
    /** Get docs results (direct format) */
    results?: CodeGetDocsResult[];
    /** Library name from request (for processing state) */
    library?: string;
    /** Task ID for cancellation of entire AI response */
    taskId?: string;
    /** Skill task ID for cancellation of just this skill (allows AI to continue) */
    skillTaskId?: string;
    /** Skill preview data (skill preview context) */
    previewData?: CodeGetDocsSkillPreviewData;
    /** Whether to use mobile layout */
    isMobile?: boolean;
    /** Click handler for fullscreen */
    onFullscreen?: () => void;
  }
  
  let {
    id,
    status: statusProp,
    results: resultsProp,
    library: libraryProp,
    taskId: taskIdProp,
    skillTaskId: skillTaskIdProp,
    previewData,
    isMobile = false,
    onFullscreen
  }: Props = $props();
  
  // ===========================================
  // Local state for embed data (updated via onEmbedDataUpdated callback)
  // CRITICAL: Using $state allows us to update these values when we receive embed updates
  // via the onEmbedDataUpdated callback from UnifiedEmbedPreview
  // ===========================================
  let localResults = $state<CodeGetDocsResult[]>([]);
  let localLibrary = $state<string>('');
  // Status type matches UnifiedEmbedPreview expectations (excludes 'cancelled')
  // We map 'cancelled' to 'error' for display purposes
  let localStatus = $state<'processing' | 'finished' | 'error'>('processing');
  let localSkillTaskId = $state<string | undefined>(undefined);
  
  /**
   * Map SkillExecutionStatus to UnifiedEmbedPreview status
   * 'cancelled' is mapped to 'error' since UnifiedEmbedPreview doesn't support it
   */
  function mapStatusToEmbedStatus(status: SkillExecutionStatus): 'processing' | 'finished' | 'error' {
    if (status === 'cancelled') {
      return 'error';
    }
    return status;
  }
  
  // Initialize local state from props
  $effect(() => {
    // Initialize from previewData or direct props
    if (previewData) {
      localResults = previewData.results || [];
      localLibrary = previewData.library || '';
      localStatus = mapStatusToEmbedStatus(previewData.status);
      // skill_task_id might be in previewData for skill-level cancellation
      localSkillTaskId = 'skill_task_id' in previewData ? (previewData as Record<string, unknown>).skill_task_id as string | undefined : undefined;
    } else {
      localResults = resultsProp || [];
      localLibrary = libraryProp || '';
      localStatus = statusProp || 'processing';
      localSkillTaskId = skillTaskIdProp;
    }
  });
  
  // Use local state as the source of truth (allows updates from embed events)
  let status = $derived(localStatus);
  let results = $derived(localResults);
  let taskId = $derived(previewData?.task_id || taskIdProp);
  let skillTaskId = $derived(localSkillTaskId);
  
  // Get first result for main display (may be undefined if results are empty)
  let firstResult = $derived(results[0]);
  
  /**
   * Handle embed data updates from UnifiedEmbedPreview
   * Called when the parent component receives and decodes updated embed data
   * This is the CENTRALIZED way to receive updates - no need for custom subscription
   */
  function handleEmbedDataUpdated(data: { status: string; decodedContent: Record<string, unknown> }) {
    console.debug(`[CodeGetDocsEmbedPreview] 🔄 Received embed data update for ${id}:`, {
      status: data.status,
      hasContent: !!data.decodedContent
    });
    
    // Update status - map SkillExecutionStatus to embed status
    if (data.status === 'processing' || data.status === 'finished' || data.status === 'error' || data.status === 'cancelled') {
      localStatus = mapStatusToEmbedStatus(data.status as SkillExecutionStatus);
    }
    
    // Update get-docs-specific fields from decoded content
    const content = data.decodedContent;
    if (content) {
      // Update results if available
      if (content.results && Array.isArray(content.results) && content.results.length > 0) {
        console.debug(`[CodeGetDocsEmbedPreview] ✅ Updated results from callback:`, content.results.length);
        localResults = content.results as CodeGetDocsResult[];
      }
      
      // Update library if available
      if (content.library && typeof content.library === 'string') {
        localLibrary = content.library;
      }
      
      // Extract skill_task_id for individual skill cancellation
      if (content.skill_task_id && typeof content.skill_task_id === 'string') {
        localSkillTaskId = content.skill_task_id;
      }
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
    return $text('embeds.get_docs.text') || 'Documentation';
  });
  
  // Library ID for display (e.g., "/sveltejs/svelte")
  let libraryId = $derived(firstResult?.library?.id || '');
  
  /**
   * Calculate word count from documentation
   */
  let wordCount = $derived.by(() => {
    if (!firstResult?.documentation) return 0;
    const words = firstResult.documentation.trim().split(/\s+/).filter(Boolean);
    return words.length;
  });
  
  // Provider text: "via Context7" (same pattern as WebSearchEmbedPreview)
  const viaProvider = 'via Context7';

  // Skill icon name - "docs" icon for documentation
  const skillIconName = 'docs';

  // Skill display name from translations
  let skillName = $derived($text('embeds.get_docs.text') || 'Get Docs');
  
  // Debug logging to help trace data flow issues
  $effect(() => {
    console.debug('[CodeGetDocsEmbedPreview] Rendering with:', {
      id,
      status,
      resultsCount: results.length,
      displayTitle,
      libraryId,
      wordCount,
      hasPreviewData: !!previewData
    });
  });
  
  /**
   * Handle stop button click - cancels this specific skill, not the entire AI response
   * Uses skill_task_id for individual skill cancellation (AI processing continues)
   */
  async function handleStop() {
    if (status !== 'processing') return;
    
    if (skillTaskId) {
      try {
        await chatSyncService.sendCancelSkill(skillTaskId, id);
        console.debug(`[CodeGetDocsEmbedPreview] Sent cancel_skill request for skill_task_id ${skillTaskId}`);
      } catch (error) {
        console.error(`[CodeGetDocsEmbedPreview] Failed to cancel skill ${skillTaskId}:`, error);
      }
    } else if (taskId) {
      console.warn(`[CodeGetDocsEmbedPreview] No skill_task_id, falling back to task cancellation`);
      try {
        await chatSyncService.sendCancelAiTask(taskId);
        console.debug(`[CodeGetDocsEmbedPreview] Sent cancel request for task ${taskId}`);
      } catch (error) {
        console.error(`[CodeGetDocsEmbedPreview] Failed to cancel task ${taskId}:`, error);
      }
    }
  }
</script>

<UnifiedEmbedPreview
  {id}
  appId="code"
  skillId="get_docs"
  {skillIconName}
  {status}
  {skillName}
  {taskId}
  {isMobile}
  {onFullscreen}
  onStop={handleStop}
  onEmbedDataUpdated={handleEmbedDataUpdated}
>
  {#snippet details({ isMobile: isMobileLayout })}
    <div class="get-docs-details" class:mobile={isMobileLayout}>
      <!-- Library title (main title) -->
      <div class="docs-title">{displayTitle}</div>
      
      <!-- Provider subtitle: "via Context7" (same pattern as WebSearchEmbedPreview) -->
      <div class="docs-provider">{viaProvider}</div>
      
      <!-- Word count info (shown when finished) -->
      {#if status === 'finished' && wordCount > 0}
        <div class="docs-info">
          <span class="word-count">{wordCount.toLocaleString()} words</span>
        </div>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  /* ===========================================
     Get Docs Details Content
     Follows WebSearchEmbedPreview pattern
     =========================================== */
  
  .get-docs-details {
    display: flex;
    flex-direction: column;
    gap: 4px;
    height: 100%;
  }
  
  /* Desktop layout: vertically centered content */
  .get-docs-details:not(.mobile) {
    justify-content: center;
  }
  
  /* Mobile layout: top-aligned content */
  .get-docs-details.mobile {
    justify-content: flex-start;
  }
  
  /* Library title (same pattern as .search-query in WebSearchEmbedPreview) */
  .docs-title {
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
  
  .get-docs-details.mobile .docs-title {
    font-size: 14px;
    -webkit-line-clamp: 4;
    line-clamp: 4;
  }
  
  /* Provider subtitle: "via Context7" (same pattern as .search-provider in WebSearchEmbedPreview) */
  .docs-provider {
    font-size: 14px;
    color: var(--color-grey-70);
    line-height: 1.3;
  }
  
  .get-docs-details.mobile .docs-provider {
    font-size: 12px;
  }
  
  /* Docs info (word count) - same pattern as .search-results-info */
  .docs-info {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-top: 4px;
  }
  
  .get-docs-details.mobile .docs-info {
    margin-top: 2px;
  }
  
  /* Word count - same pattern as .remaining-count */
  .word-count {
    font-size: 14px;
    color: var(--color-grey-70);
    font-weight: 500;
  }
  
  .get-docs-details.mobile .word-count {
    font-size: 12px;
  }
  
  /* ===========================================
     Skill Icon Styling (docs icon)
     =========================================== */
  
  /* Get Docs skill icon - "docs" icon for documentation */
  :global(.unified-embed-preview .skill-icon[data-skill-icon="docs"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/docs.svg');
    mask-image: url('@openmates/ui/static/icons/docs.svg');
  }
  
  :global(.unified-embed-preview.mobile .skill-icon[data-skill-icon="docs"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/docs.svg');
    mask-image: url('@openmates/ui/static/icons/docs.svg');
  }
</style>
