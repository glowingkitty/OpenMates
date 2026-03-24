<!--
  DocsCodeBlock Component

  Renders code blocks in documentation pages using the existing CodeEmbedPreview
  and CodeEmbedFullscreen components. Allows these embed components to be used
  without actual embed data — purely for rendering code content.

  Architecture: docs/architecture/frontend/docs-web-app.md
-->

<script lang="ts">
  import CodeEmbedPreview from '@repo/ui/components/embeds/code/CodeEmbedPreview.svelte';
  import CodeEmbedFullscreen from '@repo/ui/components/embeds/code/CodeEmbedFullscreen.svelte';

  interface Props {
    /** The code content to display */
    code: string;
    /** Programming language for syntax highlighting */
    language?: string;
    /** Unique ID for this code block (used by CodeEmbedPreview) */
    blockId: string;
  }

  let { code, language = '', blockId }: Props = $props();

  let showFullscreen = $state(false);
  let lineCount = $derived(code.split('\n').length);

  function openFullscreen() {
    showFullscreen = true;
  }

  function closeFullscreen() {
    showFullscreen = false;
  }
</script>

<div class="docs-code-block">
  <CodeEmbedPreview
    id={blockId}
    status="finished"
    {language}
    lineCount={lineCount}
    codeContent={code}
    onFullscreen={openFullscreen}
  />
</div>

{#if showFullscreen}
  <div class="docs-code-fullscreen-overlay">
    <CodeEmbedFullscreen
      codeContent={code}
      {language}
      lineCount={lineCount}
      onClose={closeFullscreen}
    />
  </div>
{/if}

<style>
  .docs-code-block {
    margin: 0.75rem 0;
    min-width: 0;
    container-type: inline-size;
    container-name: embed-preview;
  }

  .docs-code-fullscreen-overlay {
    position: fixed;
    inset: 0;
    z-index: 1000;
    background: var(--color-background-primary, #fff);
  }
</style>
