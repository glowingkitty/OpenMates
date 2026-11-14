<!--
  Chat embed card for a Specification: title, kind, status, revision and proof summary.
  Props-driven and lightweight; the fullscreen view loads the readable document.
  Used in chats and in the Project Specifications section.
  Contract: specifications/features/specifications/specification.yml.
-->
<script lang="ts">
  import { text } from '../../../i18n/translations';
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import type { SpecificationListItem } from './SpecificationRevision';

  interface Props {
    id: string;
    item: SpecificationListItem;
    isMobile?: boolean;
    onFullscreen: () => void;
  }
  let { id, item, isMobile = false, onFullscreen }: Props = $props();

  const statusKey = $derived(
    item.changesSinceApproval && item.status === 'approved' ? 'status.changes_since_approval' : `status.${item.status}`
  );
  const updated = $derived(new Date(item.updatedAt).toLocaleDateString(undefined, { dateStyle: 'medium' }));
</script>

<UnifiedEmbedPreview
  {id} appId="design" skillId="specification" skillIconName="design" status="finished"
  skillName={item.title} {isMobile} {onFullscreen} onStop={() => {}}
  showStatus={false} showSkillIcon={false}
>
  {#snippet details()}
    <article class="spec-card" data-testid="specification-embed-card">
      <div class="top">
        <span class="kind">{item.kind}</span>
        <span class="badge" data-testid="specification-status" data-status={item.changesSinceApproval && item.status === 'approved' ? 'changes' : item.status}>
          {$text(`specifications.${statusKey}`)}
        </span>
      </div>
      <h3>{item.title}</h3>
      <div class="meta">
        {#if item.revisionNumber > 0}<span data-testid="specification-revision">{$text('specifications.preview.revision', { values: { number: item.revisionNumber } })}</span>{/if}
        <span>{$text('specifications.preview.updated', { values: { time: updated } })}</span>
        <span>{$text('specifications.preview.requirements', { values: { count: item.requirementCount } })}</span>
      </div>
      <p class="proof" data-testid="specification-proof-summary">
        {$text('specifications.preview.proof', { values: { passed: item.proof.passed, open: item.proof.open, stale: item.proof.stale } })}
      </p>
    </article>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .spec-card { display: flex; flex-direction: column; gap: var(--spacing-3); width: 100%; height: 100%; padding: var(--spacing-6); min-width: 0; }
  .top { display: flex; align-items: center; justify-content: space-between; gap: var(--spacing-4); }
  .kind { color: var(--color-font-secondary); font-size: var(--font-size-xs); font-weight: 600; }
  .badge { border-radius: var(--radius-full); padding: 2px 9px; font-size: var(--font-size-xxs); font-weight: 650; background: var(--color-grey-20); color: var(--color-font-primary); white-space: nowrap; }
  .badge[data-status='approved'] { background: var(--color-chat-rainbow-green); color: var(--color-font-button); }
  .badge[data-status='changes'] { background: var(--color-warning); color: var(--color-font-button); }
  .badge[data-status='superseded'] { background: var(--color-grey-30); color: var(--color-font-secondary); }
  h3 { margin: 0; color: var(--color-font-primary); font-size: var(--font-size-sm); font-weight: 700; line-height: 1.25; overflow: hidden; text-overflow: ellipsis; }
  .meta { display: flex; flex-wrap: wrap; gap: 4px 10px; color: var(--color-font-secondary); font-size: var(--font-size-xxs); }
  .proof { margin: 0; color: var(--color-font-secondary); font-size: var(--font-size-xxs); font-weight: 600; }
</style>
