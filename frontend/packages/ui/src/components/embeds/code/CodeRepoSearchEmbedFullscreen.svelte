<!--
  frontend/packages/ui/src/components/embeds/code/CodeRepoSearchEmbedFullscreen.svelte

  Fullscreen grid for Code search_repos results. It renders child repository
  embeds with the dedicated GitHub repo preview/fullscreen components.
-->

<script lang="ts">
  import SearchResultsTemplate from '../SearchResultsTemplate.svelte';
  import CodeRepoEmbedPreview from './CodeRepoEmbedPreview.svelte';
  import CodeRepoEmbedFullscreen from './CodeRepoEmbedFullscreen.svelte';
  import { text } from '@repo/ui';
  import type { EmbedFullscreenRawData } from '../../../types/embedFullscreen';

  interface RepoResult {
    embed_id: string;
    url: string;
    full_name?: string;
    name?: string;
    owner_login?: string;
    owner_avatar_url?: string;
    description?: string;
    primary_language?: string;
    license_name?: string;
    license_spdx_id?: string;
    stars?: number;
    forks?: number;
    open_issues?: number;
    updated_at?: string;
    [key: string]: unknown;
  }

  interface Props {
    data: EmbedFullscreenRawData;
    onClose: () => void;
    embedId?: string;
    hasPreviousEmbed?: boolean;
    hasNextEmbed?: boolean;
    onNavigatePrevious?: () => void;
    onNavigateNext?: () => void;
    navigateDirection?: 'previous' | 'next';
    showChatButton?: boolean;
    onShowChat?: () => void;
  }

  let {
    data,
    onClose,
    embedId,
    hasPreviousEmbed = false,
    hasNextEmbed = false,
    onNavigatePrevious,
    onNavigateNext,
    navigateDirection,
    showChatButton = false,
    onShowChat
  }: Props = $props();

  let initialChildEmbedId = $derived(data.focusChildEmbedId ?? undefined);
  let embedIds = $derived(data.decodedContent?.embed_ids ?? data.embedData?.embed_ids);
  let legacyResults = $derived(Array.isArray(data.decodedContent?.results) ? data.decodedContent.results as unknown[] : []);
  let query = $state('');
  let provider = $state('GitHub');
  let localStatus = $state<'processing' | 'finished' | 'error' | 'cancelled'>('finished');
  let localErrorMessage = $state('');
  let embedIdsOverride = $state<string | string[] | undefined>(undefined);
  let embedIdsValue = $derived(embedIdsOverride ?? embedIds);
  let viaProvider = $derived(`${$text('embeds.via')} ${provider}`);

  $effect(() => {
    query = typeof data.decodedContent?.query === 'string' ? data.decodedContent.query : '';
    provider = typeof data.decodedContent?.provider === 'string' ? data.decodedContent.provider : 'GitHub';
    localStatus = normalizeStatus(data.embedData?.status ?? data.decodedContent?.status);
    localErrorMessage = typeof data.decodedContent?.error === 'string' ? data.decodedContent.error : '';
  });

  function normalizeStatus(value: unknown): 'processing' | 'finished' | 'error' | 'cancelled' {
    if (value === 'processing' || value === 'finished' || value === 'error' || value === 'cancelled') return value;
    return 'finished';
  }

  function asString(value: unknown): string | undefined {
    return typeof value === 'string' && value.length > 0 ? value : undefined;
  }

  function asNumber(value: unknown): number | undefined {
    return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
  }

  function transformToRepoResult(embedId: string, content: Record<string, unknown>): RepoResult {
    return {
      ...content,
      embed_id: embedId,
      url: asString(content.url) || asString(content.html_url) || '',
      full_name: asString(content.full_name),
      name: asString(content.name),
      owner_login: asString(content.owner_login),
      owner_avatar_url: asString(content.owner_avatar_url),
      description: asString(content.description),
      primary_language: asString(content.primary_language),
      license_name: asString(content.license_name),
      license_spdx_id: asString(content.license_spdx_id),
      stars: asNumber(content.stars),
      forks: asNumber(content.forks),
      open_issues: asNumber(content.open_issues),
      updated_at: asString(content.updated_at)
    };
  }

  function transformLegacyResults(results: unknown[]): RepoResult[] {
    const rows: RepoResult[] = [];
    for (const groupOrResult of results as Array<Record<string, unknown>>) {
      if (Array.isArray(groupOrResult.results)) {
        groupOrResult.results.forEach((result, index) => {
          rows.push(transformToRepoResult(`legacy-${rows.length}-${index}`, result as Record<string, unknown>));
        });
      } else {
        rows.push(transformToRepoResult(`legacy-${rows.length}`, groupOrResult));
      }
    }
    return rows;
  }

  function handleEmbedDataUpdated(update: { status: string; decodedContent: Record<string, unknown> }) {
    localStatus = normalizeStatus(update.status);
    const content = update.decodedContent;
    if (typeof content.query === 'string') query = content.query;
    if (typeof content.provider === 'string') provider = content.provider;
    if (content.embed_ids) embedIdsOverride = content.embed_ids as string | string[];
    if (typeof content.error === 'string') localErrorMessage = content.error;
  }
</script>

<SearchResultsTemplate
  appId="code"
  skillId="search_repos"
  embedHeaderTitle={query}
  embedHeaderSubtitle={viaProvider}
  skillIconName="search"
  showSkillIcon={true}
  {onClose}
  currentEmbedId={embedId}
  embedIds={embedIdsValue}
  childEmbedTransformer={transformToRepoResult}
  {legacyResults}
  legacyResultTransformer={transformLegacyResults}
  status={localStatus}
  errorMessage={localErrorMessage}
  {query}
  minCardWidth="320px"
  onEmbedDataUpdated={handleEmbedDataUpdated}
  {initialChildEmbedId}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
  {navigateDirection}
  {showChatButton}
  {onShowChat}
>
  {#snippet resultCard({ result, onSelect })}
    <CodeRepoEmbedPreview
      id={result.embed_id}
      url={result.url}
      fullName={result.full_name}
      name={result.name}
      ownerLogin={result.owner_login}
      ownerAvatarUrl={result.owner_avatar_url}
      description={result.description}
      primaryLanguage={result.primary_language}
      licenseName={result.license_name}
      licenseSpdxId={result.license_spdx_id}
      stars={result.stars}
      forks={result.forks}
      openIssues={result.open_issues}
      updatedAt={result.updated_at}
      status="finished"
      isMobile={false}
      onFullscreen={onSelect}
    />
  {/snippet}

  {#snippet childFullscreen(nav)}
    <CodeRepoEmbedFullscreen
      data={{ decodedContent: nav.result }}
      onClose={nav.onClose}
      embedId={nav.result.embed_id}
      hasPreviousEmbed={nav.hasPrevious}
      hasNextEmbed={nav.hasNext}
      onNavigatePrevious={nav.onPrevious}
      onNavigateNext={nav.onNext}
    />
  {/snippet}
</SearchResultsTemplate>

<style>
  :global(.unified-embed-fullscreen-overlay .skill-icon[data-skill-icon='search']) {
    -webkit-mask-image: url('@openmates/ui/static/icons/search.svg');
    mask-image: url('@openmates/ui/static/icons/search.svg');
  }
</style>
