<script lang="ts">
  import { text } from '../../i18n/translations';
  import type { AppsSavedSearch } from '../../services/appsWorkspaceLibraryService';
  import type { AppsResultItem } from '../../services/appsWorkspaceResultsService';
  import type { Chat } from '../../types/chat';
  import { tick } from 'svelte';
  let { appName, saved, recent, examples, onSaved, onRecent, onExample, onClose, resultTitles = {}, savedEmbeds = [], recentChats = [], onSavedEmbed }: {
    appName: string; saved: AppsSavedSearch[]; recent: AppsResultItem[]; examples: Chat[];
    recentChats?: Chat[]; resultTitles?: Record<string, string>; savedEmbeds?: Array<{ id: string; title: string }>;
    onSavedEmbed: (id: string) => void;
    onSaved: (search: AppsSavedSearch) => void; onRecent: (result: AppsResultItem) => void;
    onExample: (chat: Chat) => void; onClose: () => void;
  } = $props();
  let searchOpen = $state(false);
  let query = $state('');
  let searchInput = $state<HTMLInputElement>();
  const matches = (title: string | undefined) => !query.trim() || (title ?? '').toLocaleLowerCase().includes(query.trim().toLocaleLowerCase());
  const savedTitle = (search: AppsSavedSearch) => search.query || search.title || $text('apps_workspace.saved_search');
  const recentTitle = (result: AppsResultItem) => resultTitles[result.embedId] || result.skillId.replaceAll('_', ' ');
  async function openSearch(): Promise<void> {
    searchOpen = true;
    await tick();
    searchInput?.focus();
  }
</script>

<aside class="apps-sidebar" data-testid="apps-sidebar" aria-label={appName}>
  <div class="sidebar-top">
    {#if searchOpen}
      <input bind:this={searchInput} bind:value={query} type="search" aria-label={$text('common.search')} placeholder={$text('common.search')} onkeydown={event => { if (event.key === 'Escape') { query = ''; searchOpen = false; } }} />
    {:else}
      <button type="button" class="sidebar-action" aria-label={$text('common.search')} onclick={openSearch}><span class="clickable-icon icon_search" aria-hidden="true"></span></button>
    {/if}
    <button type="button" class="sidebar-action sidebar-close" data-testid="apps-sidebar-close" aria-label={$text('common.close')} onclick={onClose}><span class="clickable-icon icon_close" aria-hidden="true"></span></button>
  </div>
  <nav aria-label={appName}>
    <section data-testid="apps-sidebar-saved"><h2>{$text('apps_workspace.saved')}</h2>
      {#each savedEmbeds.filter(item => matches(item.title)) as item (item.id)}<button type="button" class="entry" onclick={() => onSavedEmbed(item.id)}><span class="clickable-icon icon_heart" aria-hidden="true"></span><span class="entry-copy"><span class="entry-title">{item.title}</span></span></button>{/each}
      {#each saved.filter(search => matches(savedTitle(search))) as search (search.id)}<button type="button" class="entry" onclick={() => onSaved(search)}><span class="clickable-icon icon_heart" aria-hidden="true"></span><span class="entry-copy"><span class="entry-title">{savedTitle(search)}</span></span></button>{/each}
    </section>
    <section data-testid="apps-sidebar-recent"><h2>{$text('apps_workspace.recent')}</h2>
      {#each recent.filter(result => matches(recentTitle(result))) as result (result.embedId)}<button type="button" class="entry" onclick={() => onRecent(result)}><span class="clickable-icon icon_history" aria-hidden="true"></span><span class="entry-copy"><span class="entry-title">{recentTitle(result)}</span><small>{new Date(result.createdAt * 1000).toLocaleDateString()}</small></span></button>{/each}
      {#each recentChats.filter(chat => matches(chat.title)) as chat (chat.chat_id)}<button type="button" class="entry" onclick={() => onExample(chat)}><span class="clickable-icon icon_chat" aria-hidden="true"></span><span class="entry-copy"><span class="entry-title">{chat.title}</span></span></button>{/each}
    </section>
    {#if examples.length}<section data-testid="apps-sidebar-examples"><h2>{$text('apps_workspace.example_chats')}</h2>
      {#each examples.filter(chat => matches(chat.title)) as chat (chat.chat_id)}<button type="button" class="entry" onclick={() => onExample(chat)}><span class="clickable-icon icon_chat" aria-hidden="true"></span><span class="entry-copy"><span class="entry-title">{chat.title}</span></span></button>{/each}
    </section>{/if}
  </nav>
</aside>

<style>
  .apps-sidebar { height: 100%; width: 100%; min-width: 0; min-height: 0; overflow: hidden; box-sizing: border-box; display: flex; flex-direction: column; background: var(--color-grey-20); color: var(--color-font-primary); }
  .sidebar-top { display: flex; flex: 0 0 auto; align-items: center; gap: var(--spacing-8); min-height: 32px; padding: var(--spacing-8) var(--spacing-10); border-bottom: 1px solid var(--color-grey-30); }
  /* Sidebar controls must not inherit the global primary-button dimensions,
     margins, shadows or hover scaling. Chat sidebar rows use the same reset. */
  button { all: unset; box-sizing: border-box; font: inherit; color: inherit; cursor: pointer; border-radius: var(--radius-3); }
  button:hover, button:active { scale: none; filter: none; }
  button:focus-visible { outline: 2px solid var(--color-primary-focus); outline-offset: -2px; }
  .sidebar-action { display: grid; place-items: center; width: 32px; height: 32px; flex: 0 0 32px; }
  .sidebar-close { margin-inline-start: auto; }
  .clickable-icon { flex: 0 0 24px; width: 24px; height: 24px; margin: 0; }
  input { box-sizing: border-box; min-width: 0; width: 100%; height: 32px; padding: var(--spacing-4) var(--spacing-6); border: 1px solid var(--color-grey-40); border-radius: var(--radius-3); background: var(--color-grey-10); color: var(--color-font-primary); font: inherit; font-size: var(--font-size-small); }
  nav { flex: 1; min-height: 0; overflow-y: auto; overflow-x: hidden; padding-bottom: var(--spacing-16); scrollbar-width: thin; }
  section { display: flex; flex-direction: column; gap: var(--spacing-2); }
  h2 { font-size: 0.85em; font-weight: 500; color: var(--color-grey-60); margin: 0 0 var(--spacing-3); padding: 15px 15px 0; text-transform: uppercase; letter-spacing: 0.5px; }
  .entry { display: flex; gap: var(--spacing-8); width: 100%; min-height: 56px; text-align: start; padding: var(--spacing-6) var(--spacing-8); align-items: center; }
  .entry-copy { display: flex; flex-direction: column; flex: 1; min-width: 0; line-height: 1.3; }
  .entry-title { display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 2; overflow: hidden; overflow-wrap: anywhere; font-size: var(--font-size-p); font-weight: 500; }
  .icon_heart { mask-image: url('@openmates/ui/static/icons/heart.svg'); -webkit-mask-image: url('@openmates/ui/static/icons/heart.svg'); }
  .icon_history { mask-image: url('@openmates/ui/static/icons/time.svg'); -webkit-mask-image: url('@openmates/ui/static/icons/time.svg'); }
  @media (hover: hover) { .entry:hover, .sidebar-action:hover { background: var(--color-grey-10); } }
  small { display: block; color: var(--color-font-secondary); font-size: var(--font-size-small); margin-top: var(--spacing-2); }
</style>
