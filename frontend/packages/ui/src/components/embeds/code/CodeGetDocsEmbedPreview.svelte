<!--
  frontend/packages/ui/src/components/embeds/code/CodeGetDocsEmbedPreview.svelte
  
  Preview component for Code Get Docs skill embeds.
  Uses UnifiedEmbedPreview as base and provides get_docs-specific details content.
  
  Displays:
  - Selected library ID (e.g., "/sveltejs/svelte")
  - Query/question that was asked
  - "via Context7" provider attribution
  - Word count when finished
  
  Layout:
  - Library ID (selected library)
  - Query (question asked)
  - "via Context7"
  - Word count (when finished)
  
  Data Flow:
  - Receives embed data with `library` (input) and `question` (input) fields
  - Results contain: library object (id, title), documentation, word_count
  - Library ID comes from results (library.id or library_id)
  - Question comes from embed metadata (question field)
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
    /** Question/query that was asked (for display) */
    question?: string;
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
    question: questionProp,
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
  let localQuestion = $state<string>('');
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
      localQuestion = previewData.question || '';
      localStatus = mapStatusToEmbedStatus(previewData.status);
      // skill_task_id might be in previewData for skill-level cancellation
      localSkillTaskId = 'skill_task_id' in previewData ? (previewData as Record<string, unknown>).skill_task_id as string | undefined : undefined;
    } else {
      localResults = resultsProp || [];
      localLibrary = libraryProp || '';
      localQuestion = questionProp || '';
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
      
      // Update library if available (input library name)
      if (content.library && typeof content.library === 'string') {
        localLibrary = content.library;
      }
      
      // Update question if available (the query that was asked)
      if (content.question && typeof content.question === 'string') {
        localQuestion = content.question;
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
  
  // ===========================================
  // Helper functions to handle both flat and nested structures
  // Backend may send: { library_id, library_title } OR { library: { id, title } }
  // ===========================================
  
  /**
   * Get library ID from result, handling both flat and nested structures
   */
  function getLibraryId(result: CodeGetDocsResult | undefined): string {
    if (!result) return '';
    // Try flat structure first (library_id)
    if (result.library_id) return result.library_id;
    // Try nested structure (library.id)
    if (result.library?.id) return result.library.id;
    return '';
  }

  // Library ID for display (e.g., "/sveltejs/svelte")
  // This is the SELECTED library from Context7 - shown as main identifier
  let libraryId = $derived.by(() => {
    const libId = getLibraryId(firstResult);
    // If we have a selected library ID from results, use it
    if (libId) return libId;
    // Fallback to input library name during processing
    if (localLibrary) return localLibrary;
    return '';
  });
  
  // Query/question that was asked - displayed below library ID
  let displayQuestion = $derived(localQuestion || '');
  
  /**
   * Get word count from backend-provided field
   * The word_count is calculated by the backend GetDocsSkill and stored in IndexedDB
   * We do NOT calculate this client-side - the backend is the source of truth
   */
  let wordCount = $derived(firstResult?.word_count || 0);
  
  // Provider text: "via Context7" (same pattern as WebSearchEmbedPreview)
  const viaProvider = 'via Context7';

  // Skill icon name - "docs" icon for documentation
  const skillIconName = 'docs';

  // Skill display name from translations
  let skillName = $derived($text('embeds.get_docs'));
  
  // Debug logging to help trace data flow issues
  $effect(() => {
    console.debug('[CodeGetDocsEmbedPreview] Rendering with:', {
      id,
      status,
      resultsCount: results.length,
      libraryId,
      displayQuestion,
      // word_count is provided by backend GetDocsSkill (not calculated client-side)
      wordCount,
      wordCountFromBackend: firstResult?.word_count,
      hasPreviewData: !!previewData,
      localLibrary,
      localQuestion
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
      <!-- Library ID (selected library from Context7) -->
      {#if libraryId}
        <div class="docs-library-id">{libraryId}</div>
      {/if}
      
      <!-- Question/query that was asked -->
      {#if displayQuestion}
        <div class="docs-question">{displayQuestion}</div>
      {/if}
      
      <!-- Provider attribution: "via Context7" -->
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
     Layout: library ID, question, via Context7, word count
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
  
  /* Library ID - the selected library from Context7 (e.g., "/sveltejs/svelte") */
  .docs-library-id {
    font-size: 16px;
    font-weight: 600;
    color: var(--color-grey-100);
    line-height: 1.3;
    /* Use monospace font for library IDs */
    font-family: 'SF Mono', 'Monaco', 'Inconsolata', 'Fira Mono', 'Consolas', monospace;
    /* Limit to 2 lines with ellipsis */
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
    text-overflow: ellipsis;
    word-break: break-word;
  }
  
  .get-docs-details.mobile .docs-library-id {
    font-size: 14px;
  }
  
  /* Question/query that was asked */
  .docs-question {
    font-size: 14px;
    color: var(--color-grey-80);
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
  
  .get-docs-details.mobile .docs-question {
    font-size: 12px;
  }
  
  /* Provider attribution: "via Context7" */
  .docs-provider {
    font-size: 14px;
    color: var(--color-grey-70);
    line-height: 1.3;
  }
  
  .get-docs-details.mobile .docs-provider {
    font-size: 12px;
  }
  
  /* Docs info (word count) */
  .docs-info {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-top: 4px;
  }
  
  .get-docs-details.mobile .docs-info {
    margin-top: 2px;
  }
  
  /* Word count */
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
