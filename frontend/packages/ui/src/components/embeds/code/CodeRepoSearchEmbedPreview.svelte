<!--
  frontend/packages/ui/src/components/embeds/code/CodeRepoSearchEmbedPreview.svelte

  Preview component for the Code app's GitHub repository search skill.
  Uses the common embed shell while keeping the app/skill metadata distinct from
  generic web search embeds.
-->

<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { text } from '@repo/ui';

  interface Props {
    id: string;
    query?: string;
    provider?: string;
    status?: 'processing' | 'finished' | 'error' | 'cancelled';
    results?: unknown[];
    taskId?: string;
    isMobile?: boolean;
    onFullscreen: () => void;
  }

  let {
    id,
    query: queryProp,
    provider: providerProp,
    status: statusProp,
    results: resultsProp,
    taskId,
    isMobile = false,
    onFullscreen
  }: Props = $props();

  let query = $state('');
  let provider = $state('GitHub');
  let status = $state<'processing' | 'finished' | 'error' | 'cancelled'>('processing');
  let results = $state<unknown[]>([]);
  let errorMessage = $state('');

  $effect(() => {
    if (queryProp !== undefined) query = queryProp || '';
    if (providerProp !== undefined) provider = providerProp || 'GitHub';
    if (statusProp !== undefined) status = statusProp || 'processing';
    if (resultsProp !== undefined) results = resultsProp || [];
  });

  let skillName = $derived($text('app_skills.code.search_repos'));
  let viaProvider = $derived(`${$text('embeds.via')} ${provider}`);
  let resultCount = $derived(countResults(results));

  function countResults(rawResults: unknown[]): number {
    if (!Array.isArray(rawResults)) return 0;
    const first = rawResults[0] as Record<string, unknown> | undefined;
    if (first && Array.isArray(first.results)) {
      return rawResults.reduce((sum, entry) => {
        const group = entry as Record<string, unknown>;
        return sum + (Array.isArray(group.results) ? group.results.length : 0);
      }, 0);
    }
    return rawResults.length;
  }

  function handleEmbedDataUpdated(data: { status: string; decodedContent: Record<string, unknown> }) {
    if (data.status === 'processing' || data.status === 'finished' || data.status === 'error' || data.status === 'cancelled') {
      status = data.status;
    }
    const content = data.decodedContent;
    if (typeof content.query === 'string') query = content.query;
    if (typeof content.provider === 'string') provider = content.provider;
    if (Array.isArray(content.results)) results = content.results;
    if (typeof content.error === 'string') errorMessage = content.error;
  }
</script>

<UnifiedEmbedPreview
  {id}
  appId="code"
  skillId="search_repos"
  skillIconName="search"
  {status}
  {skillName}
  {taskId}
  {isMobile}
  {onFullscreen}
  onEmbedDataUpdated={handleEmbedDataUpdated}
>
  {#snippet details({ isMobile: isMobileLayout })}
    <div class="repo-search-details" class:mobile={isMobileLayout}>
      <div class="repo-search-query">{query}</div>
      <div class="repo-search-provider">{viaProvider}</div>
      {#if status === 'error'}
        <div class="repo-search-error">{errorMessage || 'Repository search failed'}</div>
      {:else if status === 'finished'}
        <div class="repo-search-count" data-testid="code-repo-search-count">
          {#if resultCount === 0}
            {$text('embeds.search_no_results_for_query').replace('{query}', query)}
          {:else}
            {resultCount} {resultCount === 1 ? 'repository' : 'repositories'}
          {/if}
        </div>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .repo-search-details {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-2);
    justify-content: center;
    height: 100%;
  }

  .repo-search-query {
    font-size: 15px;
    font-weight: 650;
    color: var(--color-text-primary);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .repo-search-provider,
  .repo-search-count {
    font-size: 13px;
    color: var(--color-text-secondary);
  }

  .repo-search-error {
    font-size: 13px;
    color: var(--color-error, #ef4444);
  }

  :global(.skill-icon[data-skill-icon='search']) {
    -webkit-mask-image: url('@openmates/ui/static/icons/search.svg');
    mask-image: url('@openmates/ui/static/icons/search.svg');
  }
</style>
