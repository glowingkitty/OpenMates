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
  //   - BasicInfosBar stays at the standard ~300px width, horizontally centered
  //     within the wider card so it does not stretch across the full card width
  //   - BasicInfosBar protrudes 15px below the card via translateY (overflow:visible)
  //   - Image corners are clipped via border-radius on .website-preview-image (not .details-section)
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
     The standard desktop card is 300x200px; the large variant expands to full width
     with no max-width cap so it uses the complete available response column width.
     overflow:visible allows the BasicInfosBar to protrude below via translateY. */
  .unified-embed-preview-large :global(.unified-embed-preview.desktop) {
    width: 100% !important;
    min-width: unset !important;
    max-width: unset !important;
    height: 350px !important;
    min-height: 350px !important;
    max-height: 350px !important;
    overflow: visible !important;
  }

  /* The details-section must NOT have overflow:hidden — that would clip the
     BasicInfosBar which protrudes below via translateY(15px).  Instead, per-type
     large components (e.g. WebsiteEmbedPreviewLarge) apply border-radius and
     overflow:hidden directly on the image element to clip rounded corners. */

  /* Also ensure the desktop-layout itself allows the info bar to overflow */
  .unified-embed-preview-large :global(.desktop-layout) {
    overflow: visible !important;
  }

  /* BasicInfosBar (.basic-infos-bar.desktop) stays at ~300px width (matching the
     standard card width) and is horizontally centered within the wider card via
     auto margins. This prevents the info bar from stretching across the full card.
     translateY(15px) shifts it below the card edge (visible thanks to overflow:visible). */
  .unified-embed-preview-large :global(.basic-infos-bar.desktop) {
    width: 300px;
    max-width: 300px;
    min-width: unset;
    margin-left: auto;
    margin-right: auto;
    flex-shrink: 0;
    transform: translateY(15px);
  }
</style>
