<!--
  frontend/packages/ui/src/components/embeds/math/MathCalculateEmbedPreview.svelte

  Preview card for Math / Calculate skill embeds.
  Uses UnifiedEmbedPreview as base; provides skill-specific content via the `details` snippet.

  States:
  - processing: Shows expression while calculation is running (stop button shown by UnifiedEmbedPreview)
  - finished:   Shows result value prominently
  - error:      Shows error indicator
  - cancelled:  Dimmed card (handled by UnifiedEmbedPreview automatically)

  Real-time updates are handled by UnifiedEmbedPreview's embedUpdated listener.
  This component implements onEmbedDataUpdated to sync local state when notified.
-->

<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { text } from '@repo/ui';
  import { chatSyncService } from '../../../services/chatSyncService';

  /**
   * Result shape from the backend TOON content for math/calculate.
   */
  interface CalculateResult {
    expression?: string;
    result?: string;
    result_type?: string;
    mode?: string;
  }

  interface Props {
    /** Unique embed ID */
    id: string;
    /** Expression that was evaluated */
    query?: string;
    /** Processing status */
    status?: 'processing' | 'finished' | 'error' | 'cancelled';
    /** Calculation results */
    results?: CalculateResult[];
    /** Task ID for full-response cancellation (fallback) */
    taskId?: string;
    /** Skill task ID for single-skill cancellation (preferred) */
    skillTaskId?: string;
    /** Whether to use mobile layout */
    isMobile?: boolean;
    /** Click handler that opens the fullscreen */
    onFullscreen: () => void;
  }

  let {
    id,
    query: queryProp,
    status: statusProp,
    results: resultsProp,
    taskId: taskIdProp,
    skillTaskId: skillTaskIdProp,
    isMobile = false,
    onFullscreen
  }: Props = $props();

  // ── Local state ─────────────────────────────────────────────────────────────
  let localQuery        = $state('');
  let localStatus       = $state<'processing' | 'finished' | 'error' | 'cancelled'>('processing');
  let localResults      = $state<CalculateResult[]>([]);
  let localTaskId       = $state<string | undefined>(undefined);
  let localSkillTaskId  = $state<string | undefined>(undefined);

  $effect(() => {
    localQuery       = queryProp || '';
    localStatus      = statusProp || 'processing';
    localResults     = resultsProp || [];
    localTaskId      = taskIdProp;
    localSkillTaskId = skillTaskIdProp;
  });

  let query       = $derived(localQuery);
  let status      = $derived(localStatus);
  let results     = $derived(localResults);
  let taskId      = $derived(localTaskId);
  let skillTaskId = $derived(localSkillTaskId);

  // ── Derived display ──────────────────────────────────────────────────────────
  // Primary result to show in the card (first result value)
  let primaryResult = $derived(results[0]?.result ?? '');
  let skillName = $derived($text('embeds.math.calculate'));

  // ── Embed data update callback ───────────────────────────────────────────────
  function handleEmbedDataUpdated(data: { status: string; decodedContent: Record<string, unknown> }) {
    if (data.status === 'processing' || data.status === 'finished' || data.status === 'error' || data.status === 'cancelled') {
      localStatus = data.status;
    }
    const c = data.decodedContent;
    if (!c) return;
    if (typeof c.query === 'string') localQuery = c.query;
    if (Array.isArray(c.results)) localResults = c.results as CalculateResult[];
    if (typeof c.skill_task_id === 'string') localSkillTaskId = c.skill_task_id;
  }

  // ── Stop / cancel ────────────────────────────────────────────────────────────
  async function handleStop() {
    if (status !== 'processing') return;
    if (skillTaskId) {
      await chatSyncService.sendCancelSkill(skillTaskId, id).catch(err =>
        console.error('[MathCalculateEmbedPreview] Failed to cancel skill:', err)
      );
    } else if (taskId) {
      await chatSyncService.sendCancelAiTask(taskId).catch(err =>
        console.error('[MathCalculateEmbedPreview] Failed to cancel task:', err)
      );
    }
  }
</script>

<UnifiedEmbedPreview
  {id}
  appId="math"
  skillId="calculate"
  skillIconName="math"
  {status}
  {skillName}
  {taskId}
  {isMobile}
  {onFullscreen}
  onStop={handleStop}
  onEmbedDataUpdated={handleEmbedDataUpdated}
>
  {#snippet details({ isMobile: isMobileLayout })}
    <div class="math-calculate-details" class:mobile={isMobileLayout}>
      <!-- Expression shown in processing and finished states -->
      {#if query}
        <div class="expression-text">{query}</div>
      {/if}

      {#if status === 'error'}
        <div class="error-indicator">{$text('chat.an_error_occured')}</div>
      {:else if status === 'finished' && primaryResult}
        <!-- Show computed result prominently -->
        <div class="result-value">{primaryResult}</div>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  /* ── Details layout ─────────────────────────────────────────────────────── */

  .math-calculate-details {
    display: flex;
    flex-direction: column;
    gap: 6px;
    height: 100%;
    justify-content: center;
  }

  .math-calculate-details.mobile {
    justify-content: flex-start;
  }

  /* ── Expression ─────────────────────────────────────────────────────────── */

  .expression-text {
    font-size: 14px;
    font-weight: 400;
    color: var(--color-grey-70);
    line-height: 1.3;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
    text-overflow: ellipsis;
    word-break: break-all;
    font-family: 'Courier New', Courier, monospace;
  }

  /* ── Result ─────────────────────────────────────────────────────────────── */

  .result-value {
    font-size: 22px;
    font-weight: 700;
    color: var(--color-grey-100);
    line-height: 1.2;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
    text-overflow: ellipsis;
    word-break: break-all;
    font-family: 'Courier New', Courier, monospace;
  }

  .math-calculate-details.mobile .result-value {
    font-size: 18px;
  }

  /* ── Error ───────────────────────────────────────────────────────────────── */

  .error-indicator {
    font-size: 13px;
    color: var(--color-error);
    margin-top: 4px;
  }

  /* ── Skill icon ──────────────────────────────────────────────────────────── */

  :global(.unified-embed-preview .skill-icon[data-skill-icon="math"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/math.svg');
    mask-image: url('@openmates/ui/static/icons/math.svg');
  }

  :global(.unified-embed-preview.mobile .skill-icon[data-skill-icon="math"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/math.svg');
    mask-image: url('@openmates/ui/static/icons/math.svg');
  }
</style>
