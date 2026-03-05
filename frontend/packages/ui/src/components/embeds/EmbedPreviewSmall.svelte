<script lang="ts">
  // frontend/packages/ui/src/components/embeds/EmbedPreviewSmall.svelte
  //
  // Compact (existing preview-card size) clickable embed card rendered inline in
  // the message flow when the LLM writes [](embed:some-ref) (empty display text).
  //
  // Visual design:
  //   A horizontally oriented card (~300×80px) with:
  //   - Left: circular gradient app-icon badge (30px)
  //   - Centre: embed reference name (with random suffix stripped)
  //   - Right: chevron arrow indicating it is clickable
  //
  // On click: dispatches the same `embedfullscreen` CustomEvent used by
  // EmbedInlineLink and SourceQuoteBlock so ActiveChat opens the fullscreen panel.
  //
  // The card resolves the embed_ref → embed_id lazily at click time (not at
  // render time) to avoid blocking rendering during streaming.
  //
  // Architecture: analogous to SourceQuoteBlock.svelte but for full embed preview.
  // Tests: (none yet)

  import { embedStore, embedRefIndexVersion } from '../../services/embedStore';

  interface Props {
    /** Short slug from the LLM (e.g. "ryanair-0600-k8D") */
    embedRef: string;
    /** Pre-resolved UUID — may be null when the node is first created */
    embedId?: string | null;
    /** app_id hint from parse-time — may be null */
    appId?: string | null;
  }

  let { embedRef, embedId = null, appId = null }: Props = $props();

  // Reactively resolve the effective appId (same pattern as EmbedInlineLink).
  let effectiveAppId = $derived.by(() => {
    void $embedRefIndexVersion;
    return appId ?? embedStore.resolveAppIdByRef(embedRef);
  });

  // Badge gradient — uses the app gradient.
  let gradientStyle = $derived(
    effectiveAppId
      ? `background: var(--color-app-${effectiveAppId});`
      : 'background: var(--color-grey-30);',
  );

  // Display label — strip the random 3-char suffix for readability.
  // e.g. "ryanair-0600-k8D" → "ryanair-0600"
  let displayLabel = $derived(embedRef.replace(/-[a-zA-Z0-9]{3}$/, '') || embedRef);

  /**
   * Open embed fullscreen on click.
   * Resolves embed_ref → embed_id at click time (lazy).
   * Handles child → parent redirect (same pattern as EmbedInlineLink).
   */
  async function handleClick(e: MouseEvent) {
    e.preventDefault();
    e.stopPropagation();

    const resolvedEmbedId = embedId || embedStore.resolveByRef(embedRef);

    if (!resolvedEmbedId) {
      console.warn(
        `[EmbedPreviewSmall] Cannot open fullscreen: embed_ref "${embedRef}" not yet resolved`,
      );
      return;
    }

    let targetEmbedId = resolvedEmbedId;
    let focusChildEmbedId: string | undefined;
    try {
      const rawEntry = await embedStore.getRawEntry(`embed:${resolvedEmbedId}`);
      if (rawEntry?.parent_embed_id) {
        targetEmbedId = rawEntry.parent_embed_id;
        focusChildEmbedId = resolvedEmbedId;
      }
    } catch (err) {
      console.debug(`[EmbedPreviewSmall] getRawEntry failed, using child embed_id:`, err);
    }

    document.dispatchEvent(
      new CustomEvent('embedfullscreen', {
        detail: {
          embedId: targetEmbedId,
          embedType: 'app-skill-use',
          focusChildEmbedId,
        },
        bubbles: true,
      }),
    );
  }
</script>

<!-- Compact embed preview card — full-width block in the message flow -->
<button
  class="embed-preview-small"
  type="button"
  onclick={handleClick}
>
  <!-- App icon badge -->
  <span class="embed-preview-small-badge" style={gradientStyle} aria-hidden="true">
    <span class="icon_rounded {effectiveAppId || ''}"></span>
  </span>

  <!-- Embed label -->
  <span class="embed-preview-small-label">{displayLabel}</span>

  <!-- Chevron arrow (right side) -->
  <span class="embed-preview-small-chevron" aria-hidden="true">&#8250;</span>
</button>

<style>
  /* Compact horizontal card — resets global button styles then applies card look */
  .embed-preview-small {
    all: unset;

    display: flex;
    align-items: center;
    gap: 10px;
    width: 100%;
    max-width: 360px;
    padding: 10px 14px;
    margin: 6px 0;
    border-radius: 10px;
    background-color: var(--color-background-tertiary, rgba(0, 0, 0, 0.04));
    border: 1px solid var(--color-border-primary, rgba(0, 0, 0, 0.08));
    cursor: pointer;
    box-sizing: border-box;
    font: inherit;
    color: inherit;
    transition: background-color 0.15s ease, box-shadow 0.15s ease;
    text-align: left;
  }

  .embed-preview-small:hover {
    background-color: var(--color-background-secondary, rgba(0, 0, 0, 0.07));
    box-shadow: 0 1px 4px rgba(0, 0, 0, 0.06);
    scale: none;
  }

  .embed-preview-small:active {
    background-color: var(--color-background-tertiary, rgba(0, 0, 0, 0.04));
    scale: none;
    filter: none;
  }

  /* 30px circular app-icon badge */
  .embed-preview-small-badge {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 30px;
    height: 30px;
    min-width: 30px;
    border-radius: 50%;
    flex-shrink: 0;
  }

  .embed-preview-small-badge :global(.icon_rounded) {
    width: 14px !important;
    height: 14px !important;
    min-width: 14px;
    position: relative;
    bottom: auto;
    left: auto;
    z-index: auto;
    background: transparent !important;
  }

  .embed-preview-small-badge :global(.icon_rounded::after) {
    filter: brightness(0) invert(1);
    width: 100%;
    height: 100%;
    background-size: contain !important;
  }

  /* Embed label — fills remaining width */
  .embed-preview-small-label {
    flex: 1 1 auto;
    font-size: 13px;
    font-weight: 500;
    color: var(--color-font-primary);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  /* Chevron arrow on the right */
  .embed-preview-small-chevron {
    font-size: 18px;
    line-height: 1;
    color: var(--color-font-tertiary);
    flex-shrink: 0;
  }

  /* Dark mode adjustments */
  :global([data-theme="dark"]) .embed-preview-small {
    background-color: var(--color-background-tertiary, rgba(255, 255, 255, 0.05));
    border-color: rgba(255, 255, 255, 0.08);
  }

  :global([data-theme="dark"]) .embed-preview-small:hover {
    background-color: var(--color-background-secondary, rgba(255, 255, 255, 0.09));
  }
</style>
