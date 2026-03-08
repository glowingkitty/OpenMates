<!--
  frontend/packages/ui/src/components/embeds/web/WebsiteEmbedPreviewLarge.svelte

  Large preview variant for website embeds ([!](embed:ref) syntax).
  Wraps EmbedReferencePreview within UnifiedEmbedPreviewLarge which expands the
  card to full assistant-response width with BasicInfosBar constrained to 300px.

  Website-specific large layout overrides:
  - Description text: capped at 30% width so it does not stretch too wide.
    -webkit-line-clamp: 15 allows more text to show in the taller card.
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

  /* Description text: 30% width, up to 15 lines visible in the taller card.
     flex: 0 1 30% allows shrinking but not growing beyond 30%. */
  .website-embed-preview-large :global(.website-description) {
    max-width: 30%;
    width: 30%;
    flex: 0 1 30%;
    min-width: 0;
    overflow: hidden;
    -webkit-line-clamp: 15;
    line-clamp: 15;
  }

  /* The content row must stretch to fill the full details area height so the
     image can fill the full card height (minus the BasicInfosBar). */
  .website-embed-preview-large :global(.website-content-row) {
    align-items: stretch;
    height: 100%;
  }

  /* Let the preview image fill all remaining horizontal space and cover the
     full height of the content area (350px card height). */
  .website-embed-preview-large :global(.website-preview-image:not(.full-width)) {
    flex: 1 1 0;
    min-width: 0;
    height: 350px;
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
