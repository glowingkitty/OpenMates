<!--
  frontend/packages/ui/src/components/embeds/checks/CheckEmbedPreview.svelte

  Preview card for a Check embed: title, aggregate status (icon + text), per-type
  source chips ("E2E 2/2 · Unit 1/1 · AI ✓ · Human pending"), stale indicator and
  last run time. Props-driven; the whole card opens the fullscreen, where the Check
  is run and human sources are confirmed (no nested buttons inside the card).
  Spec: checks.gui.preview.
-->
<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import CheckStatusBadge from './CheckStatusBadge.svelte';
  import { text } from '../../../i18n/translations';
  import { groupSources, summarizeGroup, type GroupSummary } from './checkGrouping';
  import type { CheckView } from './checkTypes';

  interface Props {
    id: string;
    check: CheckView;
    status?: 'processing' | 'finished' | 'error' | 'cancelled';
    taskId?: string;
    isMobile?: boolean;
    presentationOnly?: boolean;
    onFullscreen: () => void;
  }

  let {
    id, check, status, taskId, isMobile = false, presentationOnly = false, onFullscreen,
  }: Props = $props();

  let embedStatus = $derived(status ?? (check.aggregate === 'running' || check.aggregate === 'queued' ? 'processing' : 'finished'));
  let statusLabel = $derived($text(`checks.status.${check.aggregate}`));
  let summaries = $derived(groupSources(check).map(summarizeGroup));
  let lastRun = $derived(check.runs.length > 0 ? check.runs[0] : undefined);

  function chipText(s: GroupSummary): string {
    const kind = $text(`checks.kind.${s.id}`);
    if (s.id === 'ai') return `${kind} ${s.failed > 0 ? '✗' : s.pending > 0 ? '…' : '✓'}`;
    if (s.id === 'human') {
      return s.failed > 0 ? `${kind} ✗` : s.pending > 0 ? `${kind} ${$text('checks.result.human_pending')}` : `${kind} ✓`;
    }
    return `${kind} ${s.passed}/${s.total}`;
  }

  function chipState(s: GroupSummary): string {
    return s.failed > 0 ? 'failed' : s.pending > 0 ? 'pending' : 'passed';
  }

  function formatTime(iso: string): string {
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? iso : d.toLocaleString(undefined, { dateStyle: 'short', timeStyle: 'short' });
  }
</script>

<UnifiedEmbedPreview
  resultPreview={true}
  {presentationOnly}
  {id}
  appId="code"
  skillId="check"
  skillIconName="coding"
  status={embedStatus}
  skillName={check.title || $text('checks.title')}
  {taskId}
  {isMobile}
  {onFullscreen}
  customStatusText={statusLabel}
  showSkillIcon={true}
>
  {#snippet details()}
    <div class="ck-preview" data-testid="check-preview" data-aggregate={check.aggregate} data-stale={check.stale}>
      <p class="ck-title" data-testid="check-preview-title">{check.title}</p>
      <div class="ck-row">
        <CheckStatusBadge status={check.aggregate} label={statusLabel} testId="check-preview-status" />
        {#if check.stale}
          <CheckStatusBadge status="stale" label={$text('checks.stale')} testId="check-preview-stale" />
        {/if}
      </div>
      <ul class="ck-chips" data-testid="check-preview-chips">
        {#each summaries as s (s.id)}
          <li class="ck-chip ck-chip-{chipState(s)}" data-testid="check-preview-chip-{s.id}" data-state={chipState(s)}>{chipText(s)}</li>
        {/each}
      </ul>
      <p class="ck-meta" data-testid="check-preview-last-run">
        {#if lastRun}{$text('checks.last_run')}: {formatTime(lastRun.started_at)}{:else}{$text('checks.no_run')}{/if}
      </p>
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  /* 48px side gap keeps text clear of the app corner tile (docs/design-guide/result-embeds.md). */
  .ck-preview { display: flex; flex-direction: column; gap: var(--spacing-2); padding: var(--spacing-4) 48px; width: 100%; box-sizing: border-box; min-width: 0; justify-content: center; }
  .ck-title { margin: 0; font-size: var(--font-size-p); font-weight: 600; color: var(--color-font-primary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .ck-row { display: flex; flex-wrap: wrap; gap: var(--spacing-3); }
  .ck-chips { display: flex; flex-wrap: wrap; gap: var(--spacing-2); margin: 0; padding: 0; list-style: none; }
  .ck-chip { padding: var(--spacing-1) var(--spacing-4); border-radius: var(--radius-5); background: var(--color-grey-10); font-size: var(--font-size-small); color: var(--color-font-secondary); }
  .ck-chip-failed { color: var(--color-error); background: var(--color-error-light); }
  .ck-meta { margin: 0; min-width: 0; font-size: var(--font-size-small); color: var(--color-font-secondary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
</style>
