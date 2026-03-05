<script lang="ts">
  // frontend/packages/ui/src/components/embeds/EmbedPreviewSmall.svelte
  //
  // Purpose: Render [](embed:ref) by reusing the existing embed renderer pipeline
  // so the same app/skill-specific preview components are shown.
  //
  // Architecture: wraps EmbedReferencePreview (renderer-based mount).
  // Tests: frontend/packages/ui/src/message_parsing/__tests__/parse_message.test.ts

  import EmbedReferencePreview from './EmbedReferencePreview.svelte';

  interface Props {
    embedRef: string;
    embedId?: string | null;
    appId?: string | null;
  }

  let { embedRef, embedId = null }: Props = $props();
</script>

<div class="embed-preview-small">
  <EmbedReferencePreview {embedRef} {embedId} variant="small" />
</div>

<style>
  .embed-preview-small {
    width: 100%;
  }
</style>
