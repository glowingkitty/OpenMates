<script lang="ts">
  import { text } from '../../i18n/translations';
  import type { ProjectFileApprovalEntry } from '../../stores/projectFileApprovalStore';

  interface Props {
    entry: ProjectFileApprovalEntry;
    onDecision: (id: string, accepted: boolean) => void;
  }
  let { entry, onDecision }: Props = $props();
  let path = $derived(entry.kind === 'write' ? entry.request.mutation.path : entry.request.path);
</script>

<section class="file-card" data-testid="project-file-approval-card" data-status={entry.status}>
  <strong>
    {#if entry.status === 'applied'}
      {$text('projects.file_change_applied')}
    {:else if entry.kind === 'read'}
      {$text('projects.ignored_read_approval_title')}
    {:else}
      {$text('projects.file_write_approval_title')}
    {/if}
  </strong>
  <code class="path">{path}</code>
  {#if entry.kind === 'read'}
    <p>{$text('projects.ignored_read_approval_description')}</p>
  {:else}
    <details open={entry.status === 'pending'}>
      <summary>{$text('projects.file_change_review')}</summary>
      <pre data-testid="project-file-change-diff">{entry.request.mutation.patch ?? entry.request.mutation.content ?? ''}</pre>
    </details>
  {/if}
  {#if entry.status === 'pending'}
    <div class="actions">
      <button class="approve" data-testid="project-file-approve" onclick={() => onDecision(entry.id, true)}>
        {$text(entry.kind === 'read' ? 'projects.file_read_approve' : 'projects.file_write_approve')}
      </button>
      <button data-testid="project-file-reject" onclick={() => onDecision(entry.id, false)}>
        {$text('projects.file_approval_reject')}
      </button>
    </div>
  {/if}
</section>

<style>
  .file-card { width: 100%; min-width: 0; box-sizing: border-box; padding: var(--spacing-6); border: 1px solid var(--color-grey-25); border-radius: var(--radius-7); background: var(--color-grey-10); color: var(--color-font-primary); }
  strong { display: block; font-size: var(--font-size-p); }
  code { background: transparent; color: var(--color-font-primary); padding: 0; }
  .path { display: block; margin: var(--spacing-3) 0; overflow-wrap: anywhere; }
  p, summary { font-size: var(--font-size-small); color: var(--color-font-secondary); }
  summary { cursor: pointer; }
  pre { max-height: 20rem; overflow: auto; padding: var(--spacing-4); background: var(--color-grey-0); border-radius: var(--radius-4); font-size: var(--font-size-small); white-space: pre; tab-size: 2; }
  .actions { display: flex; flex-wrap: wrap; gap: var(--spacing-3); margin-top: var(--spacing-5); }
  button { min-height: 2.75rem; border: 1px solid var(--color-grey-30); border-radius: var(--radius-4); padding: var(--spacing-3) var(--spacing-5); background: var(--color-grey-0); color: var(--color-font-primary); cursor: pointer; }
  button.approve { background: var(--color-button-primary); color: var(--color-font-button); border-color: var(--color-button-primary); }
  button.approve:hover { background: var(--color-button-primary-hover); }
  button:focus-visible, summary:focus-visible { outline: 2px solid var(--color-button-primary); outline-offset: 2px; }
  button.approve:focus-visible { outline-color: var(--color-primary); }
</style>
