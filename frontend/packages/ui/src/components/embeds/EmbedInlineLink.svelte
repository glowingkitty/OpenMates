<script lang="ts">
  // frontend/packages/ui/src/components/embeds/EmbedInlineLink.svelte
  //
  // Compact inline embed reference rendered inside ReadOnlyMessage.
  //
  // Visuals (left to right):
  //   1. Small 20 px circular badge: app gradient background + white icon_rounded icon
  //   2. Display text as a solid-colour clickable link
  //      Dark mode  → uses the gradient END colour (brighter, higher contrast on dark bg)
  //      Light mode → uses the gradient START colour (darker, higher contrast on light bg)
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
  //
  // Reliability note:
  //   appId is resolved both from the prop (set at parse-time) AND reactively
  //   via embedStore.refIndexVersion so the badge colour self-corrects whenever
  //   new refs are registered — e.g. after a page-reload cold-start or when a
  //   streaming embed card arrives after this inline link was already rendered.

  import { embedStore, embedRefIndexVersion } from '../../services/embedStore';

  interface Props {
    /** Short slug from the LLM (e.g. "ryanair-0600-k8D") */
    embedRef: string;
    /** Pre-resolved UUID — may be null when the node is first created */
    embedId?: string | null;
    /** Human-readable text chosen by the LLM */
    displayText: string;
    /** app_id hint from parse-time (e.g. "travel", "web", "videos") — may be
     *  null if the ref index was empty when the message was parsed.  Always
     *  falls back to a live lookup via embedStore.refIndexVersion. */
    appId?: string | null;
    /**
     * For code embeds: the first line to highlight when the fullscreen opens
     * (1-indexed). Parsed from the #L42 or #L10-L20 suffix in embed: links.
     * null means no line highlighting.
     */
    focusLineStart?: number | null;
    /**
     * For code embeds: the last line to highlight (1-indexed, inclusive).
     * Equal to focusLineStart for single-line references.
     * null when focusLineStart is null.
     */
    focusLineEnd?: number | null;
  }

  let { embedRef, embedId = null, displayText, appId = null, focusLineStart = null, focusLineEnd = null }: Props = $props();

  // Reactively resolve the effective appId.
  //
  // $embedRefIndexVersion is a Svelte auto-subscription to the embedRefIndexVersion
  // writable store. Whenever registerEmbedRef() increments this store, Svelte
  // automatically re-runs this $derived and any other expressions that reference
  // $embedRefIndexVersion — without requiring a full TipTap setContent() re-parse.
  //
  // Priority: prop appId (from parse-time two-pass fallback) > live index lookup.
  // The prop is trusted first because it may have been resolved via sibling
  // embed-node scanning (Pass 1), which is always correct even on cold-start.
  // The live lookup handles the case where the prop is null but the ref has
  // since been registered (e.g. streaming embed arrived after first render).
  //
  // $embedRefIndexVersion is read here purely as a reactive dependency trigger;
  // its numeric value is unused — only the side-effect of invalidating this
  // $derived matters.
  let effectiveAppId = $derived.by(() => {
    // Reading $embedRefIndexVersion registers it as a reactive dependency.
    // Whenever registerEmbedRef() increments this store, Svelte re-runs this
    // derived and picks up the newly available appId — no full re-parse needed.
    void $embedRefIndexVersion;
    return appId ?? embedStore.resolveAppIdByRef(embedRef);
  });

  // Badge gradient (circular icon background) — unchanged from original design.
  // Falls back to neutral grey when appId is unknown.
  let gradientStyle = $derived(
    effectiveAppId
      ? `background: var(--color-app-${effectiveAppId});`
      : 'background: var(--color-grey-30);',
  );

  // Solid text colour — switches between START (dark) and END (light) colours
  // via CSS custom properties set as inline style.  The actual selection is
  // done in CSS using the [data-theme="dark"] selector override so it responds
  // immediately to theme changes without a JS re-render.
  //
  // We set both colour values as CSS custom properties on the element itself
  // so the CSS rule can reference them without needing to know the appId.
  //
  //   --_link-color-light  = START colour (darker, for light backgrounds)
  //   --_link-color-dark   = END colour   (brighter, for dark backgrounds)
  //
  // Fallback: var(--color-grey-60) for unknown apps (readable in both modes).
  let textColorVarsStyle = $derived(
    effectiveAppId
      ? `--_link-color-light: var(--color-app-${effectiveAppId}-start); --_link-color-dark: var(--color-app-${effectiveAppId}-end);`
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

    const { targetEmbedId, focusChildEmbedId } =
      await embedStore.resolveFullscreenTarget(resolvedEmbedId);

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
          // Pass the line range so CodeEmbedFullscreen can highlight + scroll to the target lines
          focusLineRange: focusLineStart != null
            ? { start: focusLineStart, end: focusLineEnd ?? focusLineStart }
            : undefined,
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
    <span class="icon_rounded {effectiveAppId || ''}"></span>
  </span>
  <!-- Solid-colour display text — colour adapts to light/dark mode via CSS -->
  <span class="embed-inline-text" class:has-app-color={!!effectiveAppId} style={textColorVarsStyle}>{displayText}</span>
</span>

<style>
  /* Outer wrapper — true inline so it flows naturally within paragraph text.
   *
   * Using display:inline (not inline-flex) is critical for multi-line wrapping:
   * - inline-flex creates a single rectangular box, so the badge vertically
   *   centres inside the whole text height when text wraps to 2+ lines.
   * - display:inline lets the browser treat badge + text as a normal inline
   *   flow: the badge sits on the first line, and wrapped text continues
   *   on subsequent lines at the same colour, all part of the same click target.
   */
  .embed-inline-link {
    display: inline;
    cursor: pointer;
    text-decoration: none;
    /* Slight lift on hover to indicate interactivity */
    transition: opacity var(--duration-fast) var(--easing-default);
    user-select: none;
  }

  .embed-inline-link:hover {
    opacity: 0.8;
  }

  /* 20 px circular gradient badge — mirrors .app-icon-circle from BasicInfosBar.svelte
     but scaled down (61 px → 20 px, keeping the same shape/icon ratio).
     inline-flex + vertical-align:middle keeps it aligned to the text midline
     on the first line while text can wrap freely beneath it. */
  .embed-inline-badge {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 20px;
    height: 20px;
    min-width: 20px;
    border-radius: 50%;
    vertical-align: middle;
    margin-right: 3px;
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

  /* Display text — solid colour link.
   *
   * display:inline so it participates in normal text flow and wraps naturally
   * across lines, staying the same colour throughout.
   *
   * Default (light mode): use START colour (darker stop of the gradient,
   *   better contrast against light backgrounds).
   * Dark mode override:   use END colour   (brighter stop of the gradient,
   *   better contrast against dark backgrounds).
   *
   * Both colour values are set as CSS custom properties on the element via
   * textColorVarsStyle, so the rule below can reference them without knowing
   * the specific app. The .has-app-color guard keeps the fallback colour
   * active for unknown apps. */
  /* Unified clickable-text colour: brand CTA orange.
     Matches .markdown-link and .wiki-inline-text so users learn a single
     visual signal for "this text is clickable" — independent of which app
     the embed belongs to. The circular badge on the left still carries the
     per-app gradient for app identification. */
  .embed-inline-text {
    display: inline;
    font-size: inherit;
    font-weight: 500;
    line-height: inherit;
    color: var(--color-button-primary);
    transition: color 0.15s ease, opacity 0.15s ease;
  }

  .embed-inline-link:hover .embed-inline-text {
    color: var(--color-button-primary-hover);
  }

  .embed-inline-link:active .embed-inline-text {
    color: var(--color-button-primary-pressed);
    opacity: 0.85;
  }
</style>
