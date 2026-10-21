<script lang="ts">
  import { text } from '../../i18n/translations';
  import type { AppsSavedSearch } from '../../services/appsWorkspaceLibraryService';
  import type { AppsResultItem } from '../../services/appsWorkspaceResultsService';
  import type { Chat } from '../../types/chat';
  let { appName, saved, recent, examples, onSaved, onRecent, onExample, onClose, resultTitles = {}, savedEmbeds = [], recentChats = [], onSavedEmbed }: {
    appName: string; saved: AppsSavedSearch[]; recent: AppsResultItem[]; examples: Chat[];
    recentChats?: Chat[]; resultTitles?: Record<string, string>; savedEmbeds?: Array<{ id: string; title: string }>;
    onSavedEmbed: (id: string) => void;
    onSaved: (search: AppsSavedSearch) => void; onRecent: (result: AppsResultItem) => void;
    onExample: (chat: Chat) => void; onClose: () => void;
  } = $props();
</script>

<aside class="apps-sidebar" data-testid="apps-sidebar" aria-label={appName}>
  <div class="sidebar-top"><strong>{appName}</strong><button aria-label={$text('common.close')} onclick={onClose}><span class="clickable-icon icon_close" aria-hidden="true"></span></button></div>
  <nav aria-label={appName}>
    <section data-testid="apps-sidebar-saved"><h2>{$text('apps_workspace.saved')}</h2>
      {#each savedEmbeds as item (item.id)}<button class="entry" onclick={() => onSavedEmbed(item.id)}><span class="clickable-icon icon_heart" aria-hidden="true"></span><span>{item.title}</span></button>{/each}
      {#each saved as search (search.id)}<button class="entry" onclick={() => onSaved(search)}><span class="clickable-icon icon_heart" aria-hidden="true"></span><span>{search.query || search.title || $text('apps_workspace.saved_search')}</span></button>{/each}
    </section>
    <section data-testid="apps-sidebar-recent"><h2>{$text('apps_workspace.recent')}</h2>
      {#each recent as result (result.embedId)}<button class="entry" onclick={() => onRecent(result)}><span class="clickable-icon icon_history" aria-hidden="true"></span><span>{resultTitles[result.embedId] || result.skillId.replaceAll('_', ' ')}<small>{new Date(result.createdAt * 1000).toLocaleDateString()}</small></span></button>{/each}
      {#each recentChats as chat (chat.chat_id)}<button class="entry" onclick={() => onExample(chat)}><span class="clickable-icon icon_chat" aria-hidden="true"></span><span>{chat.title}</span></button>{/each}
    </section>
    {#if examples.length}<section data-testid="apps-sidebar-examples"><h2>{$text('apps_workspace.example_chats')}</h2>
      {#each examples as chat (chat.chat_id)}<button class="entry" onclick={() => onExample(chat)}><span class="clickable-icon icon_chat" aria-hidden="true"></span><span>{chat.title}</span></button>{/each}
    </section>{/if}
  </nav>
</aside>

<style>
  .apps-sidebar { height: 100%; min-height: 0; box-sizing: border-box; display: flex; flex-direction: column; background: var(--color-grey-20); color: var(--color-font-primary); border-radius: var(--radius-5); }
  .sidebar-top { display: flex; align-items: center; justify-content: space-between; padding: var(--spacing-8); }
  nav { min-height: 0; overflow-y: auto; padding: var(--spacing-4) var(--spacing-8) var(--spacing-16); }
  h2 { font-size: var(--font-size-small); color: var(--color-font-secondary); margin: var(--spacing-12) 0 var(--spacing-6); }
  button { font: inherit; color: inherit; cursor: pointer; border: 0; background: transparent; border-radius: var(--radius-5); }
  .entry { display: flex; gap: var(--spacing-8); width: 100%; text-align: start; padding: var(--spacing-8) var(--spacing-4); align-items: center; }
  .entry > span:last-child { min-width: 0; overflow-wrap: anywhere; }
  .icon_heart { mask-image: url('@openmates/ui/static/icons/heart.svg'); -webkit-mask-image: url('@openmates/ui/static/icons/heart.svg'); }
  .icon_history { mask-image: url('@openmates/ui/static/icons/time.svg'); -webkit-mask-image: url('@openmates/ui/static/icons/time.svg'); }
  .entry:hover, .entry:focus-visible { background: var(--color-grey-0); }
  small { display: block; color: var(--color-font-secondary); margin-top: var(--spacing-2); }
</style>
