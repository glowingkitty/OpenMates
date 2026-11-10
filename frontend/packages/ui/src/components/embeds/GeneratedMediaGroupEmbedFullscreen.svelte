<!-- One skill-use invocation opens a grid of its actual generated output embeds. -->
<script lang="ts">
  import { getContext } from 'svelte';
  import { text } from '@repo/ui';
  import SearchResultsTemplate from './SearchResultsTemplate.svelte';
  import GeneratedMediaChildPreview from './GeneratedMediaChildPreview.svelte';
  import ImageGenerateEmbedFullscreen from './images/ImageGenerateEmbedFullscreen.svelte';
  import AudioGenerateEmbedFullscreen from './audio/AudioGenerateEmbedFullscreen.svelte';
  import MusicGenerateEmbedFullscreen from './music/MusicGenerateEmbedFullscreen.svelte';
  import VideoGenerateEmbedFullscreen from './videos/VideoGenerateEmbedFullscreen.svelte';
  import Model3DGenerateEmbedFullscreen from './models3d/Model3DGenerateEmbedFullscreen.svelte';
  import DesignEmbroideryEmbedFullscreen from './design/DesignEmbroideryEmbedFullscreen.svelte';
  import { generatedMediaChildIds } from './generatedMediaGroup';
  import { pinnedEmbedsOf } from '../../services/rustCore/embeds/messageEmbedVersion';
  import type { PinnedEmbed } from '../../services/rustCore/embeds/childRevisionProtocol';
  import { imageContentAtVersion } from './images/imageVersionScope';
  import { EMBED_SOURCE_CHAT_CONTEXT, type EmbedSourceChatContext } from '../../types/embedFullscreen';
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
  const sourceChat = getContext<EmbedSourceChatContext | undefined>(EMBED_SOURCE_CHAT_CONTEXT);
  const sourceChatId = sourceChat?.lookupChatId ?? sourceChat?.chatId ?? null;
  // A skill use that changed an earlier image pins that image's new version (core rule).
  // Its grid card shows that version: the pinned child joins the grid once its content is open.
  let pins = $state<PinnedEmbed[]>([]);
  let pinnedContents = $state<Map<string, Record<string, unknown>>>(new Map());
  let pinError = $state<string | undefined>(undefined);
  $effect(() => {
    const source = content;
    void (async () => {
      try {
        const next = await pinnedEmbedsOf(source);
        const opened = new Map<string, Record<string, unknown>>();
        for (const pin of next) opened.set(pin.embed_id, await imageContentAtVersion(sourceChatId, pin.embed_id, pin.version));
        pinnedContents = opened;
        pins = next;
      } catch (err) {
        console.error('[GeneratedMediaGroupEmbedFullscreen] Failed to open pinned versions:', err);
        pinError = err instanceof Error ? err.message : String(err);
      }
    })();
  });
  const embedIds = $derived([...new Set([
    ...(generatedMediaChildIds(content).length > 0
      ? generatedMediaChildIds(content)
      : generatedMediaChildIds(data.embedData)),
    ...pins.map((pin) => pin.embed_id),
  ])]);
  const pinnedVersion = (childId: string) => pins.find((pin) => pin.embed_id === childId)?.version;
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
    return { ...(pinnedContents.get(childEmbedId) ?? childContent), embed_id: childEmbedId };
  }
</script>

<SearchResultsTemplate
  testId="generated-media-group-fullscreen"
  {appId} {skillId} skillIconName={appId === 'models3d' ? '3dmodels' : appId === 'design' ? 'embroidery' : appId}
  embedHeaderTitle={skillName} embedHeaderSubtitle={subtitle}
  {onClose} currentEmbedId={embedId} {embedIds}
  childEmbedTransformer={childFromContent}
  initialChildEmbedId={data.focusChildEmbedId ?? undefined}
  {hasPreviousEmbed} {hasNextEmbed} {onNavigatePrevious} {onNavigateNext}
  navigateDirection={navigateDirection ?? undefined}
  {showChatButton} {onShowChat} {status}
  errorMessage={typeof content.error === 'string' ? content.error : pinError}
  skeletonCount={Math.max(1, resultCount || 1)} minCardWidth="260px"
>
  {#snippet resultCard({ result, onSelect })}
    <GeneratedMediaChildPreview {appId} {result} {onSelect} />
  {/snippet}
  {#snippet childFullscreen(nav)}
    {@const childData = { decodedContent: nav.result, embedData: { status: 'finished' } }}
    {#if appId === 'images'}
      <ImageGenerateEmbedFullscreen data={childData} embedId={nav.result.embed_id} onClose={nav.onClose}
        initialVersion={pinnedVersion(nav.result.embed_id)}
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
    {:else if appId === 'design'}
      <DesignEmbroideryEmbedFullscreen data={childData} embedId={nav.result.embed_id} onClose={nav.onClose}
        hasPreviousEmbed={nav.hasPrevious} hasNextEmbed={nav.hasNext}
        onNavigatePrevious={nav.onPrevious} onNavigateNext={nav.onNext} />
    {/if}
  {/snippet}
</SearchResultsTemplate>
