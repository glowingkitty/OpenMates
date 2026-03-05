<script lang="ts">
  // frontend/packages/ui/src/components/embeds/UnifiedEmbedPreviewLarge.svelte
  //
  // Purpose: Apply a "large" presentation wrapper to existing embed preview cards
  // without replacing their app/skill-specific internals.
  //
  // Architecture: wraps existing UnifiedEmbedPreview-based cards rendered by
  // the renderer pipeline. Used by [!](embed:ref) inline references.
  // Tests: frontend/packages/ui/src/message_parsing/__tests__/parse_message.test.ts
</script>

<div class="unified-embed-preview-large">
  <slot />
</div>

<style>
  .unified-embed-preview-large {
    width: 100%;
    display: flex;
    justify-content: center;
    margin: 6px 0;
  }

  .unified-embed-preview-large :global(.unified-embed-preview.desktop) {
    width: min(100%, 460px) !important;
    min-width: min(100%, 460px) !important;
    max-width: min(100%, 460px) !important;
    height: 280px !important;
    min-height: 280px !important;
    max-height: 280px !important;
  }

  .unified-embed-preview-large :global(.basic_infos) {
    margin-left: auto;
    margin-right: auto;
  }
</style>
