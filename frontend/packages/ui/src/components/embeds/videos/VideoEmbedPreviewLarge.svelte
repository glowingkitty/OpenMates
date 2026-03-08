<!--
  frontend/packages/ui/src/components/embeds/videos/VideoEmbedPreviewLarge.svelte

  Large preview variant for Video embeds ([!](embed:ref) syntax).
  Wraps EmbedReferencePreview within UnifiedEmbedPreviewLarge which expands the card
  to full assistant-response width with BasicInfosBar constrained to 300px centered.

  This component provides a per-type large preview container that can be extended
  in the future with Video-specific large-layout customisations.

  Architecture: See docs/architecture/embeds.md for the large-preview pipeline.
  Tests: frontend/packages/ui/src/message_parsing/__tests__/parse_message.test.ts
-->

<script lang="ts">
  import UnifiedEmbedPreviewLarge from '../UnifiedEmbedPreviewLarge.svelte';
  import EmbedReferencePreview from '../EmbedReferencePreview.svelte';

  interface Props {
    /** Short embed reference slug (e.g. "ryanair-0600-k8D") */
    embedRef: string;
    /** Pre-resolved UUID embed ID — may be null when first created */
    embedId?: string | null;
  }

  let { embedRef, embedId = null }: Props = $props();
</script>

<UnifiedEmbedPreviewLarge>
  <EmbedReferencePreview {embedRef} {embedId} variant="large" />
</UnifiedEmbedPreviewLarge>
