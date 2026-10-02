<!--
  ChatProjectNavigator provides the compact chat organization/activity surface.
  Uses shared design tokens and accessible native controls.
  Navigation stays readable within the narrow sidebar.
  Global lifecycle stores remain separate from rendering.
  Colocated fixtures provide isolated component verification.
-->
<script lang="ts">
  import { text } from '@repo/ui';
  import { ChevronLeft, ChevronRight, Folder, MoreHorizontal, Plus, ExternalLink } from '@lucide/svelte';
  import ProcessingWheel from './ProcessingWheel.svelte';
  import { projectBreadcrumbs, locationHasRunningChats, type ChatProjectLocation, type SidebarProject } from '../../utils/chatProjectNavigation';
  let { projects, location = $bindable(null), runningIds, onNavigate = next => location = next, onDropChat, onCreateFolder, onOpenProject }: {
    projects: SidebarProject[];
    location?: ChatProjectLocation | null;
    runningIds: ReadonlySet<string>;
    onNavigate?: (location: ChatProjectLocation | null) => void;
    onDropChat: (chatId: string, location: ChatProjectLocation) => void;
    onCreateFolder: (location: ChatProjectLocation, name: string) => Promise<void>;
    onOpenProject: (id: string) => void;
  } = $props();
  let showAncestors = $state(false);
  let newFolderName = $state('');
  let creatingFolder = $state(false);
  let busy = $state(false);
  let error = $state('');
  const project = $derived(projects.find(project => project.id === location?.projectId));
  const crumbs = $derived(project ? projectBreadcrumbs(project, location?.folderId ?? null) : []);
  const currentHash = $derived(project?.folders.find(folder => folder.id === location?.folderId)?.hash ?? null);
  const folders = $derived(project?.folders.filter(folder => folder.parentHash === currentHash) ?? []);
  function go(next: ChatProjectLocation | null): void { showAncestors = false; creatingFolder = false; onNavigate(next); }
  function goUp(): void {
    if (!project || crumbs.length < 2) go(null);
    else go({ projectId: project.id, folderId: crumbs[crumbs.length - 2].id });
  }
  function drop(event: DragEvent, destination: ChatProjectLocation): void {
    event.preventDefault();
    event.stopPropagation();
    const id = event.dataTransfer?.getData('application/x-openmates-chat');
    if (id) onDropChat(id, destination);
  }
  async function createFolder(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    if (!location || !newFolderName.trim() || busy) return;
    busy = true; error = '';
    try { await onCreateFolder(location, newFolderName.trim()); creatingFolder = false; newFolderName = ''; }
    catch (failure) { console.error('[ChatProjectNavigator] Folder creation failed:', failure); error = $text('chats.projects.error'); }
    finally { busy = false; }
  }
</script>

<section class="project-navigation" data-testid="chat-project-navigation">
  {#if project && location}
    <nav class="breadcrumb" aria-label={$text('chats.projects.path')}>
      <button class="icon-control" type="button" aria-label={$text('chats.projects.up')} onclick={goUp}><ChevronLeft size={16} /></button>
      <button class="crumb" type="button" title={project.name} onclick={() => go({ projectId: project.id, folderId: null })}>{project.name}</button>
      {#if crumbs.length > 2}
        <ChevronRight size={12} />
        <button class="icon-control" type="button" aria-label={$text('chats.projects.ancestors')} aria-expanded={showAncestors} onclick={() => showAncestors = !showAncestors}><MoreHorizontal size={16} /></button>
      {/if}
      {#if crumbs.length > 1}<ChevronRight size={12} /><span class="crumb current" title={crumbs.at(-1)?.name}>{crumbs.at(-1)?.name}</span>{/if}
    </nav>
    {#if showAncestors}
      <div class="ancestor-list" data-testid="chat-project-ancestors">
        {#each crumbs as crumb}
          <button type="button" class="folder-row" aria-current={crumb.id === location.folderId ? 'location' : undefined} onclick={() => go({ projectId: project.id, folderId: crumb.id })}>
            <span class="row-name">{crumb.name}</span>
          </button>
        {/each}
      </div>
    {/if}
    <div class="folder-actions">
      <button type="button" class="action" onclick={() => creatingFolder = !creatingFolder}><Plus size={14} />{$text('chats.projects.new_folder')}</button>
      <button type="button" class="icon-control" aria-label={$text('chats.projects.open')} onclick={() => onOpenProject(project.id)}><ExternalLink size={16} /></button>
    </div>
    {#if creatingFolder}
      <form class="new-folder" onsubmit={createFolder}>
        <input aria-label={$text('chats.projects.folder_name')} bind:value={newFolderName} maxlength={200} disabled={busy} />
        <button class="icon-control" type="submit" aria-label={$text('chats.projects.new_folder')} disabled={busy || !newFolderName.trim()}><Plus size={16} /></button>
      </form>
    {/if}
    {#each folders as folder (folder.id)}
      <button type="button" class="folder-row" data-testid="chat-project-folder" onclick={() => go({ projectId: project.id, folderId: folder.id })}
        ondragover={event => { if (event.dataTransfer?.types.includes('application/x-openmates-chat')) event.preventDefault(); }}
        ondrop={event => drop(event, { projectId: project.id, folderId: folder.id })}>
        {#if locationHasRunningChats(project, folder.id, runningIds)}<ProcessingWheel />{:else}<Folder size={24} />{/if}
        <span class="row-name" title={folder.name}>{folder.name}</span><ChevronRight size={16} />
      </button>
    {/each}
  {:else}
    {#each projects as root (root.id)}
      <button type="button" class="folder-row" data-testid="chat-project-root" onclick={() => go({ projectId: root.id, folderId: null })}
        ondragover={event => { if (event.dataTransfer?.types.includes('application/x-openmates-chat')) event.preventDefault(); }}
        ondrop={event => drop(event, { projectId: root.id, folderId: null })}>
        {#if locationHasRunningChats(root, null, runningIds)}<ProcessingWheel />{:else}<Folder size={24} />{/if}
        <span class="row-name" title={root.name}>{root.name}</span><ChevronRight size={16} />
      </button>
    {/each}
  {/if}
  {#if error}<p class="error" role="alert">{error}</p>{/if}
</section>

<style>
  .project-navigation { inline-size: 100%; min-inline-size: 0; box-sizing: border-box; padding-block: var(--spacing-4); }
  .breadcrumb { display: flex; align-items: center; gap: var(--spacing-2); min-inline-size: 0; }
  .breadcrumb :global(svg) { flex-shrink: 0; }
  button { font: inherit; color: var(--color-font-primary); border: 0; background: transparent; cursor: pointer;
    scale: 1; min-inline-size: 0; block-size: auto; margin: 0; filter: none; justify-content: flex-start; transition: background-color 0.15s; }
  button:hover { background: var(--color-grey-20); }
  .icon-control { flex: 0 0 auto; display: inline-flex; align-items: center; justify-content: center; padding: var(--spacing-4); border-radius: var(--radius-3); }
  .crumb { min-inline-size: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: var(--font-size-small); }
  button.crumb { flex: 1; padding: var(--spacing-4) 0; text-align: start; }
  .current { flex: 1.2; }
  .folder-row { display: flex; align-items: center; gap: var(--spacing-6); inline-size: 100%; min-inline-size: 0; padding: var(--spacing-6); border-radius: var(--radius-3); text-align: start; }
  .folder-row :global(svg) { flex-shrink: 0; }
  .row-name { flex: 1; min-inline-size: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .ancestor-list .row-name { white-space: normal; overflow-wrap: anywhere; }
  .ancestor-list { border-block-end: 1px solid var(--color-grey-30); }
  .folder-actions { display: flex; align-items: center; justify-content: space-between; }
  .action { display: inline-flex; align-items: center; gap: var(--spacing-4); padding: var(--spacing-4); font-size: var(--font-size-small); }
  .new-folder { display: flex; align-items: center; gap: var(--spacing-4); padding: var(--spacing-4); }
  input { flex: 1; min-inline-size: 0; font: inherit; font-size: 1rem; background: var(--color-grey-0); color: var(--color-font-primary); border: 1px solid var(--color-grey-30); border-radius: var(--radius-3); padding: var(--spacing-4); }
  .error { color: var(--color-error); font-size: var(--font-size-small); }
  @media (pointer: coarse) { .icon-control, .folder-row, .action { min-block-size: 44px; } }
</style>
