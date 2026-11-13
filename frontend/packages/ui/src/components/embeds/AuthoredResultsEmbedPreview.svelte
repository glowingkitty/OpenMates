<script lang="ts">
  import { getContext, type Component } from 'svelte';
  import { text } from '../../i18n/translations';
  import type { AuthoredResultsContent } from '../../types/authoredResult';
  import { EMBED_SOURCE_CHAT_CONTEXT, type EmbedSourceChatContext } from '../../types/embedFullscreen';
  import { embedAvailabilityVersion, embedRefIndexVersion } from '../../services/embedStore';
  import { resolveEmbed, decodeToonContent } from '../../services/embedResolver';
  import { embedPreviewRegistry } from '../../services/embedPreviewRegistry';
  import { dispatchEmbedFullscreen } from '../../services/embedFullscreenController';
  import EmbedsMapView from './EmbedsMapView.svelte';
  import UnifiedEmbedPreview from './UnifiedEmbedPreview.svelte';

  let { id, content, status: statusProp, isMobile = false, onFullscreen }: {
    id: string; content: Partial<AuthoredResultsContent>; isMobile?: boolean;
    status?: 'processing' | 'finished' | 'error' | 'cancelled'; onFullscreen?: () => void;
  } = $props();
  const source = getContext<EmbedSourceChatContext | undefined>(EMBED_SOURCE_CHAT_CONTEXT);
  let hydrated = $state<Partial<AuthoredResultsContent>>();
  const current = $derived(hydrated ?? content);
  const status = $derived(hydrated?.status ?? statusProp ?? current.status ?? 'processing');
  const ids = $derived(current.view?.embeds?.length ? current.view.embeds : current.embed_ids ?? []);
  const singleId = $derived(ids.length === 1 && !current.pending_count && current.view?.mode !== 'map' ? ids[0] : undefined);
  let preview = $state<{ component: Component<Record<string, unknown>>; props: Record<string, unknown> }>();
  let unavailable = $state(false);
  $effect(() => {
    void $embedAvailabilityVersion; void $embedRefIndexVersion;
    const childId = singleId;
    preview = undefined; unavailable = false;
    if (status !== 'finished' || !childId) return;
    let current = true;
    void (async () => {
      const embed = await resolveEmbed(childId, { chatId: source?.exampleChatId ?? source?.lookupChatId ?? source?.chatId ?? undefined });
      if (!current) return;
      if (!embed?.content) { unavailable = true; return; }
      const decoded = await decodeToonContent(embed.content);
      if (!current || !decoded || typeof decoded !== 'object') return;
      const resolved = await embedPreviewRegistry.resolve({ embedId: childId,
        embedData: embed as unknown as Record<string, unknown>, decodedContent: decoded,
        onFullscreen: () => dispatchEmbedFullscreen({ embedId: childId, embedType: embed.type,
          embedData: embed, decodedContent: decoded, sourceChatId: source?.chatId }) });
      if (current && resolved) preview = resolved as typeof preview;
      else if (current) unavailable = true;
    })().catch(() => { if (current) unavailable = true; });
    return () => { current = false; };
  });
  // A carrier request opens the first member; there is no group-level layer.
  function openGroup() {
    if (onFullscreen) onFullscreen();
    else dispatchEmbedFullscreen({ embedId: id, embedType: 'authored_results', decodedContent: current,
      sourceChatId: source?.chatId });
  }
</script>

<section data-testid="authored-results-preview" data-status={status}>
  {#if current.validation?.status === 'partial'}<p role="status" data-testid="authored-results-partial">{$text('embeds.authoring.partial')}</p>{/if}
  {#if status !== 'finished' || unavailable}
    <UnifiedEmbedPreview {id} appId="ai" skillId="authored_results" skillIconName="ai"
      skillName={current.title ?? ''} status={unavailable ? 'error' : status} {isMobile} resultPreview onFullscreen={openGroup}
      onStatusChanged={(resolvedStatus) => { if (resolvedStatus === 'cancelled') hydrated = { ...current, status: resolvedStatus }; }}
      onEmbedDataUpdated={({ status: resolvedStatus, decodedContent }) => {
        const body = decodedContent.type === 'authored_results' ? decodedContent as Partial<AuthoredResultsContent> : current;
        if (['processing', 'finished', 'error', 'cancelled'].includes(resolvedStatus))
          hydrated = { ...body, status: resolvedStatus as AuthoredResultsContent['status'] };
      }}>
      {#snippet details()}<p role="status">{$text(unavailable || status === 'error' ? 'embeds.error' : status === 'cancelled' ? 'embeds.cancelled' : 'embeds.processing')}</p>{/snippet}
    </UnifiedEmbedPreview>
  {:else if singleId}
    {#if preview}{@const Preview = preview.component}<Preview {...preview.props} {isMobile} />
    {:else}<p role="status">{$text('embeds.processing')}</p>{/if}
  {:else}
    <EmbedsMapView {id} title={current.title ?? ''} embedRefs={ids.map(value => `embed:${value}`)}
      includeAllResults viewMode={current.view?.mode ?? 'auto'} pendingCount={current.pending_count ?? 0} />
  {/if}
</section>

<style>
  /* The results view floats its tab switch and filter button over its top edge and reserves that room with margin-top; flow-root keeps the room inside this host so nothing overlaps the message above. */
  section { display: flow-root; width: 100%; min-width: 0; }
  p { color: var(--color-font-secondary); }
</style>
