<!--
  frontend/packages/ui/src/components/projects/ProjectFileChangeEventNotice.svelte

  Chat-history system event for applied Project file changes: one quiet, centred
  line ("Project file changed: path" / "3 Project files changed") with a small
  "View changes" control that expands the per-file diff inside the notice.
-->
<script lang="ts">
  import { text } from '../../i18n/translations';
  import { projectFileApprovals, type ProjectFileApprovalEntry } from '../../stores/projectFileApprovalStore';
  import SystemMessageNotice from '../SystemMessageNotice.svelte';
  import { withLiveDiffs, type ProjectFileChangeRow } from './projectFileChangeEvent';

  // `entries` lets previews seed live diffs; in the app the session store supplies them.
  let { rows, entries = undefined, onOpen = undefined }: {
    rows: ProjectFileChangeRow[]; entries?: ProjectFileApprovalEntry[]; onOpen?: () => void;
  } = $props();
  let expanded = $state(false);
  let changes = $derived(withLiveDiffs(rows, entries ?? $projectFileApprovals));
  let hasLiveDiff = $derived(changes.some((change) => change.diff));
  let label = $derived(changes.length === 1
    ? $text('projects.file_change_event_one', { values: { path: changes[0]?.path ?? '' } })
    : $text('projects.file_change_event_many', { values: { count: changes.length } }));
  // Live: expand the in-memory diff. After a reload no diff exists, so open the file through the Project reference view.
  function review() { if (hasLiveDiff) expanded = !expanded; else onOpen?.(); }
</script>

<div class="project-file-change-event" data-testid="project-file-change-event"
  data-paths={changes.map((change) => change.path).join(',')}>
  <SystemMessageNotice>
    <span class="label">{label}</span>
    <button type="button" class="toggle" aria-expanded={expanded} onclick={review}>
      {$text('projects.file_change_review')}
    </button>
    {#if expanded && hasLiveDiff}
      <div class="files">
        {#each changes as change (change.project_id + change.path)}
          <div class="file">
            <code class="path">{change.path}</code>
            {#if change.diff}<pre data-testid="project-file-change-diff">{change.diff}</pre>{/if}
          </div>
        {/each}
      </div>
    {/if}
  </SystemMessageNotice>
</div>

<style>
  .project-file-change-event { display: flex; justify-content: center; width: 100%; min-width: 0; }
  .label { overflow-wrap: anywhere; }
  .toggle { all: unset; cursor: pointer; margin-inline-start: var(--spacing-4); text-decoration: underline; border-radius: var(--radius-3); }
  .toggle:hover { color: var(--color-grey-80); }
  .toggle:focus-visible { outline: 2px solid var(--color-primary-start); outline-offset: 2px; }
  .files { margin-top: var(--spacing-4); text-align: start; }
  .path { display: block; background: transparent; padding: 0; overflow-wrap: anywhere; }
  pre { max-height: 16rem; overflow: auto; margin: var(--spacing-2) 0 var(--spacing-4); padding: var(--spacing-4); background: var(--color-grey-0); border-radius: var(--radius-4); font-size: var(--font-size-xs); white-space: pre; tab-size: 2; }
</style>
