<!--
  frontend/packages/ui/src/components/embeds/checks/CheckEmbedFullscreen.svelte

  Fullscreen view of a Check: header with aggregate and revision, sources grouped by
  type with role/result/details, deterministic-rule notice, run history (newest
  first, stale runs marked) and Run again / Cancel actions. Props-driven.
  Spec: checks.gui.fullscreen.
-->
<script lang="ts">
  import type { Snippet } from 'svelte';
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import CheckStatusBadge from './CheckStatusBadge.svelte';
  import CheckSourceRow from './CheckSourceRow.svelte';
  import { text } from '../../../i18n/translations';
  import { groupSources } from './checkGrouping';
  import type { CheckView, HumanDecision } from './checkTypes';

  interface Props {
    check: CheckView;
    onClose: () => void;
    onRun: () => void;
    onCancel: () => void;
    onConfirm: (bindingId: string, decision: HumanDecision) => void;
    onSelectRun: (runId: string) => void;
    onOpenTestResult: (embedId: string) => void;
    embedId?: string;
    hasPreviousEmbed?: boolean;
    hasNextEmbed?: boolean;
    onNavigatePrevious?: () => void;
    onNavigateNext?: () => void;
    navigateDirection?: 'previous' | 'next';
    showChatButton?: boolean;
    onShowChat?: () => void;
    /** False for unsaved draft Checks that cannot run yet. */
    showActions?: boolean;
    /** Draft-only actions (e.g. Save to Project) shown under the header row. */
    draftActions?: Snippet;
  }

  let {
    check, onClose, onRun, onCancel, onConfirm, onSelectRun, onOpenTestResult, embedId,
    hasPreviousEmbed = false, hasNextEmbed = false, onNavigatePrevious, onNavigateNext, navigateDirection,
    showChatButton = false, onShowChat, showActions = true, draftActions,
  }: Props = $props();

  let statusLabel = $derived($text(`checks.status.${check.aggregate}`));
  let groups = $derived(groupSources(check));
  let runs = $derived([...check.runs].sort((a, b) => b.started_at.localeCompare(a.started_at)));
  let active = $derived(check.aggregate === 'running' || check.aggregate === 'queued');
  let subtitle = $derived(check.revision_number > 0 ? `${statusLabel} · ${$text('checks.revision')} ${check.revision_number}` : statusLabel);

  function formatTime(iso: string): string {
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
  }
</script>

<UnifiedEmbedFullscreen
  testId="check-fullscreen"
  appId="code"
  skillId="check"
  skillIconName="coding"
  embedHeaderTitle={check.title || $text('checks.title')}
  embedHeaderSubtitle={subtitle}
  showSkillIcon={true}
  {onClose}
  currentEmbedId={embedId}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
  {navigateDirection}
  {showChatButton}
  {onShowChat}
>
  {#snippet content()}
    <div class="cf" data-testid="check-fullscreen-body" data-aggregate={check.aggregate} data-stale={check.stale}>
      <header class="cf-head">
        <CheckStatusBadge status={check.aggregate} label={statusLabel} testId="check-status" />
        {#if check.stale}
          <CheckStatusBadge status="stale" label={check.stale_reason ? `${$text('checks.stale')}: ${check.stale_reason}` : $text('checks.stale')} testId="check-stale" />
        {/if}
        {#if check.revision_number > 0}<span class="cf-rev" data-testid="check-revision">{$text('checks.revision')} {check.revision_number}</span>{/if}
        {#if showActions}<div class="cf-actions">
          {#if active}
            <button type="button" class="cf-btn" data-testid="check-cancel" onclick={onCancel}>{$text('checks.action.cancel')}</button>
          {:else}
            <button type="button" class="cf-btn" data-testid="check-run" onclick={onRun}>{$text('checks.action.run')}</button>
          {/if}
        </div>{/if}
      </header>
      {#if draftActions}{@render draftActions()}{/if}
      {#if check.description}<p class="cf-desc" data-testid="check-description">{check.description}</p>{/if}
      {#if check.covered_claims.length > 0}
        <section data-testid="check-claims">
          <h3>{$text('checks.claims')}</h3>
          <ul>{#each check.covered_claims as claim (claim)}<li>{claim}</li>{/each}</ul>
        </section>
      {/if}
      {#if check.requires_deterministic}
        <p class="cf-rule" role="note" data-testid="check-rule-notice">{$text('checks.rule.requires_deterministic')}</p>
      {/if}
      <section data-testid="check-sources">
        <h3>{$text('checks.sources')}</h3>
        {#each groups as group (group.id)}
          <div class="cf-group" data-testid="check-group-{group.id}">
            <h4>{$text(`checks.group.${group.id}`)}</h4>
            <ul class="cf-list">
              {#each group.sources as source (source.binding_id)}
                <CheckSourceRow {source} {onConfirm} {onOpenTestResult} />
              {/each}
            </ul>
          </div>
        {/each}
      </section>
      <section data-testid="check-history">
        <h3>{$text('checks.history.title')}</h3>
        {#if runs.length === 0}
          <p class="cf-muted">{$text('checks.no_run')}</p>
        {:else}
          <ul class="cf-list">
            {#each runs as run (run.run_id)}
              <li>
                <button type="button" class="cf-run" data-testid="check-run-{run.run_id}" data-stale={run.stale ?? false} onclick={() => onSelectRun(run.run_id)}>
                  <CheckStatusBadge status={run.status} label={$text(`checks.status.${run.status}`)} testId="check-run-status" />
                  <span>{[`${$text('checks.revision')} ${run.revision_number}`, run.subject_label, formatTime(run.started_at)].filter(Boolean).join(' · ')}</span>
                  {#if run.stale}<span class="cf-stale">{$text('checks.history.stale')}</span>{/if}
                </button>
              </li>
            {/each}
          </ul>
        {/if}
      </section>
    </div>
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  .cf { display: flex; flex-direction: column; gap: var(--spacing-8); padding: var(--spacing-8); max-width: 900px; margin: 0 auto; }
  .cf-head { display: flex; flex-wrap: wrap; align-items: center; gap: var(--spacing-4); }
  .cf-actions { margin-inline-start: auto; }
  .cf-rev, .cf-muted, .cf-desc { color: var(--color-font-secondary); font-size: var(--font-size-small); margin: 0; }
  .cf-rule { margin: 0; padding: var(--spacing-6); border-radius: var(--radius-5); background: var(--color-grey-10); color: var(--color-font-primary); font-size: var(--font-size-small); }
  .cf h3, .cf h4 { margin: 0 0 var(--spacing-3); color: var(--color-font-primary); }
  .cf-group { margin-bottom: var(--spacing-6); }
  .cf-list { margin: 0; padding: 0; list-style: none; display: flex; flex-direction: column; gap: var(--spacing-4); }
  .cf-btn, .cf-run { padding: var(--spacing-3) var(--spacing-6); border-radius: var(--radius-5); border: 1px solid var(--color-grey-30); background: transparent; color: var(--color-font-primary); cursor: pointer; }
  .cf-run { display: flex; flex-wrap: wrap; gap: var(--spacing-4); align-items: center; width: 100%; text-align: start; }
  .cf-run[data-stale='true'] { border-style: dashed; opacity: 0.8; }
  .cf-stale { font-size: var(--font-size-small); color: var(--color-font-secondary); font-style: italic; }
</style>
