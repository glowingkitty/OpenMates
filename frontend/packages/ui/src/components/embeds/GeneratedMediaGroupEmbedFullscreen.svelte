<!-- One skill-use invocation opens a grid of its actual generated output embeds. -->
<script lang="ts">
  import { text } from '@repo/ui';
  import SearchResultsTemplate from './SearchResultsTemplate.svelte';
  import GeneratedMediaChildPreview from './GeneratedMediaChildPreview.svelte';
  import ImageGenerateEmbedFullscreen from './images/ImageGenerateEmbedFullscreen.svelte';
  import AudioGenerateEmbedFullscreen from './audio/AudioGenerateEmbedFullscreen.svelte';
  import MusicGenerateEmbedFullscreen from './music/MusicGenerateEmbedFullscreen.svelte';
  import VideoGenerateEmbedFullscreen from './videos/VideoGenerateEmbedFullscreen.svelte';
  import Model3DGenerateEmbedFullscreen from './models3d/Model3DGenerateEmbedFullscreen.svelte';
  import { generatedMediaChildIds } from './generatedMediaGroup';
  import type { EmbedFullscreenRawData } from '../../types/embedFullscreen';

  interface GeneratedChild extends Record<string, unknown> { embed_id: string; }
  interface Props {
    data: EmbedFullscreenRawData;
    embedId?: string;
    onClose: () => void;
    hasPreviousEmbed?: boolean;
    hasNextEmbed?: boolean;
    onNavigatePrevious?: () => void;
    onNavigateNext?: () => void;
    navigateDirection?: 'previous' | 'next' | null;
    showChatButton?: boolean;
    onShowChat?: () => void;
  }

  let {
    data, embedId, onClose, hasPreviousEmbed = false, hasNextEmbed = false,
    onNavigatePrevious, onNavigateNext, navigateDirection = null,
    showChatButton = false, onShowChat,
  }: Props = $props();
  const content = $derived(data.decodedContent);
  const appId = $derived(typeof content.app_id === 'string' ? content.app_id : 'images');
  const skillId = $derived(typeof content.skill_id === 'string' ? content.skill_id : 'generate');
  const skillName = $derived($text(`app_skills.${appId}.${skillId}`));
  const embedIds = $derived(
    generatedMediaChildIds(content).length > 0
      ? generatedMediaChildIds(content)
      : generatedMediaChildIds(data.embedData),
  );
  const resultCount = $derived(typeof content.result_count === 'number' ? content.result_count : 0);
  const failedCount = $derived(Array.isArray(content.failed_results) ? content.failed_results.length : 0);
  const status = $derived(
    content.status === 'error' ? 'error'
      : data.embedData?.status === 'processing' ? 'processing' : 'finished',
  );
  const subtitle = $derived([
    resultCount > 0 ? `${resultCount} ${$text('apps_workspace.results')}` : '',
    failedCount > 0 ? String(content.error || '') : '',
  ].filter(Boolean).join(' · '));

  function childFromContent(childEmbedId: string, childContent: Record<string, unknown>): GeneratedChild {
    return { ...childContent, embed_id: childEmbedId };
  }
</script>

<SearchResultsTemplate
  testId="generated-media-group-fullscreen"
  {appId} {skillId} skillIconName={appId === 'models3d' ? '3dmodels' : appId}
  embedHeaderTitle={skillName} embedHeaderSubtitle={subtitle}
  {onClose} currentEmbedId={embedId} {embedIds}
  childEmbedTransformer={childFromContent}
  initialChildEmbedId={data.focusChildEmbedId ?? undefined}
  {hasPreviousEmbed} {hasNextEmbed} {onNavigatePrevious} {onNavigateNext}
  navigateDirection={navigateDirection ?? undefined}
  {showChatButton} {onShowChat} {status}
  errorMessage={typeof content.error === 'string' ? content.error : undefined}
  skeletonCount={Math.max(1, resultCount || 1)} minCardWidth="260px"
>
  {#snippet resultCard({ result, onSelect })}
    <GeneratedMediaChildPreview {appId} {result} {onSelect} />
  {/snippet}
  {#snippet childFullscreen(nav)}
    {@const childData = { decodedContent: nav.result, embedData: { status: 'finished' } }}
    {#if appId === 'images'}
      <ImageGenerateEmbedFullscreen data={childData} embedId={nav.result.embed_id} onClose={nav.onClose}
        hasPreviousEmbed={nav.hasPrevious} hasNextEmbed={nav.hasNext}
        onNavigatePrevious={nav.onPrevious} onNavigateNext={nav.onNext} />
    {:else if appId === 'audio'}
      <AudioGenerateEmbedFullscreen data={childData} embedId={nav.result.embed_id} onClose={nav.onClose}
        hasPreviousEmbed={nav.hasPrevious} hasNextEmbed={nav.hasNext}
        onNavigatePrevious={nav.onPrevious} onNavigateNext={nav.onNext} />
    {:else if appId === 'music'}
      <MusicGenerateEmbedFullscreen data={childData} embedId={nav.result.embed_id} onClose={nav.onClose}
        hasPreviousEmbed={nav.hasPrevious} hasNextEmbed={nav.hasNext}
        onNavigatePrevious={nav.onPrevious} onNavigateNext={nav.onNext} />
    {:else if appId === 'videos'}
      <VideoGenerateEmbedFullscreen data={childData} embedId={nav.result.embed_id} onClose={nav.onClose}
        hasPreviousEmbed={nav.hasPrevious} hasNextEmbed={nav.hasNext}
        onNavigatePrevious={nav.onPrevious} onNavigateNext={nav.onNext} />
    {:else if appId === 'models3d'}
      <Model3DGenerateEmbedFullscreen data={childData} embedId={nav.result.embed_id} onClose={nav.onClose}
        hasPreviousEmbed={nav.hasPrevious} hasNextEmbed={nav.hasNext}
        onNavigatePrevious={nav.onPrevious} onNavigateNext={nav.onNext} />
    {/if}
  {/snippet}
</SearchResultsTemplate>
