<!--
  frontend/packages/ui/src/components/embeds/math/MathPlotEmbedPreviewLarge.svelte

  Large preview variant for Math Plot embeds.
  Used when a single math-plot embed is auto-promoted to large preview
  in assistant messages (promoteSingleAssistantEmbedsToLarge in parse_message.ts).

  Wraps EmbedReferencePreview within UnifiedEmbedPreviewLarge which expands the card
  to full assistant-response width with BasicInfosBar constrained to 300px centered.

  Architecture: See docs/architecture/embeds.md for the large-preview pipeline.
  Tests: frontend/packages/ui/src/message_parsing/__tests__/parse_message.test.ts
-->

<script lang="ts">
  import UnifiedEmbedPreviewLarge from '../UnifiedEmbedPreviewLarge.svelte';
  import EmbedReferencePreview from '../EmbedReferencePreview.svelte';

  interface Props {
    /** Embed reference — UUID when auto-promoted from embed node */
    embedRef: string;
    /** Pre-resolved UUID embed ID — may be null when first created */
    embedId?: string | null;
  }

  let { embedRef, embedId = null }: Props = $props();
</script>

<UnifiedEmbedPreviewLarge>
  <EmbedReferencePreview {embedRef} {embedId} variant="large" />
</UnifiedEmbedPreviewLarge>
