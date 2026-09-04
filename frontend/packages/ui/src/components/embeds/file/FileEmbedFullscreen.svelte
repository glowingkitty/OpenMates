<!--
  frontend/packages/ui/src/components/embeds/file/FileEmbedFullscreen.svelte

  Non-executable fullscreen fallback for captured Code Run artifacts.
  The viewer displays encrypted child metadata and offers the short-lived download
  URL when available. It never previews, parses, or executes arbitrary file content.
-->

<script lang="ts">
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import { formatCodeRunArtifactSize, isCodeRunArtifactDownloadAvailable } from '../../../services/codeRunArtifacts';
  import type { EmbedFullscreenRawData } from '../../../types/embedFullscreen';

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

  let {
    data,
    onClose,
    embedId,
    hasPreviousEmbed = false,
    hasNextEmbed = false,
    onNavigatePrevious,
    onNavigateNext,
    navigateDirection,
    showChatButton = false,
    onShowChat,
  }: Props = $props();

  let content = $derived(data.decodedContent);
  let path = $derived(
    typeof content.normalized_path === 'string' ? content.normalized_path
      : typeof content.path === 'string' ? content.path
        : typeof content.filename === 'string' ? content.filename
          : 'File'
  );
  let filename = $derived(typeof content.filename === 'string' ? content.filename : path.split('/').pop() || path);
  let mimeType = $derived(typeof content.mime_type === 'string' ? content.mime_type : 'application/octet-stream');
  let sizeBytes = $derived(typeof content.size_bytes === 'number' ? content.size_bytes : undefined);
  let downloadUrl = $derived(typeof content.download_url === 'string' ? content.download_url : undefined);
  let downloadExpiresAt = $derived(typeof content.download_expires_at === 'number' ? content.download_expires_at : undefined);
  let downloadHref = $derived(isCodeRunArtifactDownloadAvailable({
    path,
    download_url: downloadUrl,
    download_expires_at: downloadExpiresAt,
  }) ? downloadUrl : null);
  let subtitle = $derived([mimeType, formatCodeRunArtifactSize(sizeBytes)].filter(Boolean).join(' · '));
</script>

<UnifiedEmbedFullscreen
  testId="file-embed-fullscreen"
  appId="files"
  skillId="file"
  appIconName="files"
  embedHeaderTitle={filename}
  embedHeaderSubtitle={subtitle}
  skillIconName="files"
  showSkillIcon={false}
  {onClose}
  currentEmbedId={embedId}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
  {navigateDirection}
  {showChatButton}
  {onShowChat}
  {downloadHref}
  downloadFilename={filename}
>
  {#snippet content()}
    <section class="file-fullscreen-content">
      <span class="file-fullscreen-icon icon files" aria-hidden="true"></span>
      <div class="file-fullscreen-copy">
        <h2>{path}</h2>
        <p>{subtitle}</p>
        {#if !downloadHref}
          <p class="file-download-unavailable">Download link unavailable or expired.</p>
        {/if}
      </div>
    </section>
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  .file-fullscreen-content {
    display: flex;
    width: min(44rem, calc(100% - var(--spacing-16)));
    min-width: 0;
    align-items: center;
    gap: var(--spacing-12);
    margin: var(--spacing-16) auto;
    padding: var(--spacing-16);
    box-sizing: border-box;
    border: 1px solid var(--color-grey-25);
    border-radius: var(--radius-8);
    background: var(--color-grey-10);
    color: var(--color-font-primary);
  }

  .file-fullscreen-icon {
    width: 4rem;
    height: 4rem;
    flex: 0 0 auto;
  }

  .file-fullscreen-copy {
    min-width: 0;
  }

  .file-fullscreen-copy h2,
  .file-fullscreen-copy p {
    margin: 0;
  }

  .file-fullscreen-copy h2 {
    overflow-wrap: anywhere;
    font-size: var(--font-size-h4);
  }

  .file-fullscreen-copy p {
    margin-top: var(--spacing-4);
    color: var(--color-font-secondary);
    font-size: var(--font-size-small);
  }

  .file-download-unavailable {
    color: var(--color-warning);
  }

  @container embed-fullscreen (max-width: 730px) {
    .file-fullscreen-content {
      flex-direction: column;
      align-items: flex-start;
    }
  }
</style>
