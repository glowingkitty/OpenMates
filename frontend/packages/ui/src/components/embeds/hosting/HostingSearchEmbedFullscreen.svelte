<script lang="ts">
  import SearchResultsTemplate from '../SearchResultsTemplate.svelte';
  import HostingDomainEmbedPreview from './HostingDomainEmbedPreview.svelte';
  import HostingDomainEmbedFullscreen from './HostingDomainEmbedFullscreen.svelte';
  import { text } from '@repo/ui';
  import type { EmbedFullscreenRawData } from '../../../types/embedFullscreen';
  import { boundedView, idList, normalizeDomain, type DomainResult, type DomainSearchContent, type DomainView, type EmbedStatus } from './hostingDomainData';

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
    /** Public synthetic component-preview data; production hydrates encrypted embed_ids. */
    previewChildren?: DomainResult[];
  }

  let { data, onClose, embedId, hasPreviousEmbed = false, hasNextEmbed = false, onNavigatePrevious, onNavigateNext, navigateDirection, showChatButton = false, onShowChat, previewChildren }: Props = $props();
  let searchData = $state<DomainSearchContent>({});
  let status = $state<EmbedStatus>('finished');
  let children = $state<DomainResult[]>([]);
  let view = $state<DomainView>('selected');

  $effect(() => {
    searchData = (data?.decodedContent ?? {}) as DomainSearchContent;
    const raw = data.embedData?.status ?? data.decodedContent?.status;
    status = raw === 'processing' || raw === 'error' || raw === 'cancelled' ? raw : 'finished';
  });

  $effect(() => {
    if (previewChildren) children = previewChildren;
  });

  let checkedIds = $derived(idList(searchData.embed_ids));
  let selectedIds = $derived(idList(searchData.selected_embed_ids));
  let limit = $derived(Math.max(1, Math.min(20, searchData.max_results ?? 10)));
  let visible = $derived.by(() => {
    const initial = boundedView(children, selectedIds, view, limit);
    // A failed exact check has no selected result, but the unknown checked
    // child remains usable as diagnostic evidence on the parent.
    if (view === 'selected' && !initial.length && searchData.error) {
      return boundedView(children, selectedIds, 'unknown', limit);
    }
    return initial;
  });
  let headerSubtitle = $derived(`${$text('embeds.hosting.search_domains.provider_via').replace('{provider}', searchData.provider || 'Gandi')} · ${searchData.currency || 'EUR'}${searchData.country ? ` · ${searchData.country}` : ''}`);

  function updated(event: { status: string; decodedContent: Record<string, unknown> }) {
    searchData = { ...searchData, ...event.decodedContent } as DomainSearchContent;
    if (event.status === 'processing' || event.status === 'finished' || event.status === 'error' || event.status === 'cancelled') status = event.status;
  }

</script>

<SearchResultsTemplate
  testId="hosting-search-fullscreen"
  appId="hosting"
  skillId="search_domains"
  embedHeaderTitle={searchData.query || $text('embeds.hosting.search_domains.title')}
  embedHeaderSubtitle={headerSubtitle}
  skillIconName="search"
  showSkillIcon={true}
  currentEmbedId={embedId}
  {onClose}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
  {navigateDirection}
  {showChatButton}
  {onShowChat}
  embedIds={previewChildren ? undefined : checkedIds}
  localResults={!!previewChildren}
  legacyResults={previewChildren}
  legacyResultTransformer={items => items as DomainResult[]}
  initialChildEmbedId={data.focusChildEmbedId}
  status={children.length ? 'finished' : status}
  errorMessage={searchData.error || undefined}
  emptyTestId="hosting-search-empty"
  gridTestId="hosting-domain-grid"
  filters={{ controls: viewControls, matches: child => visible.some(item => item.embed_id === child.embed_id) }}
  childEmbedTransformer={normalizeDomain}
  onResultsLoaded={(loaded) => { if (!previewChildren) children = loaded as DomainResult[]; }}
  onEmbedDataUpdated={updated}
  headerActionCount={(searchData.unknown_count ?? 0) > 0 ? 5 : 4}
>
  {#snippet viewControls()}
    {#each [
      ['selected', $text('embeds.hosting.search_domains.selected_count').replace('{count}', String(searchData.result_count ?? selectedIds.length))],
      ['available', $text('embeds.hosting.search_domains.show_available')],
      ['all', $text('embeds.hosting.search_domains.show_all')],
      ['in-use', $text('embeds.hosting.search_domains.show_in_use')],
      ...((searchData.unknown_count ?? 0) > 0 ? [['unknown', $text('embeds.hosting.search_domains.show_unknown')]] : [])
    ] as [filter, label]}
      <button type="button" class="button-wrapper domain-filter" aria-pressed={view === filter} data-testid={`hosting-view-${filter}`} onclick={() => view = filter as DomainView}>
        <span class="action-label">{label}</span>
      </button>
    {/each}
  {/snippet}

  {#snippet headerActions()}{@render viewControls()}{/snippet}
  {#snippet emptyContent()}
    {#if status === 'processing'}<p aria-busy="true">{$text('embeds.hosting.search_domains.processing')}</p>
    {:else if status === 'cancelled'}<p>{$text('embeds.hosting.search_domains.cancelled')}</p>
    {:else if searchData.error}<p data-testid="hosting-search-error">{searchData.error}</p>
    {:else}<p>{$text('embeds.hosting.search_domains.no_domains_in_view')}</p>{/if}
  {/snippet}
  {#snippet resultCard({ result: child, onSelect })}
    <HostingDomainEmbedPreview id={child.embed_id} domain={child} presentationOnly={true} onFullscreen={onSelect} />
  {/snippet}
  {#snippet childFullscreen({ result: child, onClose: closeChild, hasPrevious, hasNext, onPrevious, onNext })}
    <HostingDomainEmbedFullscreen domain={child} embedId={child.embed_id} onClose={closeChild} hasPreviousEmbed={hasPrevious} hasNextEmbed={hasNext} onNavigatePrevious={onPrevious} onNavigateNext={onNext} />
  {/snippet}
</SearchResultsTemplate>

<style>
.domain-filter {border:0;border-radius:var(--radius-full);padding:var(--spacing-3) var(--spacing-4);background:var(--color-grey-10);color:var(--color-font-primary);font:inherit;cursor:pointer;pointer-events:auto;} .domain-filter[aria-pressed="true"] {color:var(--color-button-primary);} .domain-filter:focus-visible {outline:2px solid var(--color-button-primary);outline-offset:2px;}
</style>
