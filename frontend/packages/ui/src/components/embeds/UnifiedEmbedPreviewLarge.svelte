<script lang="ts">
  // frontend/packages/ui/src/components/embeds/UnifiedEmbedPreviewLarge.svelte
  //
  // Purpose: Apply a "large" presentation wrapper to existing embed preview cards
  // without replacing their app/skill-specific internals.
  //
  // Architecture: wraps existing UnifiedEmbedPreview-based cards rendered by
  // the renderer pipeline. Used by per-type XxxEmbedPreviewLarge.svelte files.
  // See docs/architecture/embeds.md for embed rendering pipeline.
  //
  // Design spec:
  //   - Card fills the FULL width of the assistant response container (no max-width cap)
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

  /* Override desktop card sizing to fill the full assistant response width and be taller.
     The standard desktop card is 300×200px; the large variant expands to full width
     with no max-width cap so it uses the complete available response column width. */
  .unified-embed-preview-large :global(.unified-embed-preview.desktop) {
    width: 100% !important;
    min-width: unset !important;
    max-width: unset !important;
    height: 350px !important;
    min-height: 350px !important;
    max-height: 350px !important;
  }

  /* BasicInfosBar stays at ~300px width (matching the standard card width) and is
     horizontally centered within the wider card via auto margins.
     This prevents the info bar from stretching across the entire large card. */
  .unified-embed-preview-large :global(.basic_infos) {
    width: 300px;
    max-width: 300px;
    margin-left: auto;
    margin-right: auto;
  }
</style>
