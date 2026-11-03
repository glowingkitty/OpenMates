<script lang="ts">
  import { text } from '../../i18n/translations';
  import UnifiedEmbedFullscreen from './UnifiedEmbedFullscreen.svelte';
  import EmbedsMapView from './EmbedsMapView.svelte';
  import type { EmbedFullscreenCommonProps, EmbedFullscreenRawData } from '../../types/embedFullscreen';
  import type { AuthoredResultsContent } from '../../types/authoredResult';
  // This internal adapter forwards the shared fullscreen contract.
  // svelte-ignore custom_element_props_identifier
  let { data, embedId, ...controls }: EmbedFullscreenCommonProps & { data: EmbedFullscreenRawData } = $props();
  const records = $derived(data.decodedContent as unknown as AuthoredResultsContent);
  const id = $derived(embedId ?? String(data.embedData?.embed_id ?? data.embedData?.id ?? ''));
  const ids = $derived(records.view?.embeds?.length ? records.view.embeds : records.embed_ids ?? []);
</script>

<UnifiedEmbedFullscreen {...controls} appId="ai" skillId="authored_results" skillIconName="ai"
  currentEmbedId={id} title={records.title}>
  {#snippet content()}
    {#if records.validation?.status === 'partial'}<p role="status" data-testid="authored-results-partial">{$text('embeds.authoring.partial')}</p>{/if}
    {#if records.status !== 'finished'}
      <p role="status">{$text(records.status === 'error' ? 'embeds.error' : records.status === 'cancelled' ? 'embeds.cancelled' : 'embeds.processing')}</p>
    {:else}
    <EmbedsMapView {id} title={records.title} embedRefs={ids.map(value => `embed:${value}`)}
      includeAllResults cardsOnly={records.view?.mode !== 'map'} fullscreen />
    {/if}
  {/snippet}
</UnifiedEmbedFullscreen>
