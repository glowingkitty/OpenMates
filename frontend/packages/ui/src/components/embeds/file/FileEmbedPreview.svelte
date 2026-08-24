<!--
  frontend/packages/ui/src/components/embeds/file/FileEmbedPreview.svelte

  Safe preview for generic captured files that lack a compatible native renderer.
  It deliberately exposes only metadata and download availability; file content is
  never interpreted or executed. Fullscreen behavior uses the shared embed shell.
-->

<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { formatCodeRunArtifactSize } from '../../../services/codeRunArtifacts';

  interface Props {
    id: string;
    filename?: string;
    path?: string;
    mimeType?: string;
    sizeBytes?: number;
    status: 'processing' | 'finished' | 'error' | 'cancelled';
    isMobile?: boolean;
    onFullscreen: () => void;
  }

  let {
    id,
    filename,
    path,
    mimeType,
    sizeBytes,
    status,
    isMobile = false,
    onFullscreen,
  }: Props = $props();

  let displayName = $derived(filename || path || 'File');
  let metadata = $derived([mimeType, formatCodeRunArtifactSize(sizeBytes)].filter(Boolean).join(' · '));
</script>

<UnifiedEmbedPreview
  {id}
  appId="files"
  skillId="file"
  skillIconName="files"
  appIconName="files"
  {status}
  skillName={displayName}
  {isMobile}
  {onFullscreen}
  showSkillIcon={false}
  customStatusText={metadata}
>
  {#snippet details()}
    <div class="file-preview-details">
      <span class="file-preview-icon icon files" aria-hidden="true"></span>
      <span class="file-preview-name">{displayName}</span>
      {#if metadata}<span class="file-preview-meta">{metadata}</span>{/if}
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .file-preview-details {
    display: flex;
    height: 100%;
    min-width: 0;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: var(--spacing-4);
    padding: var(--spacing-8);
    box-sizing: border-box;
    color: var(--color-font-primary);
    text-align: center;
  }

  .file-preview-icon {
    width: 3rem;
    height: 3rem;
    flex: 0 0 auto;
  }

  .file-preview-name {
    max-width: 100%;
    overflow: hidden;
    font-size: var(--font-size-p);
    font-weight: 700;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .file-preview-meta {
    color: var(--color-font-secondary);
    font-size: var(--font-size-xs);
  }
</style>
