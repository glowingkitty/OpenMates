<!--
  Status strip, revision list and approval action for the Specification fullscreen view.
  Approval always applies to the exact revision shown, with an explicit confirmation step.
  Older revisions are read-only and cannot be approved.
  Props-driven; the parent loads the selected revision and records the approval.
-->
<script lang="ts">
  import { text } from '../../../i18n/translations';
  import type { SpecificationApproval, SpecificationRevisionSummary } from './SpecificationRevision';

  interface Props {
    revisions: SpecificationRevisionSummary[];
    currentRevisionId: string;
    viewedRevisionId: string;
    approval: SpecificationApproval;
    onApprove?: (revisionId: string, contentHash: string) => void;
    onSelectRevision?: (revisionId: string) => void;
  }
  let { revisions, currentRevisionId, viewedRevisionId, approval, onApprove, onSelectRevision }: Props = $props();

  let confirming = $state(false);
  const viewed = $derived(revisions.find(r => r.revision_id === viewedRevisionId));
  const approvedRevision = $derived(revisions.find(r => r.revision_id === approval.approved_revision_id));
  const isCurrent = $derived(viewedRevisionId === currentRevisionId);
  const isApproved = $derived(approval.state !== 'draft' && approval.approved_revision_id === viewedRevisionId);
  const canApprove = $derived(Boolean(viewed) && isCurrent && !isApproved);
  const sorted = $derived([...revisions].sort((a, b) => b.revision_number - a.revision_number));

  function when(iso: string | null) {
    return iso ? new Date(iso).toLocaleDateString(undefined, { dateStyle: 'medium' }) : '';
  }
  function confirm() {
    if (!viewed || !canApprove) return;
    confirming = false;
    onApprove?.(viewed.revision_id, viewed.content_hash);
  }
  // Leaving the viewed revision cancels a pending confirmation.
  let lastViewedRevisionId: string | undefined;
  $effect(() => {
    if (viewedRevisionId === lastViewedRevisionId) return;
    lastViewedRevisionId = viewedRevisionId;
    confirming = false;
  });
</script>

<div class="revision-panel">
  <div class="status-strip" data-testid="specification-status-strip" data-approval-state={approval.state}>
    <span class="badge" data-status={approval.state}>
      {$text(approval.state === 'stale' ? 'specifications.status.changes_since_approval' : approval.state === 'approved' ? 'specifications.status.approved' : 'specifications.status.draft')}
    </span>
    {#if viewed}<strong data-testid="specification-viewed-revision">{$text('specifications.revisions.revision', { values: { number: viewed.revision_number } })}</strong>{/if}
    {#if approval.state === 'approved' && approval.approved_at}<span>{$text('specifications.approval.approved_at', { values: { time: when(approval.approved_at) } })}</span>{/if}
    {#if approval.state === 'stale' && approvedRevision}<span>{$text('specifications.approval.stale', { values: { number: approvedRevision.revision_number } })}</span>{/if}
  </div>

  {#if !isCurrent}<p class="note" data-testid="specification-read-only">{$text('specifications.revisions.read_only')}</p>{/if}

  <section class="revisions" aria-labelledby="spec-revisions-heading">
    <h2 id="spec-revisions-heading">{$text('specifications.revisions.heading')}</h2>
    {#if sorted.length}
      <ul data-testid="specification-revisions">
        {#each sorted as revision (revision.revision_id)}
          <li data-testid={`specification-revision-${revision.revision_id}`} class:viewed={revision.revision_id === viewedRevisionId}>
            <button type="button" aria-current={revision.revision_id === viewedRevisionId} aria-label={$text('specifications.revisions.select', { values: { number: revision.revision_number } })}
              onclick={() => onSelectRevision?.(revision.revision_id)}>
              <span class="row">
                <strong>{$text('specifications.revisions.revision', { values: { number: revision.revision_number } })}</strong>
                {#if revision.revision_id === currentRevisionId}<span class="marker" data-marker="current">{$text('specifications.revisions.current')}</span>{/if}
                {#if revision.revision_id === approval.approved_revision_id}<span class="marker approved" data-marker="approved">{$text('specifications.revisions.approved')}</span>{/if}
                {#if revision.revision_id === viewedRevisionId}<span class="marker" data-marker="viewing">{$text('specifications.revisions.viewing')}</span>{/if}
              </span>
              <span class="detail">{[revision.author_label, when(revision.created_at)].filter(Boolean).join(' · ')}</span>
              <span class="detail">{revision.summary}</span>
            </button>
          </li>
        {/each}
      </ul>
    {:else}<p class="note">{$text('specifications.revisions.empty')}</p>{/if}
  </section>

  <div class="approval">
    {#if confirming && viewed}
      <div class="confirm" role="alertdialog" aria-label={$text('specifications.approval.confirm_title', { values: { number: viewed.revision_number } })} data-testid="specification-approve-confirm">
        <strong>{$text('specifications.approval.confirm_title', { values: { number: viewed.revision_number } })}</strong>
        <p>{$text('specifications.approval.confirm_body')}</p>
        <div class="actions">
          <button type="button" class="primary" data-testid="specification-approve-confirm-button" onclick={confirm}>{$text('specifications.approval.confirm')}</button>
          <button type="button" data-testid="specification-approve-cancel" onclick={() => { confirming = false; }}>{$text('specifications.approval.cancel')}</button>
        </div>
      </div>
    {:else}
      <button type="button" class="primary" data-testid="specification-approve" disabled={!canApprove} onclick={() => { confirming = true; }}>{$text('specifications.approval.approve')}</button>
      {#if isApproved}<p class="note">{$text('specifications.approval.already_approved')}</p>
      {:else if !isCurrent}<p class="note">{$text('specifications.approval.only_current')}</p>{/if}
    {/if}
  </div>
</div>

<style>
  .revision-panel { display: flex; flex-direction: column; gap: var(--spacing-6); margin: 20px 0 8px; }
  .status-strip { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 14px; padding: 12px 16px; border-radius: 14px; background: var(--color-grey-0); font-size: var(--font-size-small); }
  .badge { border-radius: var(--radius-full); padding: 2px 10px; font-size: var(--font-size-xxs); font-weight: 650; background: var(--color-grey-20); }
  .badge[data-status='approved'] { background: var(--color-chat-rainbow-green); color: var(--color-font-button); }
  .badge[data-status='stale'] { background: var(--color-warning); color: var(--color-font-button); }
  .note { margin: 0; color: var(--color-font-secondary); font-size: var(--font-size-xs); }
  h2 { font-size: var(--font-size-lg); margin: 0 0 10px; }
  ul { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 8px; }
  li button { display: flex; flex-direction: column; align-items: stretch; justify-content: flex-start; gap: 3px; width: 100%; height: auto; min-height: 0; margin: 0; box-shadow: none; text-align: left; padding: 10px 14px; border: 1px solid var(--color-grey-25); border-radius: 12px; background: var(--color-grey-0); color: var(--color-font-primary); cursor: pointer; }
  li.viewed button { border-color: var(--color-primary-start); }
  li button:focus-visible { outline: 3px solid var(--color-primary-start); outline-offset: 2px; }
  .row { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
  .marker { border-radius: var(--radius-full); padding: 1px 8px; background: var(--color-grey-20); font-size: var(--font-size-tiny); font-weight: 650; }
  .marker.approved { background: var(--color-chat-rainbow-green); color: var(--color-font-button); }
  .detail { color: var(--color-font-secondary); font-size: var(--font-size-xxs); }
  .approval { display: flex; flex-direction: column; align-items: flex-start; gap: 8px; }
  .confirm { padding: 14px 16px; border-radius: 14px; background: var(--color-grey-0); border: 1px solid var(--color-grey-25); width: 100%; box-sizing: border-box; }
  .confirm p { margin: 6px 0 12px; font-size: var(--font-size-xs); color: var(--color-font-secondary); }
  .actions { display: flex; gap: 10px; flex-wrap: wrap; }
  .approval button, .actions button { height: auto; margin: 0; padding: 8px 16px; border-radius: var(--radius-full); border: 1px solid var(--color-grey-30); background: var(--color-grey-0); color: var(--color-font-primary); cursor: pointer; font-weight: 600; }
  button.primary { background: var(--color-primary-start); border-color: var(--color-primary-start); color: var(--color-font-button); }
  button:disabled { opacity: 0.5; cursor: not-allowed; }
</style>
