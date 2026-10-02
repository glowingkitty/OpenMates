<script lang="ts">
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import ChildEmbedOverlay from '../ChildEmbedOverlay.svelte';
  import HostingDomainEmbedPreview from './HostingDomainEmbedPreview.svelte';
  import HostingDomainEmbedFullscreen from './HostingDomainEmbedFullscreen.svelte';
  import { text } from '@repo/ui';
  import type { EmbedFullscreenRawData } from '../../../types/embedFullscreen';
  import { restorePreviousFullscreenRoute, setChildFullscreenRouteFromParent } from '../../../services/embedFullscreenController';
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
  let selectedChildId = $state<string | null>(null);
  let initialOpenHandled = $state(false);

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
  let selectedIndex = $derived(selectedChildId ? children.findIndex((child) => child.embed_id === selectedChildId) : -1);
  let selectedChild = $derived(selectedIndex >= 0 ? children[selectedIndex] : null);
  let headerSubtitle = $derived(`${$text('embeds.hosting.search_domains.provider_via').replace('{provider}', searchData.provider || 'Gandi')} · ${searchData.currency || 'EUR'}${searchData.country ? ` · ${searchData.country}` : ''}`);

  $effect(() => {
    const initialId = data.focusChildEmbedId;
    if (initialId && !initialOpenHandled && children.some((child) => child.embed_id === initialId)) {
      selectedChildId = initialId;
      initialOpenHandled = true;
    }
  });

  function updated(event: { status: string; decodedContent: Record<string, unknown> }) {
    searchData = { ...searchData, ...event.decodedContent } as DomainSearchContent;
    if (event.status === 'processing' || event.status === 'finished' || event.status === 'error' || event.status === 'cancelled') status = event.status;
  }

  function openChild(child: DomainResult) {
    selectedChildId = child.embed_id;
    if (!previewChildren && embedId) setChildFullscreenRouteFromParent(child.embed_id, embedId);
  }

  function closeChild() {
    if (data.focusChildEmbedId) { onClose(); return; }
    selectedChildId = null;
    if (!previewChildren) restorePreviousFullscreenRoute(embedId ?? null);
  }

  function moveChild(offset: number) {
    const next = children[selectedIndex + offset];
    if (next) openChild(next);
  }
</script>

<UnifiedEmbedFullscreen
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
  childEmbedTransformer={normalizeDomain}
  onChildrenLoaded={(loaded) => { if (!previewChildren) children = loaded as DomainResult[]; }}
  onEmbedDataUpdated={updated}
  headerActionCount={(searchData.unknown_count ?? 0) > 0 ? 5 : 4}
>
  {#snippet headerActions()}
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

  {#snippet content(ctx)}
    <main class="search-results">
      {#if visible.length}
        <div class="grid" data-testid="hosting-domain-grid">
          {#each visible as child (child.embed_id)}
            <HostingDomainEmbedPreview id={child.embed_id} domain={child} presentationOnly={true} onFullscreen={() => openChild(child)} />
          {/each}
        </div>
      {:else if ctx.isLoadingChildren || status === 'processing'}
        <div class="loading" aria-busy="true">{$text('embeds.hosting.search_domains.processing')}</div>
      {:else if status === 'cancelled'}
        <div class="empty">{$text('embeds.hosting.search_domains.cancelled')}</div>
      {:else if searchData.error}
        <div class="empty" data-testid="hosting-search-error">{searchData.error}</div>
      {:else}
        <div class="empty" data-testid="hosting-search-empty">{$text('embeds.hosting.search_domains.no_domains_in_view')}</div>
      {/if}
    </main>
  {/snippet}
</UnifiedEmbedFullscreen>

{#if selectedChild}
  <ChildEmbedOverlay instant={!!data.focusChildEmbedId}>
    <HostingDomainEmbedFullscreen
      domain={selectedChild}
      embedId={selectedChild.embed_id}
      onClose={closeChild}
      hasPreviousEmbed={selectedIndex > 0}
      hasNextEmbed={selectedIndex < children.length - 1}
      onNavigatePrevious={() => moveChild(-1)}
      onNavigateNext={() => moveChild(1)}
    />
  </ChildEmbedOverlay>
{/if}

<style>
  .search-results { max-width: 1100px; margin: 0 auto; padding: var(--spacing-8); color: var(--color-font-primary); }
  .domain-filter { border: 0; border-radius: 40px; padding: var(--spacing-4) var(--spacing-6); background: var(--color-grey-10); color: var(--color-font-primary); font: inherit; cursor: pointer; pointer-events: auto; }
  .domain-filter[aria-pressed="true"] { color: var(--color-button-primary); }
  .domain-filter:focus-visible { outline: 2px solid var(--color-button-primary); outline-offset: 2px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 280px), 1fr)); gap: var(--spacing-8); padding: var(--spacing-8) 0 96px; }
  .grid :global(.unified-embed-preview) { width: 100% !important; min-width: 0 !important; max-width: 320px !important; margin: 0 auto; }
  .loading, .empty { padding: var(--spacing-12); text-align: center; color: var(--color-font-secondary); }
  @container fullscreen (max-width: 500px) { .search-results { padding: var(--spacing-4); } .grid { grid-template-columns: 1fr; gap: var(--spacing-5); } }
</style>
