<script lang="ts">
  // frontend/packages/ui/src/components/embeds/UnifiedEmbedPreviewLarge.svelte
  //
  // Purpose: Apply a "large" presentation wrapper to existing embed preview cards
  // without replacing their app/skill-specific internals.
  //
  // Architecture: wraps existing UnifiedEmbedPreview-based cards rendered by
  // the renderer pipeline. Used by [!](embed:ref) inline references.
  //
  // Design spec:
  //   - Card fills full width of the message container
  //   - Card is taller than the standard 200px desktop card (350px)
  //   - BasicInfosBar stays at ~300px width, horizontally centered within the wider card
  //
  // Tests: frontend/packages/ui/src/message_parsing/__tests__/parse_message.test.ts

  import type { Snippet } from 'svelte';

  interface Props {
    children: Snippet;
  }

  let { children }: Props = $props();
</script>

<div class="unified-embed-preview-large">
  {@render children()}
</div>

<style>
  .unified-embed-preview-large {
    width: 100%;
    display: flex;
    justify-content: center;
    margin: 6px 0;
  }

  /* Override desktop card sizing to fill container width and be taller.
     The standard desktop card is 300×200px; the large variant expands to
     100% width (capped at 600px for readability) and 350px height. */
  .unified-embed-preview-large :global(.unified-embed-preview.desktop) {
    width: 100% !important;
    min-width: unset !important;
    max-width: 600px !important;
    height: 350px !important;
    min-height: 350px !important;
    max-height: 350px !important;
  }

  /* BasicInfosBar stays at ~300px width (matching standard card) and is centered
     horizontally within the wider card via auto margins. */
  .unified-embed-preview-large :global(.basic_infos) {
    width: 300px;
    max-width: 300px;
    margin-left: auto;
    margin-right: auto;
  }
</style>
