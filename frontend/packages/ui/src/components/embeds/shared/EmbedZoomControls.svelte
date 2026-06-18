<!--
  frontend/packages/ui/src/components/embeds/shared/EmbedZoomControls.svelte

  Shared floating zoom controls for fullscreen embeds.
  Extracted from the document embed so diagram, document, and future zoomable
  fullscreen surfaces use one compact in-content control pattern instead of
  adding multiple header CTA buttons.
-->

<script lang="ts">
  interface Props {
    zoomOut: () => void;
    zoomIn: () => void;
    resetZoom: () => void;
    zoomLabel: string;
    zoomOutDisabled?: boolean;
    zoomInDisabled?: boolean;
    zoomOutTestId?: string;
    zoomInTestId?: string;
    resetTestId?: string;
  }

  let {
    zoomOut,
    zoomIn,
    resetZoom,
    zoomLabel,
    zoomOutDisabled = false,
    zoomInDisabled = false,
    zoomOutTestId,
    zoomInTestId,
    resetTestId
  }: Props = $props();
</script>

<div class="doc-zoom-bar">
  <div class="doc-zoom-bar-inner">
    <button
      class="doc-zoom-btn"
      onclick={zoomOut}
      aria-label="Zoom out"
      disabled={zoomOutDisabled}
      data-testid={zoomOutTestId}
    >
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
        <path d="M3 8h10" stroke="currentColor" stroke-width="2" stroke-linecap="round" />
      </svg>
    </button>
    <button
      class="doc-zoom-level"
      onclick={resetZoom}
      aria-label="Reset zoom"
      title="Click to fit page to screen"
      data-testid={resetTestId}
    >
      {zoomLabel}
    </button>
    <button
      class="doc-zoom-btn"
      onclick={zoomIn}
      aria-label="Zoom in"
      disabled={zoomInDisabled}
      data-testid={zoomInTestId}
    >
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
        <path d="M8 3v10M3 8h10" stroke="currentColor" stroke-width="2" stroke-linecap="round" />
      </svg>
    </button>
  </div>
</div>

<style>
  .doc-zoom-bar {
    position: sticky;
    bottom: 16px;
    z-index: var(--z-index-modal);
    pointer-events: none;
    display: flex;
    justify-content: center;
    margin-top: -60px;
    padding-bottom: var(--spacing-8);
  }

  .doc-zoom-bar-inner {
    display: flex;
    align-items: center;
    gap: var(--spacing-2);
    background: var(--color-grey-0, #ffffff);
    border-radius: 28px;
    padding: var(--spacing-2) var(--spacing-3);
    box-shadow:
      0 2px 8px rgba(0, 0, 0, 0.15),
      0 0 1px rgba(0, 0, 0, 0.1);
    pointer-events: auto;
  }

  .doc-zoom-btn {
    width: 36px;
    height: 36px;
    border-radius: 50%;
    border: none;
    background: transparent;
    color: var(--color-grey-70, #555);
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: background-color var(--duration-fast), color var(--duration-fast);
    padding: 0;
    flex-shrink: 0;
  }

  .doc-zoom-btn:hover:not(:disabled) {
    background: var(--color-grey-10, #f0f0f0);
    color: var(--color-grey-100, #1a1a1a);
  }

  .doc-zoom-btn:active:not(:disabled) {
    background: var(--color-grey-20, #e5e5e5);
  }

  .doc-zoom-btn:disabled {
    opacity: 0.3;
    cursor: not-allowed;
  }

  .doc-zoom-level {
    min-width: 52px;
    height: 32px;
    border-radius: var(--radius-7);
    border: 1px solid var(--color-grey-20, #e5e5e5);
    background: var(--color-grey-5, #fafafa);
    color: var(--color-grey-80, #333);
    font-size: var(--font-size-xs);
    font-weight: 500;
    font-family: inherit;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 0 10px;
    transition: background-color var(--duration-fast), border-color var(--duration-fast);
    letter-spacing: 0.2px;
  }

  .doc-zoom-level:hover {
    background: var(--color-grey-10, #f0f0f0);
    border-color: var(--color-grey-30, #ccc);
  }

  @container fullscreen (max-width: 500px) {
    .doc-zoom-bar {
      bottom: 10px;
      margin-top: -56px;
      padding-bottom: var(--spacing-5);
    }
  }
</style>
