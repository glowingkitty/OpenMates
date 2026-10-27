<!--
  frontend/packages/ui/src/components/embeds/models3d/Model3DResultEmbedFullscreen.svelte

  Fullscreen metadata view for a preview-only 3D model search result. It links
  to the source provider and intentionally does not fetch model files.
-->

<script lang="ts">
  import { text } from '@repo/ui';
  import ResultEmbedFullscreen from '../ResultEmbedFullscreen.svelte';
  import ResultEmbedInfo from '../ResultEmbedInfo.svelte';
  import EmbedHeaderCtaButton from '../EmbedHeaderCtaButton.svelte';
  import { proxyImage } from '../../../utils/imageProxy';
  import type { EmbedFullscreenRawData } from '../../../types/embedFullscreen';

  interface Props {
    data: EmbedFullscreenRawData;
    embedId?: string;
    onClose: () => void;
    hasPreviousEmbed?: boolean;
    hasNextEmbed?: boolean;
    onNavigatePrevious?: () => void;
    onNavigateNext?: () => void;
  }

  let {
    data,
    embedId,
    onClose,
    hasPreviousEmbed = false,
    hasNextEmbed = false,
    onNavigatePrevious,
    onNavigateNext,
  }: Props = $props();

  let modelContent = $derived({
    ...(data.embedData ?? {}),
    ...(data.attrs ?? {}),
    ...(data.decodedContent ?? {}),
  });
  let title = $derived(typeof modelContent.title === 'string' ? modelContent.title : $text('embeds.models3d.search.result_title'));
  let provider = $derived(typeof modelContent.provider === 'string' ? modelContent.provider : '');
  let sourcePageUrl = $derived(typeof modelContent.source_page_url === 'string' ? modelContent.source_page_url : '');
  let previewUrl = $derived(
    typeof modelContent.preview_image_url === 'string'
      ? modelContent.preview_image_url
      : typeof modelContent.thumbnail_url === 'string'
        ? modelContent.thumbnail_url
        : ''
  );
  let imageUrl = $derived(proxyImage(previewUrl, 960));
  let failedImage = $state<string>();
  let ctaLabel = $derived(provider ? $text('embeds.models3d.search.open_on_provider', { values: { provider } }) : $text('embeds.models3d.search.open_result'));

</script>

<ResultEmbedFullscreen
  result={Object.fromEntries(["title", "provider", "source_page_url", "creator_name", "license", "files_count"].filter(key => modelContent[key] !== undefined).map(key => [key, modelContent[key]]))}
  appId="models3d"
  skillId="model_result"
  skillIconName="3dmodels"
  embedHeaderTitle={title}
  embedHeaderSubtitle={provider}
  showSkillIcon={true}
  {onClose}
  currentEmbedId={embedId}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
>
  {#snippet embedHeaderCta()}
    {#if sourcePageUrl}
      <EmbedHeaderCtaButton label={ctaLabel} href={sourcePageUrl} testId="models3d-open-provider-cta" />
    {/if}
  {/snippet}

  {#snippet summary()}{#if typeof modelContent.creator_name === 'string'}<ResultEmbedInfo icon="User" label="Creator" value={modelContent.creator_name}>{#snippet children()}{modelContent.creator_name}{/snippet}</ResultEmbedInfo>{/if}
{#if typeof modelContent.license === 'string'}<ResultEmbedInfo icon="Scale" label="License" value={modelContent.license}>{#snippet children()}{modelContent.license}{/snippet}</ResultEmbedInfo>{/if}
{#if typeof modelContent.files_count === 'number'}<ResultEmbedInfo icon="Files" label="Files" value={String(modelContent.files_count)}>{#snippet children()}{modelContent.files_count} catalogue files{/snippet}</ResultEmbedInfo>{/if}{/snippet}

  {#snippet media()}
    <div class="preview-area" data-testid="models3d-result-fullscreen">
      {#if imageUrl && failedImage !== imageUrl}
        <img src={imageUrl} alt={title} onerror={() => failedImage = imageUrl} />
      {:else}
        <div class="preview-placeholder" data-testid="models3d-preview-unavailable" role="status">
          <span class="placeholder-icon" aria-hidden="true"></span>
          <span>{$text('embeds.projects.references.preview_unavailable')}</span>
        </div>
      {/if}
    </div>
  {/snippet}
</ResultEmbedFullscreen>

<style>
  .preview-area {
    display: grid;
    place-items: center;
    width: 100%;
    min-height: 12rem;
    background: var(--color-grey-10);
  }

  .preview-area img {
    display: block;
    width: 100%;
    height: auto;
    max-height: 60vh;
    object-fit: contain;
  }

  .preview-placeholder {
    display: grid;
    justify-items: center;
    gap: var(--spacing-3);
    padding: var(--spacing-4);
    color: var(--color-font-secondary);
    text-align: center;
  }

  .placeholder-icon {
    width: 44px;
    height: 44px;
    background: currentColor;
    -webkit-mask: url('@openmates/ui/static/icons/3dmodels.svg') center / contain no-repeat;
    mask: url('@openmates/ui/static/icons/3dmodels.svg') center / contain no-repeat;
  }
</style>
