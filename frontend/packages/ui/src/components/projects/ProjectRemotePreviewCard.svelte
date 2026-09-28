<!-- Connected files stay virtual until explicitly imported. The shared embed preview owns the tile. -->
<script lang="ts">
  import { text } from '@repo/ui';
  import { formatLanguageName } from '../embeds/code/codeEmbedContent';
  import CodeEmbedPreview from '../embeds/code/CodeEmbedPreview.svelte';
  import FileEmbedPreview from '../embeds/file/FileEmbedPreview.svelte';
  import ImageEmbedPreview from '../embeds/images/ImageEmbedPreview.svelte';
  import UnifiedEmbedPreview from '../embeds/UnifiedEmbedPreview.svelte';
  import { classifyRemotePreviewPath, type VirtualRemoteFilePreview } from '../../services/projectRemoteSources';
  type FileKind = 'image' | 'pdf' | 'sheet' | 'document' | 'code' | 'file';

  let {
    preview,
    sourceLabel,
    previewOnly = false,
    imageSrc,
    onOpenFullscreen,
    onOpenFile,
  }: {
    preview: VirtualRemoteFilePreview;
    sourceLabel: string;
    previewOnly?: boolean;
    imageSrc?: string;
    onOpenFullscreen: () => void;
    onOpenFile?: () => void;
  } = $props();

  let content = $derived(preview.embed.content);
  let isTruncated = $derived(content.safety_flags.includes('truncated'));
  let isUnsupported = $derived(content.preview_policy === 'unsupported_binary');
  let inferredLanguage = $derived(classifyRemotePreviewPath(content.display_name).language);
  let fileKind = $derived.by((): FileKind => {
    const name = content.display_name.toLocaleLowerCase();
    if (/\.(png|jpe?g|gif|webp|avif|svg)$/.test(name)) return 'image';
    if (name.endsWith('.pdf')) return 'pdf';
    if (/\.(xlsx?|csv|ods)$/.test(name)) return 'sheet';
    if (/\.(md|mdx|txt|rst)$/.test(name)) return 'document';
    if (/\.(py|tsx?|jsx?|mjs|cjs|java|go|rs|rb|sh|css|html|json|ya?ml|toml|sql|swift|kt|xml|plist|entitlements|gradle|php|c|h|cpp|hpp)$/.test(name)
      || /^(dockerfile|makefile|gemfile|rakefile|justfile)$/.test(name)) return 'code';
    return 'file';
  });
  let useGenericFile = $derived(isUnsupported || !['code', 'document'].includes(fileKind));
  let kindLabel = $derived.by(() => {
    const name = content.display_name.toLowerCase();
    const extension = name.includes('.') ? name.split('.').pop() ?? '' : '';
    const fileTypeNames: Record<string, string> = {
      md: 'Markdown', mdx: 'Markdown', rst: 'reStructuredText', txt: 'Text',
      csv: 'CSV', xls: 'Excel spreadsheet', xlsx: 'Excel workbook', ods: 'OpenDocument spreadsheet',
      png: 'PNG image', jpg: 'JPEG image', jpeg: 'JPEG image', gif: 'GIF image',
      webp: 'WebP image', avif: 'AVIF image', svg: 'SVG image', pdf: 'PDF',
      plist: 'Property list', entitlements: 'Entitlements', gradle: 'Gradle',
    };
    if (fileTypeNames[extension]) return fileTypeNames[extension];
    const specificLanguage = formatLanguageName(inferredLanguage === 'text' ? content.language : inferredLanguage);
    if (specificLanguage) return specificLanguage;
    return ({ image: 'Image', pdf: 'PDF', sheet: 'Sheet', document: 'Document', code: 'Code', file: 'File' } as const)[fileKind];
  });
  let fileMimeType = $derived.by(() => {
    const name = content.display_name.toLocaleLowerCase();
    if (name.endsWith('.png')) return 'image/png';
    if (/\.jpe?g$/.test(name)) return 'image/jpeg';
    if (name.endsWith('.gif')) return 'image/gif';
    if (name.endsWith('.webp')) return 'image/webp';
    if (name.endsWith('.avif')) return 'image/avif';
    if (name.endsWith('.pdf')) return 'application/pdf';
    if (name.endsWith('.csv')) return 'text/csv';
    if (name.endsWith('.xlsx')) return 'Excel workbook';
    if (name.endsWith('.xls')) return 'Excel spreadsheet';
    if (name.endsWith('.ods')) return 'OpenDocument spreadsheet';
    return 'application/octet-stream';
  });
  let appId = $derived(({ image: 'images', pdf: 'pdf', sheet: 'sheets', document: 'docs', code: 'code', file: 'files' } as const)[fileKind]);
  let iconName = $derived(({ image: 'image', pdf: 'pdf', sheet: 'sheets', document: 'docs', code: 'coding', file: 'files' } as const)[fileKind]);
  let sizeLabel = $derived(content.size_bytes === undefined ? 'Size unavailable' : content.size_bytes < 1024
    ? `${content.size_bytes} B` : content.size_bytes < 1024 * 1024
      ? `${(content.size_bytes / 1024).toFixed(1)} KiB` : `${(content.size_bytes / (1024 * 1024)).toFixed(1)} MiB`);

</script>

<article class="remote-preview-card" class:preview-only={previewOnly} data-testid="project-remote-preview-card" data-remote-path={content.path} data-file-kind={fileKind} aria-label={`${content.display_name}, from connected source ${sourceLabel}`}>
  <span class="remote-cloud-badge" data-testid="project-remote-cloud-badge" role="img" aria-label="Stored remotely" title={`Stored on ${sourceLabel}`}></span>
  {#if imageSrc}
    <ImageEmbedPreview
      id={preview.embed.embed_id}
      filename={content.display_name}
      fileSize={content.size_bytes}
      src={imageSrc}
      status="finished"
      onFullscreen={onOpenFile ?? onOpenFullscreen}
    />
  {:else if useGenericFile}
    <FileEmbedPreview
      id={preview.embed.embed_id}
      filename={content.display_name}
      path={content.path}
      sizeBytes={content.size_bytes}
      mimeType={fileMimeType}
      status="finished"
      previewDescription="Open for file details and download"
      onFullscreen={onOpenFile ?? onOpenFullscreen}
    />
  {:else if content.snippet}
    <CodeEmbedPreview
      id={preview.embed.embed_id}
      language={inferredLanguage === 'text' ? content.language : inferredLanguage}
      filename={content.display_name}
      lineCount={content.line_count ?? 0}
      status="finished"
      codeContent={content.snippet}
      appId="code"
      skillId="code"
      skillIconName="coding"
      onFullscreen={onOpenFullscreen}
    />
  {:else}
    <UnifiedEmbedPreview
      id={preview.embed.embed_id}
      presentationOnly
      {appId}
      skillId="file"
      skillIconName={iconName}
      appIconName={iconName}
      status="finished"
      skillName={content.display_name}
      customStatusText={`${sizeLabel} · ${kindLabel}`}
      showSkillIcon={false}
      onFullscreen={onOpenFullscreen}
    >
      {#snippet details()}
        <div class="file-details" data-testid={isUnsupported ? 'project-remote-preview-unsupported' : 'project-remote-preview-pending'}>
          <span class="file-kind-label">{kindLabel}</span>
          <small>{sizeLabel}</small>
          <small>Open to render preview</small>
        </div>
      {/snippet}
    </UnifiedEmbedPreview>
  {/if}
  {#if isTruncated}
    <span class="preview-limit" data-testid="project-remote-preview-truncated" title={$text('projects.remote_preview_truncated')}>Preview limited</span>
  {/if}
</article>

<style>
  .remote-preview-card { position: relative; width: min(18.75rem, 100%); min-width: 0; }
  .remote-preview-card :global(.unified-embed-preview) { width: 100%; min-width: 0; }
  .remote-cloud-badge { position: absolute; inset-block-start: var(--spacing-3); inset-inline-end: var(--spacing-3); z-index: 2; width: 1.25rem; height: 1.25rem; border-radius: var(--radius-full); background: var(--color-grey-0); box-shadow: var(--shadow-sm); pointer-events: none; }
  .remote-cloud-badge::after { position: absolute; inset: 0.2rem; background: var(--color-font-secondary); content: ''; -webkit-mask: var(--icon-url-cloud) center / contain no-repeat; mask: var(--icon-url-cloud) center / contain no-repeat; }
  .file-details { display: grid; align-content: center; justify-items: start; gap: var(--spacing-2); height: 100%; padding: var(--spacing-8); overflow: hidden; }
  .file-details small { color: var(--color-font-secondary); }
  .file-kind-label { color: var(--color-font-secondary); font-size: var(--font-size-xs); font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em; }
  .preview-limit { position: absolute; inset-block-start: var(--spacing-3); inset-inline-start: var(--spacing-3); z-index: 2; padding: 2px 6px; border-radius: var(--radius-2); background: var(--color-grey-0); color: var(--color-font-secondary); font-size: var(--font-size-xs); }
</style>
