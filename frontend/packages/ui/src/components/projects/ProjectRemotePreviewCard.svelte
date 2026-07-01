<!--
  ProjectRemotePreviewCard.svelte
  Renders a virtual remote-source file preview inside Projects.
  Remote files stay virtual until the user explicitly uploads the selected file
  to OpenMates, so this component never persists embeds by itself.
-->

<script lang="ts">
  import CodeEmbedPreview from '../embeds/code/CodeEmbedPreview.svelte';
  import type { VirtualRemoteFilePreview } from '../../services/projectRemoteSources';

  let {
    preview,
    sourceLabel,
    canUpload,
    isUploading,
    onOpenFullscreen,
    onUpload,
  }: {
    preview: VirtualRemoteFilePreview;
    sourceLabel: string;
    canUpload: boolean;
    isUploading: boolean;
    onOpenFullscreen: () => void;
    onUpload: () => void;
  } = $props();

  let content = $derived(preview.embed.content);
  let sizeLabel = $derived(content.size_bytes !== undefined ? `${content.size_bytes.toLocaleString()} bytes` : 'Virtual preview');
</script>

<article class="remote-preview-card" data-testid="project-remote-preview-card" data-remote-path={content.path}>
  <div class="remote-preview-shell">
    <CodeEmbedPreview
      id={preview.embed.embed_id}
      language={content.language}
      filename={content.display_name}
      lineCount={content.line_count ?? 0}
      status="finished"
      codeContent={content.snippet}
      appId="code"
      skillId="code"
      skillIconName="coding"
      onFullscreen={onOpenFullscreen}
    />
  </div>
  <div class="remote-preview-meta">
    <div>
      <span class="remote-source-label">{sourceLabel}</span>
      <strong>{content.display_name}</strong>
      <small>{content.path} · {sizeLabel}</small>
    </div>
    <div class="remote-preview-actions">
      <button type="button" data-testid="project-remote-preview-open" onclick={onOpenFullscreen}>
        Open preview
      </button>
      <button
        type="button"
        data-testid="project-remote-preview-upload"
        disabled={!canUpload || isUploading}
        title={canUpload ? 'Upload selected remote file to OpenMates' : 'Full selected file content is required before upload'}
        onclick={onUpload}
      >
        Upload to OpenMates
      </button>
    </div>
  </div>
</article>

<style>
  .remote-preview-card {
    border: 1px solid var(--color-grey-20);
    border-radius: var(--radius-5);
    background: var(--color-grey-0);
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.08);
    overflow: hidden;
  }

  .remote-preview-shell {
    height: 170px;
    overflow: hidden;
    background: var(--color-grey-10);
  }

  .remote-preview-shell :global(.unified-embed-preview) {
    width: 100%;
    max-width: none;
    min-width: 0;
    height: 100%;
    border-radius: 0;
  }

  .remote-preview-meta {
    display: grid;
    gap: 12px;
    padding: 14px;
  }

  .remote-preview-meta strong,
  .remote-preview-meta small,
  .remote-source-label {
    display: block;
  }

  .remote-preview-meta small,
  .remote-source-label {
    color: var(--color-font-secondary);
    font-size: 0.82rem;
  }

  .remote-source-label {
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }

  .remote-preview-actions {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
  }

  .remote-preview-actions button {
    border: 0;
    border-radius: var(--radius-3);
    padding: 9px 12px;
    background: var(--color-button-primary);
    color: var(--color-font-button);
    font: inherit;
    cursor: pointer;
  }

  .remote-preview-actions button:disabled {
    opacity: 0.55;
    cursor: not-allowed;
  }
</style>
