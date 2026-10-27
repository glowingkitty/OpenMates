<!--
  frontend/packages/ui/src/components/embeds/models3d/Model3DResultEmbedPreview.svelte

  Preview-only child card for a 3D model catalog result. Source-provider CTAs
  are intentionally reserved for fullscreen so preview cards stay navigational.
-->

<script lang="ts">
  import { text } from '@repo/ui';

  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import ResultEmbedCard from '../ResultEmbedCard.svelte';
  import ResultEmbedInfo from '../ResultEmbedInfo.svelte';
  import { proxyImage, MAX_WIDTH_PREVIEW_THUMBNAIL } from '../../../utils/imageProxy';

  interface Props {
    id: string;
    title?: string;
    provider?: string;
    creatorName?: string;
    sourcePageUrl?: string;
    previewImageUrl?: string;
    thumbnailUrl?: string;
    license?: string;
    filesCount?: number | null;
    isFree?: boolean | null;
    status?: 'processing' | 'finished' | 'error';
    isMobile?: boolean;
    presentationOnly?: boolean;
    resultContext?: 'auto' | 'chat' | 'results';
    onFullscreen: () => void;
  }

  let {
    id,
    title = '',
    provider = '',
    creatorName = '',
    previewImageUrl = '',
    thumbnailUrl = '',
    license = '',
    filesCount = null,
    isFree = null,
    status = 'finished',
    isMobile = false,
    presentationOnly = false,
    resultContext = 'auto',
    onFullscreen,
  }: Props = $props();

  let displayImage = $derived(proxyImage(previewImageUrl || thumbnailUrl, MAX_WIDTH_PREVIEW_THUMBNAIL));
  let cardTitle = $derived(title || $text('embeds.models3d.search.result_title'));

  function handleStop() {
    // Result cards are not cancellable.
  }
</script>

<UnifiedEmbedPreview
  resultPreview={true}
  {presentationOnly}
  {resultContext}
  {id}
  appId="models3d"
  skillId="model_result"
  skillIconName="3dmodels"
  {status}
  skillName={provider || $text('apps.models3d')}
  {isMobile}
  {onFullscreen}
  onStop={handleStop}
  showStatus={false}
  showSkillIcon={false}
>

  {#snippet details()}
    <div data-testid="models3d-result-card" class="catalog-result-preview">
      <ResultEmbedCard title={cardTitle} sourceLabel={[creatorName, provider].filter(Boolean).join(" · ")} imageUrl={displayImage} imageAlt={cardTitle} mediaFit="contain">
        {#snippet facts()}{#if license}<ResultEmbedInfo icon="Scale" label="License" value={license}>{#snippet children()}{license}{/snippet}</ResultEmbedInfo>{/if}
{#if filesCount != null}<ResultEmbedInfo icon="Files" label="Files" value={String(filesCount)}>{#snippet children()}{filesCount} catalogue files{/snippet}</ResultEmbedInfo>{/if}
{#if isFree != null}<ResultEmbedInfo icon="BadgeDollarSign" label="Free model" state={isFree ? 'yes' : 'no'}>{#snippet children()}{isFree ? 'Listed as free by the provider.' : 'Not listed as free by the provider.'}{/snippet}</ResultEmbedInfo>{/if}{/snippet}
      </ResultEmbedCard>
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .catalog-result-preview { width: 100%; height: 100%; min-width: 0; }
</style>
