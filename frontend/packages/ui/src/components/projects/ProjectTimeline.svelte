<!--
  Project timeline: newest-first list of commits, file versions and file operations.
  Pure presentation; the parent supplies entries and callbacks.
  Native Swift counterparts: apple/OpenMates/Sources/Features/Projects/ProjectTimelineView.swift
-->
<script lang="ts">
  import { text } from '@repo/ui';
  import type { ProjectTimelineEntry } from './ProjectTimeline.types';

  interface Props {
    entries: ProjectTimelineEntry[];
    loading: boolean;
    error: string | null;
    hasMore: boolean;
    onLoadMore: () => void;
    onRestoreCommit: (commitId: string) => Promise<void>;
    onOpenFile: (path: string) => void;
  }

  let { entries, loading, error, hasMore, onLoadMore, onRestoreCommit, onOpenFile }: Props = $props();

  const ACTIONS = ['created', 'updated', 'edited', 'restored', 'renamed', 'deleted', 'adopted'];
  const ICONS = { commit: 'project', file_version: 'docs', file_operation: 'edit' } as const;

  let expandedId = $state<string | null>(null);
  let confirmId = $state<string | null>(null);
  let busyId = $state<string | null>(null);
  let status = $state<{ id: string; ok: boolean; code?: string } | null>(null);

  function relativeTime(seconds: number): string {
    const diff = seconds - Math.floor(Date.now() / 1000);
    const abs = Math.abs(diff);
    const fmt = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' });
    if (abs < 60) return fmt.format(diff, 'second');
    if (abs < 3600) return fmt.format(Math.round(diff / 60), 'minute');
    if (abs < 86400) return fmt.format(Math.round(diff / 3600), 'hour');
    return fmt.format(Math.round(diff / 86400), 'day');
  }

  function toggle(id: string): void {
    expandedId = expandedId === id ? null : id;
    confirmId = null;
  }

  async function restore(commitId: string): Promise<void> {
    confirmId = null;
    busyId = commitId;
    status = null;
    try {
      await onRestoreCommit(commitId);
      status = { id: commitId, ok: true };
    } catch (caught) {
      // Keep the core's refusal code (e.g. embed_missing) so the failure says why.
      const code = (caught as { code?: unknown } | null)?.code;
      status = { id: commitId, ok: false, code: typeof code === 'string' ? code : undefined };
    } finally {
      busyId = null;
    }
  }
</script>

<div class="pt" data-testid="project-timeline">
  {#if error}
    <p class="pt-error" role="alert" data-testid="project-timeline-error">{$text('projects.timeline_error')} {error}</p>
  {/if}
  {#if !error && !loading && entries.length === 0}
    <p class="pt-empty" data-testid="project-timeline-empty">{$text('projects.timeline_empty')}</p>
  {/if}
  <ul class="pt-list">
    {#each entries as entry (entry.id)}
      {@const commit = entry.commit}
      {@const open = expandedId === entry.id}
      <li class="pt-entry" data-testid={`project-timeline-entry-${entry.id}`} data-kind={entry.kind}>
        {#snippet rowBody()}
          <span class="pt-icon" style={`--pt-icon: var(--icon-url-${ICONS[entry.kind]})`} aria-hidden="true"></span>
          <span class="pt-main">
            <span class="pt-line">
              <span class="pt-author">{$text(`projects.timeline_author_${entry.author}`)}</span>
              {#if entry.action && ACTIONS.includes(entry.action)}
                <span class="pt-action">{$text(`projects.timeline_action_${entry.action}`)}</span>
              {/if}
              <span class="pt-time">{relativeTime(entry.createdAt)}</span>
            </span>
            {#if commit}
              <span class="pt-path pt-message">{commit.message}</span>
              <span class="pt-meta">
                {$text(commit.files.length === 1 ? 'projects.timeline_files_count_singular' : 'projects.timeline_files_count', { values: { count: commit.files.length } })}
                {#if commit.restoredFrom}
                  · {$text('projects.timeline_restored_from', { values: { id: commit.restoredFrom.slice(0, 7) } })}
                {/if}
              </span>
            {:else}
              <span class="pt-path">{entry.path ?? $text('projects.timeline_removed_file')}</span>
              {#if entry.restoredFromVersion !== null}
                <span class="pt-meta">{$text('projects.timeline_restored_from_version', { values: { version: entry.restoredFromVersion } })}</span>
              {/if}
            {/if}
          </span>
          {#if entry.version !== null}<span class="pt-chip">v{entry.version}</span>{/if}
        {/snippet}
        {#if commit}
          <button type="button" class="pt-row" aria-expanded={open} data-testid={`project-timeline-commit-toggle-${entry.id}`} onclick={() => toggle(entry.id)}>
            {@render rowBody()}
          </button>
        {:else}
          <div class="pt-row">{@render rowBody()}</div>
        {/if}

        {#if commit && open}
          <div class="pt-detail">
            <ul class="pt-files" data-testid={`project-timeline-commit-files-${entry.id}`}>
              {#each commit.files as file (file.path)}
                <li>
                  <button type="button" class="pt-file" onclick={() => onOpenFile(file.path)}>
                    <span class="pt-path">{file.path}</span>
                    {#if file.change}<span class="pt-meta">{$text(`projects.timeline_change_${file.change}`)}</span>{/if}
                    <span class="pt-chip">v{file.version}</span>
                  </button>
                </li>
              {/each}
            </ul>
            {#if confirmId === commit.id}
              <p class="pt-prompt">{$text('projects.timeline_restore_prompt')}</p>
              <div class="pt-actions">
                <button type="button" class="pt-btn pt-btn-primary" data-testid="project-timeline-restore-confirm" onclick={() => void restore(commit.id)}>{$text('projects.timeline_restore_confirm')}</button>
                <button type="button" class="pt-btn pt-btn-secondary" data-testid="project-timeline-restore-cancel" onclick={() => (confirmId = null)}>{$text('projects.timeline_restore_cancel')}</button>
              </div>
            {:else}
              <div class="pt-actions">
                <button type="button" class="pt-btn" data-testid={`project-timeline-restore-${entry.id}`} disabled={busyId !== null} onclick={() => (confirmId = commit.id)}>{$text('projects.timeline_restore_button')}</button>
              </div>
            {/if}
            {#if busyId === commit.id}
              <p class="pt-status" role="status" data-testid="project-timeline-restore-status" data-state="busy">{$text('projects.timeline_restore_busy')}</p>
            {:else if status && status.id === commit.id}
              <p class="pt-status" role="status" data-testid="project-timeline-restore-status" data-state={status.ok ? 'done' : 'error'}>
                {status.ok ? $text('projects.timeline_restore_done') : $text('projects.timeline_restore_failed')}{#if !status.ok && status.code}{` (${status.code})`}{/if}
              </p>
            {/if}
          </div>
        {/if}
      </li>
    {/each}
  </ul>
  {#if loading}<p class="pt-meta">{$text('projects.timeline_loading')}</p>{/if}
  {#if hasMore && !loading}
    <button type="button" class="pt-btn pt-more" data-testid="project-timeline-load-more" onclick={onLoadMore}>{$text('projects.timeline_load_more')}</button>
  {/if}
</div>

<style>
  .pt { display: flex; flex-direction: column; gap: var(--spacing-6); width: 100%; }
  .pt-list, .pt-files { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: var(--spacing-3); }
  .pt-entry { background: var(--color-grey-10); border-radius: var(--radius-3); overflow: hidden; }
  .pt-row, .pt-file {
    display: flex; align-items: flex-start; justify-content: flex-start; gap: var(--spacing-6);
    /* border-box: the non-button rows (div) must not overflow by their padding. */
    box-sizing: border-box; width: 100%; height: auto; min-width: 0; margin: 0; text-align: left;
    padding: var(--spacing-5) var(--spacing-6); border: 0; background: transparent;
    color: var(--color-font-primary); font: inherit; filter: none; box-shadow: none;
  }
  button.pt-row { cursor: pointer; }
  button.pt-row:hover, .pt-file:hover { background: var(--color-grey-20); scale: none; }
  button.pt-row:active, .pt-file:active { scale: none; }
  .pt-file { align-items: center; cursor: pointer; padding: var(--spacing-3) var(--spacing-6); }
  .pt-icon { flex: 0 0 auto; width: 20px; height: 20px; margin-top: 2px; background: var(--color-primary); -webkit-mask: var(--pt-icon) center / contain no-repeat; mask: var(--pt-icon) center / contain no-repeat; }
  .pt-main { display: flex; flex-direction: column; gap: var(--spacing-1); min-width: 0; flex: 1; }
  .pt-line { display: flex; flex-wrap: wrap; gap: var(--spacing-3); align-items: baseline; }
  .pt-author { font-weight: 600; }
  .pt-action, .pt-time, .pt-meta { color: var(--color-font-secondary); font-size: var(--font-size-small); }
  .pt-path { overflow-wrap: anywhere; flex: 1; min-width: 0; }
  .pt-chip { flex: 0 0 auto; padding: 0 var(--spacing-3); border-radius: var(--radius-5); background: var(--color-grey-20); font-size: var(--font-size-xs); }
  .pt-detail { padding: 0 var(--spacing-6) var(--spacing-6); display: flex; flex-direction: column; gap: var(--spacing-4); }
  .pt-prompt, .pt-status { margin: 0; }
  .pt-status[data-state='error'], .pt-error { color: var(--color-error); }
  .pt-status[data-state='done'] { color: var(--color-primary); }
  .pt-actions { display: flex; gap: var(--spacing-4); }
  .pt-empty { margin: 0; color: var(--color-font-secondary); text-align: center; padding: var(--spacing-10); }
  .pt-error { margin: 0; }
  .pt-more { align-self: center; }
  /* Cancel is the secondary choice next to Confirm (HighlightCommentPopover .hp-btn-secondary). */
  .pt-btn-secondary { background: var(--color-grey-20); color: var(--color-grey-100); }
  .pt-btn-secondary:hover:not(:disabled) { background: var(--color-grey-30); }
</style>
