<!--
  frontend/packages/ui/src/components/embeds/web/WebsiteEmbedPreviewLarge.svelte

  Large preview variant for website embeds ([!](embed:ref) syntax).
  Wraps EmbedReferencePreview within UnifiedEmbedPreviewLarge which expands the
  card to full assistant-response width with BasicInfosBar constrained to 300px.

  Website-specific large layout overrides:
  - Description text: capped at 150px max-width (half the standard 300px card width)
    so the text column does not stretch uncomfortably wide on the large card.
  - Preview image: fills the remaining horizontal space (flex:1) so it scales up
    proportionally instead of being capped at the standard 150px thumbnail width.

  Architecture: See docs/architecture/embeds.md for the large-preview pipeline.
  Tests: frontend/packages/ui/src/message_parsing/__tests__/parse_message.test.ts
-->

<script lang="ts">
  import UnifiedEmbedPreviewLarge from '../UnifiedEmbedPreviewLarge.svelte';
  import EmbedReferencePreview from '../EmbedReferencePreview.svelte';

  interface Props {
    /** Short embed reference slug (e.g. "apple-macbook-k8D") */
    embedRef: string;
    /** Pre-resolved UUID embed ID -- may be null when first created */
    embedId?: string | null;
  }

  let { embedRef, embedId = null }: Props = $props();
</script>

<div class="website-embed-preview-large">
  <UnifiedEmbedPreviewLarge>
    <EmbedReferencePreview {embedRef} {embedId} variant="large" />
  </UnifiedEmbedPreviewLarge>
</div>

<style>
  /* Wrapper to scope :global overrides to website large only */
  .website-embed-preview-large {
    width: 100%;
  }

  /* Limit description text to half the standard card width (150px) so it does not
     stretch uncomfortably wide on the large card. flex:none prevents it from
     growing to fill remaining space (the image takes that role). */
  .website-embed-preview-large :global(.website-description) {
    max-width: 150px;
    flex: none;
  }

  /* Let the preview image fill the remaining horizontal space and scale up
     proportionally. Remove the fixed 150px width and translateX offset from
     the standard card layout. */
  .website-embed-preview-large :global(.website-preview-image:not(.full-width)) {
    width: auto;
    flex: 1;
    min-width: 0;
    height: 100%;
    transform: none;
  }

  /* Ensure the image inside fills the expanded container */
  .website-embed-preview-large :global(.website-preview-image:not(.full-width) img) {
    width: 100%;
    height: 100%;
    object-fit: cover;
    object-position: center;
  }
</style>
