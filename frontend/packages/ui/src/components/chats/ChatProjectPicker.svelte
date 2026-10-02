<!--
  ChatProjectPicker provides the compact chat organization/activity surface.
  Uses shared design tokens and accessible native controls.
  Navigation stays readable within the narrow sidebar.
  Global lifecycle stores remain separate from rendering.
  Colocated fixtures provide isolated component verification.
-->
<script lang="ts">
  import { onMount, tick } from 'svelte';
  import { text } from '@repo/ui';
  import type { Chat } from '../../types/chat';
  import type { ChatProjectLocation, SidebarProject } from '../../utils/chatProjectNavigation';
  import { loadChatProjectIndex, placeChatsInProject, createChatProject, createChatProjectFolder, openChatProjectScreen } from '../../services/chatProjectService';
  import { runningChatIds } from '../../stores/chatActivityStore';
  import ChatProjectNavigator from './ChatProjectNavigator.svelte';
  import ProcessingWheel from './ProcessingWheel.svelte';
  let { initialChats, loadIndex = loadChatProjectIndex, placeChats = placeChatsInProject,
    createProject = createChatProject, createFolder = createChatProjectFolder, openProject = openChatProjectScreen }: {
      initialChats?: Chat[];
      loadIndex?: typeof loadChatProjectIndex; placeChats?: typeof placeChatsInProject;
      createProject?: typeof createChatProject; createFolder?: typeof createChatProjectFolder;
      openProject?: typeof openChatProjectScreen;
    } = $props();
  let dialog = $state<HTMLDialogElement>();
  let chats = $state<Chat[]>([]);
  let projects = $state<SidebarProject[]>([]);
  let location = $state<ChatProjectLocation | null>(null);
  let visible = $state(false);
  let busy = $state(false);
  let loading = $state(false);
  let error = $state('');
  let mode = $state<'add' | 'move'>('add');
  let generation = 0;

  function close(): void { generation++; visible = false; dialog?.close(); }
  async function refresh(): Promise<void> { projects = await loadIndex(true); }
  async function create(): Promise<void> {
    if (busy || !chats.length) return;
    busy = true; error = '';
    try {
      const project = await createProject($state.snapshot(chats));
      close();
      openProject(project.project_id);
    } catch (failure) {
      console.error('[ChatProjectPicker] Project creation failed:', failure);
      error = $text('chats.projects.error');
    } finally { busy = false; }
  }
  async function add(): Promise<void> {
    if (!location || busy) return;
    busy = true; error = '';
    try { await placeChats($state.snapshot(chats), location, mode); close(); }
    catch (failure) { console.error('[ChatProjectPicker] Chat association failed:', failure); error = $text('chats.projects.error'); }
    finally { busy = false; }
  }
  async function show(event: Event): Promise<void> {
    const detail = (event as CustomEvent<{ chats: Chat[]; create?: boolean; mode?: 'add' | 'move' }>).detail;
    if (!detail?.chats?.length || busy) return;
    chats = detail.chats; location = null; projects = []; error = ''; visible = true; mode = detail.mode ?? 'add';
    const current = ++generation;
    await tick(); dialog?.showModal();
    if (detail.create) { await create(); return; }
    loading = true;
    try { const index = await loadIndex(); if (current === generation) projects = index; }
    catch (failure) { console.error('[ChatProjectPicker] Project list failed:', failure); if (current === generation) error = $text('chats.projects.error'); }
    finally { if (current === generation) loading = false; }
  }
  onMount(() => {
    const handler = (event: Event) => { void show(event); };
    window.addEventListener('openmates-chat-project-picker', handler);
    if (initialChats?.length) handler(new CustomEvent('openmates-chat-project-picker', { detail: { chats: initialChats } }));
    return () => { generation++; window.removeEventListener('openmates-chat-project-picker', handler); };
  });
</script>

{#if visible}
  <dialog bind:this={dialog} class="project-picker" aria-labelledby="chat-project-picker-title" data-testid="chat-project-picker"
    oncancel={event => { if (busy) event.preventDefault(); else close(); }}>
    <h2 id="chat-project-picker-title">{$text(mode === 'move' ? 'chats.projects.move' : 'chats.projects.add')}</h2>
    {#if busy || loading}
      <div class="loading" role="status"><ProcessingWheel /><span>{$text(busy ? 'chats.projects.organizing' : 'common.loading')}</span></div>
    {:else}
      <ChatProjectNavigator {projects} {location} runningIds={$runningChatIds}
        onNavigate={next => location = next} onDropChat={() => {}}
        onCreateFolder={async (at, name) => { await createFolder(at, name); await refresh(); }}
        onOpenProject={id => { close(); openProject(id); }} />
    {/if}
    {#if error}<p class="error" role="alert">{error}</p>{/if}
    <div class="actions">
      <button type="button" class="action" data-testid="chat-project-create" disabled={busy || loading} onclick={() => void create()}>{$text('chats.projects.create')}</button>
      {#if location}<button type="button" class="action primary" data-testid="chat-project-add-here" disabled={busy || loading} onclick={() => void add()}>{$text(mode === 'move' ? 'chats.projects.move_here' : 'chats.projects.add_here')}</button>{/if}
      <button type="button" class="action" disabled={busy} onclick={close}>{$text('common.cancel')}</button>
    </div>
  </dialog>
{/if}

<style>
  .project-picker { inline-size: min(24rem, calc(100vw - 2rem)); max-block-size: calc(100dvh - 2rem);
    box-sizing: border-box; overflow-y: auto; padding: var(--spacing-8); border: 1px solid var(--color-grey-30);
    border-radius: var(--radius-5); background: var(--color-grey-0); color: var(--color-font-primary); box-shadow: var(--shadow-lg); }
  .project-picker::backdrop { background: rgb(0 0 0 / 0.35); }
  h2 { font-size: var(--font-size-h4); margin: 0 0 var(--spacing-6); }
  .loading { display: flex; align-items: center; gap: var(--spacing-6); padding-block: var(--spacing-8); }
  .actions { display: flex; flex-wrap: wrap; gap: var(--spacing-4); margin-block-start: var(--spacing-8); }
  .action { padding: var(--spacing-6); border: 0; border-radius: var(--radius-8); background: var(--color-grey-20); color: var(--color-font-primary); font: inherit; cursor: pointer;
    min-inline-size: 0; block-size: auto; margin: 0; filter: none; scale: 1; }
  .primary { background: var(--color-button-primary); color: var(--color-font-button); }
  .action:disabled { opacity: 0.5; cursor: default; }
  .error { color: var(--color-error); font-size: var(--font-size-small); }
  @media (pointer: coarse) { .action { min-block-size: 44px; } }
</style>
