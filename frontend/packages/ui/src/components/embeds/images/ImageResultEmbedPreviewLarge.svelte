<!--
  frontend/packages/ui/src/components/embeds/images/ImageResultEmbedPreviewLarge.svelte

  Large preview variant for Image Result embeds ([!](embed:ref) syntax).
  Wraps EmbedReferencePreview within UnifiedEmbedPreviewLarge which expands the card
  to full assistant-response width with BasicInfosBar constrained to 300px centered.

  Architecture: See docs/architecture/embeds.md for the large-preview pipeline.
  Tests: frontend/packages/ui/src/message_parsing/__tests__/parse_message.test.ts
-->

<script lang="ts">
  import UnifiedEmbedPreviewLarge from '../UnifiedEmbedPreviewLarge.svelte';
  import EmbedReferencePreview from '../EmbedReferencePreview.svelte';

  interface Props {
    /** Short embed reference slug (e.g. "macbook-air-k8D") */
    embedRef: string;
    /** Pre-resolved UUID embed ID — may be null when first created */
    embedId?: string | null;
  }

  let { embedRef, embedId = null }: Props = $props();
</script>

<UnifiedEmbedPreviewLarge>
  <EmbedReferencePreview {embedRef} {embedId} variant="large" />
</UnifiedEmbedPreviewLarge>
