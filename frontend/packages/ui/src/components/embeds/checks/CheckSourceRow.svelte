<!--
  frontend/packages/ui/src/components/embeds/checks/CheckSourceRow.svelte

  One source of a Check in the fullscreen: role, result, and type-specific details
  (AI question/verdict/score/feedback, human instruction with Confirm/Reject only
  while pending, optional link to a test result embed). The reference and the
  human instruction are shown only when they add text beyond the source title.
-->
<script lang="ts">
  import CheckStatusBadge from './CheckStatusBadge.svelte';
  import { text } from '../../../i18n/translations';
  import type { HumanDecision, SourceView } from './checkTypes';

  interface Props {
    source: SourceView;
    onConfirm: (bindingId: string, decision: HumanDecision) => void;
    onOpenTestResult: (embedId: string) => void;
  }
  let { source, onConfirm, onOpenTestResult }: Props = $props();

  let result = $derived(source.latest_result);
  let resultStatus = $derived(result?.status ?? 'never_run');
  let resultLabel = $derived(
    result ? $text(`checks.status.${result.status}`) : $text('checks.result.pending'),
  );
  let humanPending = $derived(
    source.kind === 'human_confirmation' && result?.status === 'waiting_for_confirmation' && !result.human?.decision,
  );
</script>

<li class="sr" data-testid="check-source-{source.binding_id}" data-kind={source.kind} data-role={source.role} data-status={resultStatus}>
  <div class="sr-head">
    <span class="sr-title" data-testid="check-source-title">{source.title}</span>
    <span class="sr-role" data-testid="check-source-role">{$text(`checks.role.${source.role}`)}</span>
    <CheckStatusBadge status={resultStatus} label={resultLabel} testId="check-source-status" />
  </div>
  {#if source.ref_label && source.ref_label !== source.title}<p class="sr-ref">{source.ref_label}</p>{/if}
  {#if result}
    <p class="sr-summary" data-testid="check-source-summary">{result.summary}</p>
    {#if result.test_result_embed_id}
      {@const embedId = result.test_result_embed_id}
      <button type="button" class="sr-btn" data-testid="check-source-open-test-result" onclick={() => onOpenTestResult(embedId)}>
        {$text('checks.open_test_result')}
      </button>
    {/if}
    {#if result.ai}
      <dl class="sr-details" data-testid="check-source-ai">
        <dt>{$text('checks.ai.question')}</dt><dd data-testid="check-ai-question">{result.ai.question}</dd>
        <dt>{$text('checks.ai.verdict')}</dt><dd data-testid="check-ai-verdict">{$text(`checks.ai.verdict_${result.ai.verdict}`)}</dd>
        <dt>{$text('checks.ai.score')}</dt>
        <dd data-testid="check-ai-score">{result.ai.score} / {$text('checks.ai.threshold')} {result.ai.threshold}</dd>
        <dt>{$text('checks.ai.feedback')}</dt><dd data-testid="check-ai-feedback">{result.ai.feedback}</dd>
      </dl>
    {/if}
    {#if result.human}
      <div class="sr-details" data-testid="check-source-human">
        {#if result.human.instruction !== source.title}
          <p class="sr-instruction" data-testid="check-human-instruction">{result.human.instruction}</p>
        {/if}
        {#if result.human.decision}
          <p class="sr-actor" data-testid="check-human-actor" aria-live="polite">
            {$text(result.human.decision === 'confirmed' ? 'checks.human.confirmed_by' : 'checks.human.rejected_by')}
            {result.human.confirmer_label ?? ''}{result.human.confirmed_at ? ` · ${new Date(result.human.confirmed_at).toLocaleString()}` : ''}
          </p>
        {/if}
      </div>
    {/if}
  {/if}
  {#if humanPending}
    <div class="sr-actions">
      <button type="button" class="sr-btn" data-testid="check-human-confirm" onclick={() => onConfirm(source.binding_id, 'confirmed')}>{$text('checks.human.confirm')}</button>
      <button type="button" class="sr-btn" data-testid="check-human-reject" onclick={() => onConfirm(source.binding_id, 'rejected')}>{$text('checks.human.reject')}</button>
    </div>
  {/if}
</li>

<style>
  .sr { list-style: none; padding: var(--spacing-6); border: 1px solid var(--color-grey-20); border-radius: var(--radius-5); display: flex; flex-direction: column; gap: var(--spacing-3); }
  .sr-head { display: flex; flex-wrap: wrap; align-items: center; gap: var(--spacing-4); }
  .sr-title { font-weight: 600; color: var(--color-font-primary); flex: 1 1 auto; min-width: 0; }
  .sr-role { font-size: var(--font-size-small); color: var(--color-font-secondary); }
  .sr[data-role='supporting'] { border-style: dashed; }
  .sr-ref, .sr-summary, .sr-instruction, .sr-actor { margin: 0; font-size: var(--font-size-small); color: var(--color-font-secondary); }
  .sr-details { margin: 0; display: grid; grid-template-columns: max-content 1fr; gap: var(--spacing-2) var(--spacing-6); font-size: var(--font-size-small); }
  .sr-details dt { color: var(--color-font-secondary); }
  .sr-details dd { margin: 0; color: var(--color-font-primary); }
  .sr-actions { display: flex; gap: var(--spacing-4); }
  .sr-btn { align-self: flex-start; padding: var(--spacing-2) var(--spacing-6); border-radius: var(--radius-5); border: 1px solid var(--color-grey-30); background: transparent; color: var(--color-font-primary); cursor: pointer; }
</style>
