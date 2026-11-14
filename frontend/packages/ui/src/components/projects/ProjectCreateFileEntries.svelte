<!--
  Project create-menu entries for a new folder and new empty documents, sheets,
  slide decks and code files. Clicking an entry shows an inline name field; the
  parent creates the item in the folder being viewed (a file is opened right
  away). Spec: projects.items.create-documents. Used by both Create menus of
  ProjectsPage.
-->
<script lang="ts">
  import { text } from '@repo/ui';
  import type { ProjectDocumentKind } from '../../services/projectService';

  /** A Project file kind, or a plain folder. */
  type ProjectCreateKind = ProjectDocumentKind | 'folder';

  interface Props {
    /** 'root' stacks the entries under the chat/plan entries, 'folder' spans the folder menu grid. */
    variant: 'root' | 'folder';
    /** Creates and opens the file; resolves false on failure (the parent shows the error). */
    onCreate: (kind: ProjectDocumentKind, name: string) => Promise<boolean>;
    /** Creates a folder inside the folder being viewed; resolves false on failure. */
    onCreateFolder: (name: string) => Promise<boolean>;
  }
  let { variant, onCreate, onCreateFolder }: Props = $props();

  const entries: { kind: ProjectCreateKind; testid: string; label: string; defaultName: string; icon: string }[] = [
    { kind: 'folder', testid: 'project-create-folder', label: 'projects.create_folder', defaultName: 'projects.create_default_folder_name', icon: 'var(--icon-url-files)' },
    { kind: 'document', testid: 'project-create-document', label: 'projects.create_document', defaultName: 'projects.create_default_document_name', icon: 'var(--icon-url-docs)' },
    { kind: 'sheet', testid: 'project-create-sheet', label: 'projects.create_sheet', defaultName: 'projects.create_default_sheet_name', icon: 'var(--icon-url-sheets)' },
    { kind: 'slides', testid: 'project-create-slides', label: 'projects.create_slides', defaultName: 'projects.create_default_slides_name', icon: 'var(--icon-url-slides)' },
    { kind: 'code', testid: 'project-create-code', label: 'projects.create_code_file', defaultName: 'projects.create_default_code_name', icon: 'var(--icon-url-coding)' },
  ];

  let pending = $state<ProjectCreateKind | null>(null);
  let name = $state('');
  let busy = $state(false);

  function choose(entry: (typeof entries)[number]): void {
    pending = entry.kind;
    name = $text(entry.defaultName);
  }

  async function submit(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    if (!pending || busy || !name.trim()) return;
    busy = true;
    try {
      const created = pending === 'folder' ? await onCreateFolder(name.trim()) : await onCreate(pending, name.trim());
      if (created) pending = null;
    } finally {
      busy = false;
    }
  }

  function focusAndSelect(node: HTMLInputElement): void {
    node.focus();
    node.select();
  }
</script>

<div class="file-entries" class:folder={variant === 'folder'} data-testid="project-create-file-entries">
  {#each entries as entry (entry.kind)}
    <button type="button" class:active={pending === entry.kind} data-testid={entry.testid} onclick={() => choose(entry)} disabled={busy}>
      <span class="file-icon" style:--file-entry-icon={entry.icon} aria-hidden="true"></span>
      <span class="file-label">{$text(entry.label)}</span>
    </button>
  {/each}
  {#if pending}
    <form class="name-form" onsubmit={submit}>
      <input type="text" bind:value={name} use:focusAndSelect onkeydown={(event) => { if (event.key === 'Escape' && !busy) { event.stopPropagation(); pending = null; } }} disabled={busy} aria-label={$text('projects.create_name_label')} data-testid="project-create-name-input" />
      <button type="submit" disabled={busy || !name.trim()} aria-busy={busy} data-testid="project-create-name-submit">{$text('projects.create_name_submit')}</button>
    </form>
  {/if}
</div>

<style>
  .file-entries {
    display: grid;
    grid-column: 1 / -1;
    border-top: 1px solid var(--color-grey-25);
  }
  /* Wraps into more rows when the folder panel is narrow (e.g. beside an open file). */
  .file-entries.folder {
    grid-template-columns: repeat(auto-fit, minmax(6.5rem, 1fr));
  }
  /* Thin divider lines on the right and bottom of each tile, so wrapped rows stay separated. */
  .file-entries.folder button {
    flex-direction: column;
    min-width: 0;
    min-height: 6rem;
    box-shadow: inset -1px -1px 0 var(--color-grey-25);
    filter: none;
    text-shadow: none;
    text-align: center;
    overflow-wrap: anywhere;
  }
  .file-entries button {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: var(--spacing-4);
    padding: var(--spacing-6);
    border-radius: 0;
    background: transparent;
    color: var(--color-font-secondary);
    font-weight: 600;
  }
  .file-entries:not(.folder) button { justify-content: flex-start; gap: var(--spacing-6); color: var(--color-font-primary); }
  .file-icon {
    display: inline-block;
    flex: 0 0 auto;
    width: 1.25rem;
    height: 1.25rem;
    background: currentColor;
    -webkit-mask: var(--file-entry-icon) center / contain no-repeat;
    mask: var(--file-entry-icon) center / contain no-repeat;
  }
  .file-entries button + button { border-top: 1px solid var(--color-grey-25); }
  .file-entries.folder button + button { border-top: 0; }
  .file-entries button:hover:not(:disabled), .file-entries button.active { background: var(--color-grey-10); }
  .name-form {
    display: flex;
    grid-column: 1 / -1;
    gap: var(--spacing-4);
    padding: var(--spacing-6);
    border-top: 1px solid var(--color-grey-25);
  }
  .name-form input {
    flex: 1 1 auto;
    min-width: 0;
    padding: var(--spacing-4) var(--spacing-6);
    border: 1px solid var(--color-grey-30);
    border-radius: var(--radius-3);
    background: var(--color-grey-0);
    color: var(--color-font-primary);
  }
  .name-form button { flex: 0 0 auto; border-radius: var(--radius-3); background: var(--color-primary); color: var(--color-grey-0); border-top: 0; }
  .name-form button:disabled { opacity: 0.6; }
</style>
