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

  /* Limit description text to exactly 150px (half of the standard 300px card width).
     flex: 0 0 150px prevents any growing or shrinking — the image takes all extra space. */
  .website-embed-preview-large :global(.website-description) {
    max-width: 150px;
    width: 150px;
    flex: 0 0 150px;
    min-width: 0;
    overflow: hidden;
  }

  /* The content row must stretch to fill the full details area height so the
     image can fill the full card height (minus the BasicInfosBar). */
  .website-embed-preview-large :global(.website-content-row) {
    align-items: stretch;
    height: 100%;
  }

  /* Let the preview image fill all remaining horizontal space and cover the
     full height of the content area. Remove any fixed pixel height from base. */
  .website-embed-preview-large :global(.website-preview-image:not(.full-width)) {
    flex: 1 1 0;
    min-width: 0;
    height: 100%;
    max-height: none;
    transform: none;
    overflow: hidden;
  }

  /* Ensure the img itself covers the full container */
  .website-embed-preview-large :global(.website-preview-image:not(.full-width) img) {
    width: 100%;
    height: 100%;
    object-fit: cover;
    object-position: center;
    display: block;
  }
</style>
