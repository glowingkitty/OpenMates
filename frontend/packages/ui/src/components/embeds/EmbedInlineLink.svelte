<script lang="ts">
  // frontend/packages/ui/src/components/embeds/EmbedInlineLink.svelte
  //
  // Compact inline embed reference rendered inside ReadOnlyMessage.
  //
  // Visuals (left to right):
  //   1. Small 20 px circular badge: app gradient background + white icon_rounded icon
  //   2. Display text as a gradient-coloured clickable link
  //
  // On click: dispatches a document-level "embedfullscreen" CustomEvent so
  // ActiveChat can open the fullscreen panel — same mechanism used by
  // AppSkillUseRenderer, GroupRenderer, and MapLocationRenderer.
  //
  // Zero-knowledge note:
  //   embed_ref (e.g. "ryanair-0600-k8D") is resolved to an embed UUID via the
  //   in-memory index in embedStore at click time.  The UUID is never exposed as
  //   a readable field — it only appears in the CustomEvent detail, which the
  //   fullscreen handler needs to look up the embed.

  import { embedStore } from '../../services/embedStore';

  interface Props {
    /** Short slug from the LLM (e.g. "ryanair-0600-k8D") */
    embedRef: string;
    /** Pre-resolved UUID — may be null when the node is first created */
    embedId?: string | null;
    /** Human-readable text chosen by the LLM */
    displayText: string;
    /** app_id used for gradient colour (e.g. "travel", "web", "videos") */
    appId?: string | null;
  }

  let { embedRef, embedId = null, displayText, appId = null }: Props = $props();

  // Derive badge gradient and text gradient from appId.
  // Falls back to a neutral grey gradient if appId is unknown.
  let gradientStyle = $derived(
    appId ? `background: var(--color-app-${appId});` : 'background: var(--color-grey-30);',
  );

  let textGradientStyle = $derived(
    appId
      ? `background: var(--color-app-${appId}); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;`
      : '',
  );

  /**
   * Open embed fullscreen on click.
   * Resolves embed_ref → embed_id at click time (lazy resolution handles the case
   * where the embed arrives after the message was already rendered).
   *
   * Child embeds (e.g. individual "connection" flight results) cannot be opened in
   * fullscreen directly — only their parent "app-skill-use" embed has a fullscreen
   * component. So when a child embed is clicked, we open the parent's fullscreen
   * (TravelSearchEmbedFullscreen, WebSearchEmbedFullscreen, etc.) and pass the
   * child's embed_id as `focusChildEmbedId` so the fullscreen can auto-open the
   * matching child overlay on mount, jumping straight to the specific result.
   */
  async function handleClick(e: MouseEvent) {
    e.preventDefault();
    e.stopPropagation();

    // Resolve embed_ref to embed_id (lazy, in case it arrived after first render)
    const resolvedEmbedId = embedId || embedStore.resolveByRef(embedRef);

    if (!resolvedEmbedId) {
      console.warn(
        `[EmbedInlineLink] Cannot open fullscreen: embed_ref "${embedRef}" not yet resolved`,
      );
      return;
    }

    // If this embed is a child embed (e.g. a single flight result of type "connection"),
    // navigate to the parent "app-skill-use" embed but also pass the child embed_id so
    // the fullscreen can auto-focus that specific result.
    let targetEmbedId = resolvedEmbedId;
    let focusChildEmbedId: string | undefined;
    try {
      const rawEntry = await embedStore.getRawEntry(`embed:${resolvedEmbedId}`);
      if (rawEntry?.parent_embed_id) {
        targetEmbedId = rawEntry.parent_embed_id;
        focusChildEmbedId = resolvedEmbedId;
        console.debug(
          `[EmbedInlineLink] Child embed detected — opening parent ${targetEmbedId}, focusing child ${focusChildEmbedId}`,
        );
      }
    } catch (err) {
      // getRawEntry failed — proceed with child embed_id as target (may show "not available" error)
      console.debug(`[EmbedInlineLink] getRawEntry failed, using child embed_id:`, err);
    }

    console.debug(
      `[EmbedInlineLink] Opening fullscreen for embed_ref "${embedRef}" → ${targetEmbedId}` +
        (focusChildEmbedId ? ` (focus child: ${focusChildEmbedId})` : ''),
    );

    document.dispatchEvent(
      new CustomEvent('embedfullscreen', {
        detail: {
          embedId: targetEmbedId,
          embedType: 'app-skill-use', // default type; ActiveChat will look up the real type
          // Pass the child embed_id so the search fullscreen can auto-open the specific result
          focusChildEmbedId,
        },
        bubbles: true,
      }),
    );
  }
</script>

<!-- Inline badge + link, rendered as a <span> so it flows within text -->
<span class="embed-inline-link" role="link" tabindex="0" onclick={handleClick} onkeydown={(e) => { if (e.key === 'Enter') handleClick(e as unknown as MouseEvent); }}>
  <!-- Small circular app-icon badge -->
  <span class="embed-inline-badge" style={gradientStyle} aria-hidden="true">
    <span class="icon_rounded {appId || ''}"></span>
  </span>
  <!-- Gradient display text -->
  <span class="embed-inline-text" style={textGradientStyle}>{displayText}</span>
</span>

<style>
  /* Outer wrapper — inline so it flows naturally within paragraph text */
  .embed-inline-link {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    cursor: pointer;
    text-decoration: none;
    vertical-align: middle;
    /* Slight lift on hover to indicate interactivity */
    transition: opacity 0.15s ease;
    user-select: none;
  }

  .embed-inline-link:hover {
    opacity: 0.8;
  }

  /* 20 px circular gradient badge — mirrors .app-icon-circle from BasicInfosBar.svelte
     but scaled down (61 px → 20 px, keeping the same shape/icon ratio) */
  .embed-inline-badge {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 20px;
    height: 20px;
    min-width: 20px;
    border-radius: 50%;
    flex-shrink: 0;
  }

  /* Scale down the icon_rounded icon inside the small badge.
     icon_rounded default is 26 px (as used in BasicInfosBar); here we use 10 px. */
  .embed-inline-badge :global(.icon_rounded) {
    width: 10px !important;
    height: 10px !important;
    min-width: 10px;
    position: relative;
    bottom: auto;
    left: auto;
    z-index: auto;
    background: transparent !important;
  }

  /* Make the icon white and scale it to fill the 10×10 badge circle.
     The global icon_rounded::after has background-size: 25px 25px (larger than
     our 10px element), which clips the SVG. Override with 'contain' so the icon
     SVG scales down to fit within the available area instead of being cropped. */
  .embed-inline-badge :global(.icon_rounded::after) {
    filter: brightness(0) invert(1);
    width: 100%;
    height: 100%;
    background-size: contain !important;
  }

  /* Display text — uses the same gradient-text technique as app store cards */
  .embed-inline-text {
    font-size: inherit;
    font-weight: 500;
    line-height: 1;
    /* Fallback colour if gradient is not supported */
    color: var(--color-grey-80);
  }
</style>
