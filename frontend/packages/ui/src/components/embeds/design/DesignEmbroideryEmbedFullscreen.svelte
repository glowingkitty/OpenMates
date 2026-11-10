<!--
  frontend/packages/ui/src/components/embeds/design/DesignEmbroideryEmbedFullscreen.svelte

  Opened embroidery result: large stitch preview with a Stitches / Graphic
  switch, the numbers, the thread list in sewing order, notes, one download per
  machine format and "Change settings", which asks the assistant for a new
  conversion through the shared follow-up of ResultEmbedFullscreen. A failed
  result shows its reason only.
-->
<script lang="ts">
  import { onDestroy } from 'svelte';
  import { text } from '@repo/ui';
  import ResultEmbedFullscreen from '../ResultEmbedFullscreen.svelte';
  import ResultEmbedInfo from '../ResultEmbedInfo.svelte';
  import EmbroideryThreadList from './EmbroideryThreadList.svelte';
  import EmbroideryDownloads from './EmbroideryDownloads.svelte';
  import EmbroiderySettingsForm from './EmbroiderySettingsForm.svelte';
  import { fetchAndDecryptImage, getCachedImageUrl, createImageUrlOwner } from '../images/imageEmbedCrypto';
  import { hasMediaEncryptionMetadata } from '../../../services/encryption/mediaEncryption';
  import { svgToDataUrl } from '../code/progressiveSvg';
  import type { EmbedFullscreenRawData } from '../../../types/embedFullscreen';
  import {
    EMBROIDERY_FABRIC_COLOUR, EMBROIDERY_MIN_WIDTH_MM, errorTranslationKey, formatCount, formatDuration, formatHoop, formatSize,
    noteTranslationKey, readEmbroideryDesign, type EmbroideryFile, type EmbroiderySettings,
  } from './embroideryDesign';

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
    onNavigatePrevious, onNavigateNext, navigateDirection = null, showChatButton = false, onShowChat,
  }: Props = $props();

  const imageOwner = createImageUrlOwner();
  const design = $derived(readEmbroideryDesign(data.decodedContent, data.embedData?.status));
  const finished = $derived(design.status === 'finished');
  const skillName = $derived($text('app_skills.design.embroidery'));
  const title = $derived(design.title || skillName);
  const reason = $derived($text(errorTranslationKey(design.errorCode)));
  /** Safe file name stem: letters, digits and dashes only. */
  const downloadBaseName = $derived(
    design.title.normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase()
      .replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 48).replace(/-+$/, '') || 'embroidery-design',
  );
  const hoopLabel = $derived(formatHoop(design.hoop));

  let view = $state<'stitches' | 'graphic'>('stitches');
  let stitchUrl = $state<string>();
  let graphicUrl = $state<string>();
  let mediaError = $state(false);
  const shownUrl = $derived(view === 'graphic' ? graphicUrl : (design.previewImageUrl || stitchUrl));
  const showGraphicSwitch = $derived(!!design.preparedSvgText || !!design.files.prepared_svg);

  $effect(() => {
    const file = design.files.preview;
    if (!finished || design.previewImageUrl || stitchUrl || !file) return;
    void loadStitchPreview(file);
  });
  $effect(() => {
    if (design.preparedSvgText) { graphicUrl = svgToDataUrl(design.preparedSvgText); return; }
    const file = design.files.prepared_svg;
    if (view !== 'graphic' || graphicUrl || !file) return;
    void loadPreparedSvg(file);
  });

  onDestroy(imageOwner.destroy);

  function canDecrypt(file: EmbroideryFile): boolean {
    return !!design.aesKey && hasMediaEncryptionMetadata(file, file.aes_nonce ?? design.aesNonce);
  }

  async function loadStitchPreview(file: EmbroideryFile) {
    if (!canDecrypt(file)) return;
    try {
      await fetchAndDecryptImage(design.s3BaseUrl, file.s3_key, design.aesKey, file.aes_nonce ?? design.aesNonce, file);
      stitchUrl = getCachedImageUrl(file.s3_key);
      imageOwner.retain(file.s3_key);
    } catch (caught) {
      console.warn('[DesignEmbroideryEmbedFullscreen] stitch preview decrypt failed:', caught);
      mediaError = true;
    }
  }

  async function loadPreparedSvg(file: EmbroideryFile) {
    if (!canDecrypt(file)) return;
    try {
      const blob = await fetchAndDecryptImage(design.s3BaseUrl, file.s3_key, design.aesKey, file.aes_nonce ?? design.aesNonce, file);
      graphicUrl = svgToDataUrl(await blob.text());
    } catch (caught) {
      console.warn('[DesignEmbroideryEmbedFullscreen] prepared graphic decrypt failed:', caught);
      mediaError = true;
    }
  }

  /** The downloads section; the top-bar download button saves all formats through it. */
  let downloads = $state<ReturnType<typeof EmbroideryDownloads> | null>(null);

  function requestText(settings: EmbroiderySettings): string {
    return $text('embeds.design.embroidery.apply_request', {
      values: {
        width: settings.widthMm,
        hoop: settings.hoop === 'none' ? $text('embeds.design.embroidery.hoop_none') : formatHoop(settings.hoop),
        fabric: $text(`embeds.design.embroidery.fabric_${settings.fabric}`).toLocaleLowerCase(),
      },
    });
  }

  /** Visible result metadata only: never keys, nonces or storage paths. */
  const followupResult = $derived({
    title: design.title, width_mm: design.widthMm, height_mm: design.heightMm,
    stitch_count: design.stitchCount, thread_changes: design.threadChanges,
    estimated_minutes: design.estimatedMinutes, hoop: design.hoop, fits_hoop: design.fitsHoop,
    fabric: design.fabric, source_embed_ref: design.sourceEmbedRef || undefined,
  });
</script>

<ResultEmbedFullscreen
  result={followupResult}
  appId="design"
  skillId="embroidery"
  skillIconName="embroidery"
  embedHeaderTitle={title}
  embedHeaderSubtitle={finished ? formatSize(design) : skillName}
  showSkillIcon={true}
  {onClose}
  onDownload={finished ? () => { void downloads?.download('all'); } : undefined}
  currentEmbedId={embedId}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
  {navigateDirection}
  {showChatButton}
  {onShowChat}
>
  {#snippet summary()}
    {#if finished}
      {#if design.widthMm !== null}
        <ResultEmbedInfo icon="ruler" label={$text('embeds.design.embroidery.size')} value={formatSize(design)} testId="design-embroidery-size" />
      {/if}
      {#if design.stitchCount !== null}
        <ResultEmbedInfo icon="grip" label={$text('embeds.design.embroidery.stitches')} value={formatCount(design.stitchCount)} testId="design-embroidery-stitch-count" />
      {/if}
      {#if design.threadChanges !== null}
        <ResultEmbedInfo icon="repeat" label={$text('embeds.design.embroidery.thread_changes')} value={String(design.threadChanges)} testId="design-embroidery-thread-changes" />
      {/if}
      {#if design.estimatedMinutes !== null}
        <ResultEmbedInfo icon="timer" label={$text('embeds.design.embroidery.sewing_time')} value={formatDuration(design.estimatedMinutes)} testId="design-embroidery-time" />
      {/if}
      {#if design.fitsHoop !== 'not_checked' && hoopLabel}
        <ResultEmbedInfo
          icon="frame"
          label={design.fitsHoop === 'yes' ? $text('embeds.design.embroidery.fits_hoop', { values: { hoop: hoopLabel } }) : $text('embeds.design.embroidery.too_large_for_hoop', { values: { hoop: hoopLabel } })}
          value={design.fitsHoop === 'yes' ? $text('embeds.design.embroidery.fits_hoop', { values: { hoop: hoopLabel } }) : $text('embeds.design.embroidery.too_large_for_hoop', { values: { hoop: hoopLabel } })}
          state={design.fitsHoop}
          testId="design-embroidery-hoop-fit"
        />
      {/if}
      {#if design.fabric}
        <ResultEmbedInfo icon="shirt" label={$text('embeds.design.embroidery.fabric')} value={$text(`embeds.design.embroidery.fabric_${design.fabric}`)} testId="design-embroidery-fabric-info" />
      {/if}
    {/if}
  {/snippet}
  {#snippet media()}
    <div class="embroidery-media" data-testid="design-embroidery-fullscreen" data-status={design.status}>
      {#if design.status === 'error'}
        <div class="reason" role="alert" data-testid="design-embroidery-error">
          <strong>{$text('embeds.design.embroidery.failed')}</strong>
          <span>{reason}</span>
        </div>
      {:else if design.status === 'processing'}
        <div class="reason" role="status" data-testid="design-embroidery-converting">{$text('embeds.design.embroidery.converting')}</div>
      {:else}
        {#if showGraphicSwitch}
          <div class="switch" role="group" aria-label={$text('embeds.design.embroidery.view')}>
            <button type="button" aria-pressed={view === 'stitches'} data-testid="design-embroidery-view-stitches" onclick={() => (view = 'stitches')}>
              {$text('embeds.design.embroidery.view_stitches')}
            </button>
            <button type="button" aria-pressed={view === 'graphic'} data-testid="design-embroidery-view-graphic" onclick={() => (view = 'graphic')}>
              {$text('embeds.design.embroidery.view_graphic')}
            </button>
          </div>
        {/if}
        {#if shownUrl}
          <div class="stage" class:fabric={view === 'stitches'} style:--embroidery-fabric={EMBROIDERY_FABRIC_COLOUR}>
            <img src={shownUrl} alt={title} class="result-primary-media stitch-image" data-testid="design-embroidery-image" data-view={view} />
          </div>
        {:else if mediaError}
          <p class="status" role="status">{$text('embeds.design.embroidery.preview_unavailable')}</p>
        {:else}
          <div class="stitch-image loading" aria-hidden="true"></div>
        {/if}
      {/if}
    </div>
  {/snippet}
  {#snippet detailContent({ requestFollowup, submitting })}
    {#if finished}
      <div class="embroidery-details">
        <EmbroideryDownloads bind:this={downloads} {design} baseName={downloadBaseName} />
        <EmbroideryThreadList threads={design.threads} />
        {#if design.notes.length > 0}
          <section class="notes" data-testid="design-embroidery-notes">
            <h4>{$text('embeds.design.embroidery.notes')}</h4>
            <ul>
              {#each design.notes as note, index (index)}
                {@const key = noteTranslationKey(note.code)}
                <li data-testid="design-embroidery-note">{key ? $text(key, { values: { count: note.count ?? 0 } }) : note.text}</li>
              {/each}
            </ul>
          </section>
        {/if}
        {#if design.reworked}
          <p class="hint" data-testid="design-embroidery-reworked">{$text('embeds.design.embroidery.reworked_hint')}</p>
        {/if}
        <EmbroiderySettingsForm
          widthMm={design.widthMm ?? EMBROIDERY_MIN_WIDTH_MM}
          hoop={design.hoop}
          fabric={design.fabric ?? 'normal'}
          {submitting}
          onApply={(settings) => { void requestFollowup(requestText(settings)); }}
        />
      </div>
    {/if}
  {/snippet}
</ResultEmbedFullscreen>

<style>
  .embroidery-media { width: 100%; display: flex; flex-direction: column; align-items: center; gap: var(--spacing-5); container-type: inline-size; }
  .switch { display: inline-flex; padding: var(--spacing-1); gap: var(--spacing-1); border-radius: var(--radius-8); background: var(--color-grey-0); }
  .switch button {
    min-height: 44px;
    padding: 0 var(--spacing-8);
    border: 0;
    border-radius: var(--radius-8);
    background: transparent;
    color: var(--color-font-secondary);
    font: inherit;
    cursor: pointer;
  }
  .switch button[aria-pressed="true"] { background: var(--color-button-primary); color: var(--color-font-button); }
  .switch button:focus-visible { outline: 2px solid var(--color-button-primary); outline-offset: 2px; }
  .stage { width: 100%; border-radius: var(--radius-6); overflow: hidden; }
  .stage.fabric { background: var(--embroidery-fabric); }
  .stitch-image { display: block; width: 100%; height: var(--result-media-height, 20rem); object-fit: contain; border-radius: var(--radius-6); background: var(--color-media-letterbox); }
  .stage.fabric .stitch-image { background: transparent; }
    .reason { display: flex; flex-direction: column; gap: var(--spacing-2); width: min(100%, 34rem); box-sizing: border-box; padding: var(--spacing-8); border-radius: var(--radius-6); background: var(--color-grey-0); color: var(--color-font-primary); text-align: center; }
  .status { margin: 0; color: var(--color-font-secondary); }
  .embroidery-details { width: 100%; display: flex; flex-direction: column; gap: var(--spacing-10); }
  h4 { margin: 0 0 var(--spacing-4); font-size: var(--font-size-small); color: var(--color-font-secondary); }
  .notes ul { margin: 0; padding-inline-start: var(--spacing-10); display: flex; flex-direction: column; gap: var(--spacing-2); font-size: var(--font-size-small); }
  .hint { margin: 0; font-size: var(--font-size-small); color: var(--color-font-secondary); }
</style>
