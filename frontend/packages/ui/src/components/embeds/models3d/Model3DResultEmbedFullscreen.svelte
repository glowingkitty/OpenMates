<!--
  frontend/packages/ui/src/components/embeds/models3d/Model3DResultEmbedFullscreen.svelte

  Fullscreen metadata view for a preview-only 3D model search result. It links
  to the source provider and intentionally does not fetch model files.
-->

<script lang="ts">
  import { text } from '@repo/ui';
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
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
  let ctaLabel = $derived(provider ? $text('embeds.models3d.search.open_on_provider', { values: { provider } }) : $text('embeds.models3d.search.open_result'));

  function openProvider() {
    if (!sourcePageUrl) return;
    window.open(sourcePageUrl, '_blank', 'noopener,noreferrer');
  }
</script>

<UnifiedEmbedFullscreen
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
      <EmbedHeaderCtaButton label={ctaLabel} onclick={openProvider} testId="models3d-open-provider-cta" />
    {/if}
  {/snippet}

  {#snippet content()}
    <div class="model-result-fullscreen" data-testid="models3d-result-fullscreen">
      <div class="preview-area">
        {#if imageUrl}
          <img src={imageUrl} alt={title} />
        {:else}
          <span class="clickable-icon icon_3dmodels placeholder-icon"></span>
        {/if}
      </div>
      <section class="metadata">
        <h2>{title}</h2>
        {#if typeof modelContent.creator_name === 'string'}<p>{modelContent.creator_name}</p>{/if}
        {#if typeof modelContent.license === 'string'}<p>{modelContent.license}</p>{/if}
        {#if typeof modelContent.files_count === 'number'}<p>{$text('embeds.models3d.search.files_count', { values: { count: modelContent.files_count } })}</p>{/if}
        {#if sourcePageUrl}
          <a href={sourcePageUrl} target="_blank" rel="noopener noreferrer" data-testid="models3d-open-provider-cta-inline">{ctaLabel}</a>
        {/if}
      </section>
    </div>
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  .model-result-fullscreen {
    display: grid;
    grid-template-columns: minmax(0, 1.3fr) minmax(260px, 0.7fr);
    gap: var(--spacing-12);
    width: 100%;
    padding: var(--spacing-12);
  }

  .preview-area {
    display: grid;
    place-items: center;
    min-height: 360px;
    border-radius: 24px;
    background: var(--color-grey-10);
    overflow: hidden;
  }

  img {
    width: 100%;
    height: 100%;
    max-height: 70vh;
    object-fit: contain;
  }

  .placeholder-icon {
    width: 44px;
    height: 44px;
    background: var(--color-grey-40) !important;
  }

  .metadata {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-5);
    color: var(--color-font-primary);
  }

  h2 {
    margin: 0;
    font-size: var(--font-size-lg);
  }

  p { margin: 0; color: var(--color-font-secondary); }

  a {
    align-self: flex-start;
    padding: 9px 13px;
    border-radius: var(--radius-8);
    background: var(--color-button-primary);
    color: var(--color-font-button);
    font-weight: 650;
    text-decoration: none;
  }

  @media (max-width: 760px) {
    .model-result-fullscreen { grid-template-columns: 1fr; }
  }
</style>
