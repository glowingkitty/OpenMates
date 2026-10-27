<script lang="ts">
  import UnifiedEmbedPreview from '../embeds/UnifiedEmbedPreview.svelte';
  import { text } from '../../i18n/translations';
  import type { AppsSavedSearch } from '../../services/appsWorkspaceLibraryService';
  let { search, appId, onOpen }: { search: AppsSavedSearch; appId: string; onOpen: () => void } = $props();
</script>

<UnifiedEmbedPreview id={search.id} {appId} skillId={search.skill_id} skillIconName="search"
  skillName={$text('apps_workspace.saved_search')} status="finished" onFullscreen={onOpen}>
  {#snippet details()}
    <div class="saved-search-query" data-testid="apps-saved-search-query">
      <strong>{search.query || search.title || $text('apps_workspace.saved_search')}</strong>
      <span>{$text('apps_workspace.run_saved_search')}</span>
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .saved-search-query { display: flex; flex-direction: column; justify-content: center; gap: var(--spacing-6); height: 100%; padding: var(--spacing-8); box-sizing: border-box; }
  strong { overflow: hidden; display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; }
  span { font-size: var(--font-size-small); color: var(--color-font-secondary); }
</style>
