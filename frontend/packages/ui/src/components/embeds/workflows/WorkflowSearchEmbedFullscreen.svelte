<!--
  frontend/packages/ui/src/components/embeds/workflows/WorkflowSearchEmbedFullscreen.svelte
  Fullscreen parent view for workflows.search embeds.
  Reuses SearchResultsTemplate for responsive child grid and drilldown.
  Child workflow detail upgrades snapshots to live store data when possible.
-->

<script lang="ts">
  import SearchResultsTemplate from '../SearchResultsTemplate.svelte';
  import WorkflowEmbedPreview from './WorkflowEmbedPreview.svelte';
  import WorkflowEmbedFullscreen from './WorkflowEmbedFullscreen.svelte';
  import type { EmbedFullscreenRawData } from '../../../types/embedFullscreen';
  import { extractSearchResultsFromContent } from '../embedPreviewHydration';
  import { normalizeWorkflowLegacyResults, normalizeWorkflowResult, type WorkflowEmbedResult } from './workflowEmbedData';

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

  let { data, onClose, embedId, hasPreviousEmbed = false, hasNextEmbed = false, onNavigatePrevious, onNavigateNext, navigateDirection, showChatButton = false, onShowChat }: Props = $props();

  let status = $derived((data.embedData?.status ?? data.decodedContent?.status ?? 'finished') as 'processing' | 'finished' | 'error' | 'cancelled');
  let query = $derived(typeof data.decodedContent?.query === 'string' ? data.decodedContent.query : 'Search workflows');
  let embedIds = $derived(data.decodedContent?.embed_ids ?? data.embedData?.embed_ids);
  let initialChildEmbedId = $derived(data.focusChildEmbedId ?? undefined);

  function legacyResultsFromContent(content: Record<string, unknown> | undefined): WorkflowEmbedResult[] | undefined {
    if (!content) return undefined;
    const results = extractSearchResultsFromContent(content, ['results', 'preview_results']);
    return results.length > 0 ? normalizeWorkflowLegacyResults(results) : undefined;
  }

  let legacyResults = $derived(legacyResultsFromContent(data.decodedContent));
</script>

<SearchResultsTemplate
  appId="workflows"
  skillId="search"
  skillIconName="search"
  embedHeaderTitle={query}
  embedHeaderSubtitle="Matching workflows"
  {onClose}
  currentEmbedId={embedId}
  {embedIds}
  childEmbedTransformer={normalizeWorkflowResult}
  {legacyResults}
  legacyResultTransformer={normalizeWorkflowLegacyResults}
  {initialChildEmbedId}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
  {navigateDirection}
  {showChatButton}
  {onShowChat}
  skeletonCount={4}
  minCardWidth="260px"
  {status}
  {query}
>
  {#snippet resultCard({ result, onSelect })}
    <WorkflowEmbedPreview id={result.embed_id} workflowId={result.workflow_id} title={result.title} description={result.description} status={result.status} enabled={result.enabled} triggerSummary={result.trigger_summary} onFullscreen={onSelect} />
  {/snippet}
  {#snippet childFullscreen(nav)}
    <WorkflowEmbedFullscreen data={{ decodedContent: nav.result }} embedId={nav.result.embed_id} hasPreviousEmbed={nav.hasPrevious} hasNextEmbed={nav.hasNext} onNavigatePrevious={nav.onPrevious} onNavigateNext={nav.onNext} onClose={nav.onClose} />
  {/snippet}
</SearchResultsTemplate>
