<!--
  frontend/packages/ui/src/components/embeds/web/WebsiteEmbedPreviewLarge.svelte

  Large preview variant for website embeds ([!](embed:ref) syntax).
  Wraps EmbedReferencePreview within UnifiedEmbedPreviewLarge which expands the
  card to full assistant-response width with BasicInfosBar constrained to 300px.

  Website-specific large layout overrides:
  - Description text: capped at 30% width so it does not stretch too wide.
    -webkit-line-clamp: 16 allows more text to show in the taller card.
    margin-left: 20px adds spacing between description and image.
  - Preview image: fills the remaining horizontal space (flex:1) at 350px height
    so it scales up proportionally.

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

  /* Description text: 30% width, up to 16 lines visible in the taller card.
     flex: 0 1 30% allows shrinking but not growing beyond 30%.
     margin-left: 20px adds spacing between description and image.
     !important needed to override scoped styles in WebsiteEmbedPreview base (40%). */
  .website-embed-preview-large :global(.website-description) {
    max-width: 30% !important;
    width: 30% !important;
    flex: 0 1 30% !important;
    min-width: 0 !important;
    overflow: hidden !important;
    -webkit-line-clamp: 16 !important;
    line-clamp: 16 !important;
    margin-left: 20px !important;
  }

  /* The content row must stretch to fill the full details area height so the
     image can fill the full card height (minus the BasicInfosBar). */
  .website-embed-preview-large :global(.website-content-row) {
    align-items: stretch;
    height: 100%;
  }

  /* Let the preview image fill all remaining horizontal space and cover the
     full height of the content area (350px card height).
     !important needed to override scoped base styles (height: 171px).
     border-radius clips the right corners to match the card shape — the
     outer .details-section does NOT have overflow:hidden so the BasicInfosBar
     can protrude below. */
  .website-embed-preview-large :global(.website-preview-image:not(.full-width)) {
    flex: 1 1 0 !important;
    min-width: 0 !important;
    height: 350px !important;
    max-height: none !important;
    transform: none !important;
    overflow: hidden !important;
    border-radius: 0 30px 30px 0 !important;
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
