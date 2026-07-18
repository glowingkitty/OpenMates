<!--
  frontend/packages/ui/src/components/embeds/design/DesignIconResultEmbedFullscreen.svelte

  Fullscreen detail view for one SVG icon result from the Design app.
  Shows the icon, collection, license, and stable metadata from the saved embed.

  Architecture: docs/architecture/embeds.md
-->

<script lang="ts">
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import EmbedHeaderCtaButton from '../EmbedHeaderCtaButton.svelte';
  import { getApiEndpoint } from '../../../config/api';
  import type { EmbedFullscreenRawData } from '../../../types/embedFullscreen';
  import { copyToClipboard } from '../../../utils/clipboardUtils';
  import { notificationStore } from '../../../stores/notificationStore';

  interface Props {
    data?: EmbedFullscreenRawData;
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

  function asString(value: unknown): string {
    return typeof value === 'string' ? value : '';
  }

  function asNumber(value: unknown): number | undefined {
    return typeof value === 'number' && Number.isFinite(value) && value > 0 ? value : undefined;
  }

  function applyIconColor(svg: string, color: string): string {
    const withCurrentColor = svg.replace(/\bcurrentColor\b/g, color);
    return withCurrentColor.replace(/<svg\b([^>]*)>/i, (match, attrs: string) => {
      if (/\scolor\s*=/.test(attrs)) {
        return match.replace(/\scolor\s*=\s*(['"])[^'"]*\1/i, ` color="${color}"`);
      }
      return `<svg${attrs} color="${color}">`;
    });
  }

  function filenameFor(extension: 'svg' | 'png'): string {
    const base = (asString(content.icon_id) || title || 'icon')
      .toLowerCase()
      .replace(/[^a-z0-9._-]+/g, '-')
      .replace(/^-+|-+$/g, '') || 'icon';
    return `${base}.${extension}`;
  }

  function downloadBlob(blob: Blob, filename: string): void {
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = filename;
    document.body.appendChild(anchor);
    anchor.click();
    document.body.removeChild(anchor);
    URL.revokeObjectURL(url);
  }

  async function fetchPreparedSvg(): Promise<string> {
    if (!iconSrc) throw new Error('Icon SVG path is unavailable');
    const response = await fetch(iconSrc, { credentials: 'include' });
    if (!response.ok) {
      throw new Error(`Icon SVG request failed with status ${response.status}`);
    }
    const svg = await response.text();
    return canRecolor ? applyIconColor(svg, color) : svg;
  }

  async function handleCopySvg(): Promise<void> {
    try {
      const svg = await fetchPreparedSvg();
      const result = await copyToClipboard(svg);
      if (!result.success) throw new Error(result.error || 'Copy failed');
      notificationStore.success('SVG copied to clipboard');
    } catch (error) {
      console.error('[DesignIconResultEmbedFullscreen] Failed to copy SVG:', error);
      notificationStore.error('Failed to copy SVG');
    }
  }

  async function handleDownloadSvg(): Promise<void> {
    try {
      const svg = await fetchPreparedSvg();
      downloadBlob(new Blob([svg], { type: 'image/svg+xml' }), filenameFor('svg'));
      notificationStore.success('SVG downloaded');
    } catch (error) {
      console.error('[DesignIconResultEmbedFullscreen] Failed to download SVG:', error);
      notificationStore.error('Failed to download SVG');
    }
  }

  function renderPng(svg: string, size: number): Promise<Blob> {
    return new Promise((resolve, reject) => {
      const svgUrl = URL.createObjectURL(new Blob([svg], { type: 'image/svg+xml' }));
      const image = new Image();
      image.onload = () => {
        try {
          const canvas = document.createElement('canvas');
          canvas.width = size;
          canvas.height = size;
          const context = canvas.getContext('2d');
          if (!context) throw new Error('Canvas rendering is unavailable');
          context.drawImage(image, 0, 0, size, size);
          canvas.toBlob((blob) => {
            URL.revokeObjectURL(svgUrl);
            if (blob) resolve(blob);
            else reject(new Error('PNG export failed'));
          }, 'image/png');
        } catch (error) {
          URL.revokeObjectURL(svgUrl);
          reject(error);
        }
      };
      image.onerror = () => {
        URL.revokeObjectURL(svgUrl);
        reject(new Error('SVG image failed to load for PNG export'));
      };
      image.src = svgUrl;
    });
  }

  async function handleDownloadPng(): Promise<void> {
    try {
      const svg = await fetchPreparedSvg();
      const blob = await renderPng(svg, pngSize);
      downloadBlob(blob, filenameFor('png'));
      notificationStore.success('PNG downloaded');
    } catch (error) {
      console.error('[DesignIconResultEmbedFullscreen] Failed to download PNG:', error);
      notificationStore.error('Failed to download PNG');
    }
  }

  let content = $derived({
    ...(data?.embedData ?? {}),
    ...(data?.attrs ?? {}),
    ...(data?.decodedContent ?? {}),
  });
  let title = $derived(asString(content.display_name) || asString(content.name) || asString(content.icon_id) || 'Icon');
  let collection = $derived(asString(content.collection_name) || asString(content.prefix));
  let license = $derived(asString(content.license_title) || asString(content.license_spdx));
  let licenseUrl = $derived(asString(content.license_url));
  let author = $derived(asString(content.author_name));
  let width = $derived(asNumber(content.width));
  let height = $derived(asNumber(content.height));
  let isPalette = $derived(content.palette === true);
  let svgPath = $derived(asString(content.svg_path));
  let iconSrc = $derived(svgPath ? getApiEndpoint(svgPath) : '');
  let color = $state('#111827');
  let pngSize = $state(256);
  let canRecolor = $derived(!isPalette);
</script>

<UnifiedEmbedFullscreen
  appId="design"
  skillId="search_icons"
  skillIconName="search"
  embedHeaderTitle={title}
  embedHeaderSubtitle={collection}
  showSkillIcon={true}
  {onClose}
  currentEmbedId={embedId}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
  onCopy={iconSrc ? handleCopySvg : undefined}
  onDownload={iconSrc ? handleDownloadPng : undefined}
>
  {#snippet embedHeaderCta()}
    {#if licenseUrl}
      <EmbedHeaderCtaButton label={license || 'View license'} href={licenseUrl} testId="design-icon-license-cta" />
    {/if}
  {/snippet}

  {#snippet content()}
    <div class="icon-result-fullscreen" data-testid="design-icon-result-fullscreen">
      <div class="icon-stage">
        {#if iconSrc}
          <img src={iconSrc} alt={title} />
        {:else}
          <span class="clickable-icon icon_design placeholder-icon"></span>
        {/if}
      </div>

      <section class="metadata">
        <h2>{title}</h2>
        {#if collection}<p>{collection}</p>{/if}
        {#if license}<p>{license}</p>{/if}
        {#if author}<p>{author}</p>{/if}
        {#if width && height}<p>{width} x {height}</p>{/if}
        {#if isPalette}<p>Palette icon. Recoloring is disabled to preserve the original colors.</p>{/if}
        {#if svgPath}<code>{svgPath}</code>{/if}

        <div class="export-controls" aria-label="Icon export controls">
          <label>
            <span>Color</span>
            <input type="color" bind:value={color} disabled={!canRecolor} data-testid="design-icon-color-input" />
          </label>
          <label>
            <span>PNG size</span>
            <input type="number" min="16" max="4096" step="16" bind:value={pngSize} data-testid="design-icon-png-size-input" />
          </label>
        </div>

        <div class="export-actions">
          <button type="button" onclick={handleCopySvg} disabled={!iconSrc}>Copy SVG</button>
          <button type="button" onclick={handleDownloadSvg} disabled={!iconSrc}>Download SVG</button>
          <button type="button" onclick={handleDownloadPng} disabled={!iconSrc}>Download PNG</button>
        </div>
      </section>
    </div>
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  .icon-result-fullscreen {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(260px, 360px);
    gap: var(--spacing-12);
    width: 100%;
    padding: var(--spacing-12);
  }

  .icon-stage {
    display: grid;
    place-items: center;
    min-height: 360px;
    border-radius: 24px;
    background: var(--color-grey-8);
    border: 1px solid var(--color-grey-20);
  }

  .icon-stage img {
    width: min(220px, 45vw);
    height: min(220px, 45vw);
    object-fit: contain;
  }

  .placeholder-icon {
    width: 56px;
    height: 56px;
    background: var(--color-grey-50) !important;
  }

  .metadata {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-4);
    color: var(--color-font-primary);
  }

  h2 {
    margin: 0;
    font-size: var(--font-size-lg);
  }

  p {
    margin: 0;
    color: var(--color-font-secondary);
  }

  code {
    padding: var(--spacing-3);
    border-radius: var(--radius-4);
    background: var(--color-grey-8);
    color: var(--color-font-secondary);
    word-break: break-all;
  }

  .export-controls,
  .export-actions {
    display: flex;
    flex-wrap: wrap;
    gap: var(--spacing-4);
    margin-top: var(--spacing-4);
  }

  label {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-2);
    color: var(--color-font-secondary);
    font-size: var(--font-size-small);
  }

  input[type='number'] {
    width: 110px;
    padding: var(--spacing-3);
    border: 1px solid var(--color-grey-30);
    border-radius: var(--radius-4);
    background: var(--color-grey-0);
    color: var(--color-font-primary);
  }

  input[type='color'] {
    width: 56px;
    height: 40px;
    padding: 0;
    border: 1px solid var(--color-grey-30);
    border-radius: var(--radius-4);
    background: transparent;
  }

  button {
    border: 1px solid var(--color-grey-30);
    border-radius: var(--radius-4);
    padding: var(--spacing-3) var(--spacing-5);
    background: var(--color-grey-8);
    color: var(--color-font-primary);
    cursor: pointer;
    font: inherit;
  }

  button:hover:not(:disabled) {
    background: var(--color-grey-15);
  }

  button:disabled,
  input:disabled {
    cursor: not-allowed;
    opacity: 0.55;
  }

  @media (max-width: 760px) {
    .icon-result-fullscreen {
      grid-template-columns: 1fr;
      padding: var(--spacing-6);
    }
  }
</style>
