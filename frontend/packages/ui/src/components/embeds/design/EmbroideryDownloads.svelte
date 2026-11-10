<!--
  frontend/packages/ui/src/components/embeds/design/EmbroideryDownloads.svelte

  One download per machine format. Each file is fetched encrypted from storage
  and decrypted in the browser with the embed's own key material (like the
  stitch preview), then saved from a same-origin object URL so the browser
  honours the suggested "<name>.<format>". Component previews carry inline text
  (`previewDownloadText`) and need no network. Each button keeps its own
  loading and error state.
-->
<script lang="ts">
  import { text } from '@repo/ui';
  import { fetchAndDecryptImage } from '../images/imageEmbedCrypto';
  import { hasMediaEncryptionMetadata } from '../../../services/encryption/mediaEncryption';
  import { EMBROIDERY_FORMATS, type EmbroideryDesign, type EmbroideryFormat } from './embroideryDesign';

  interface Props {
    /** Per-format file descriptors and key material of the result. */
    design: Pick<EmbroideryDesign, 'files' | 's3BaseUrl' | 'aesKey' | 'aesNonce' | 'previewDownloadText'>;
    /** File name without extension, used as the browser's suggested name. */
    baseName: string;
  }
  let { design, baseName }: Props = $props();

  let loading = $state<Partial<Record<EmbroideryFormat, boolean>>>({});
  let failed = $state<Partial<Record<EmbroideryFormat, boolean>>>({});

  async function readBytes(format: EmbroideryFormat): Promise<Blob> {
    if (design.previewDownloadText) return new Blob([design.previewDownloadText]);
    const file = design.files[format];
    const nonce = file?.aes_nonce ?? design.aesNonce;
    if (!file || !design.aesKey || !hasMediaEncryptionMetadata(file, nonce)) {
      throw new Error(`Embroidery file ${format} is not available`);
    }
    // The helper labels the bytes as an image; only the bytes are used here.
    const decrypted = await fetchAndDecryptImage(design.s3BaseUrl, file.s3_key, design.aesKey, nonce, file);
    return new Blob([await decrypted.arrayBuffer()], { type: 'application/octet-stream' });
  }

  async function download(format: EmbroideryFormat) {
    if (loading[format]) return;
    loading = { ...loading, [format]: true };
    failed = { ...failed, [format]: false };
    try {
      const url = URL.createObjectURL(await readBytes(format));
      const link = document.createElement('a');
      link.href = url;
      link.download = `${baseName || 'embroidery'}.${format}`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 0);
    } catch (caught) {
      console.warn('[EmbroideryDownloads] download failed:', format, caught);
      failed = { ...failed, [format]: true };
    } finally {
      loading = { ...loading, [format]: false };
    }
  }
</script>

<section class="downloads" data-testid="design-embroidery-downloads">
  <h4>{$text('embeds.design.embroidery.download')}</h4>
  <div class="buttons">
    {#each EMBROIDERY_FORMATS as format (format)}
      <div class="item">
        <button
          type="button"
          class="download"
          class:failed={failed[format]}
          data-testid={`design-embroidery-download-${format}`}
          data-state={loading[format] ? 'loading' : failed[format] ? 'error' : 'idle'}
          disabled={loading[format]}
          aria-busy={loading[format] ? 'true' : undefined}
          onclick={() => download(format)}
        >
          {format.toUpperCase()}
        </button>
        {#if failed[format]}
          <span class="error" role="alert" data-testid={`design-embroidery-download-${format}-error`}>
            {$text('embeds.action_failed')}
          </span>
        {/if}
      </div>
    {/each}
  </div>
</section>

<style>
  .downloads { width: 100%; }
  h4 { margin: 0 0 var(--spacing-4); font-size: var(--font-size-small); color: var(--color-font-secondary); }
  .buttons { display: grid; grid-template-columns: repeat(auto-fit, minmax(5rem, 1fr)); gap: var(--spacing-4); }
  .item { display: flex; flex-direction: column; gap: var(--spacing-2); min-width: 0; }
  .download {
    min-height: 44px;
    border: 0;
    border-radius: var(--radius-4);
    background: var(--color-button-primary);
    color: var(--color-font-button);
    font: inherit;
    font-weight: 650;
    cursor: pointer;
    transition: opacity var(--duration-fast) var(--easing-default);
  }
  .download:hover:not(:disabled) { opacity: 0.9; }
  .download:disabled { opacity: 0.6; cursor: progress; }
  .download:focus-visible { outline: 2px solid var(--color-button-primary); outline-offset: 3px; }
  .download.failed { background: var(--color-error); }
  .error { font-size: var(--font-size-xxs); color: var(--color-error); text-align: center; }
</style>
