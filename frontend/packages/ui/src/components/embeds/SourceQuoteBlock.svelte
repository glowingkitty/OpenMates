<script lang="ts">
  // frontend/packages/ui/src/components/embeds/SourceQuoteBlock.svelte
  //
  // Styled source quote block rendered in the chat message stream.
  // Replaces a standard blockquote when the content is a verified source quote
  // using the syntax: > [quoted text](embed:some-ref-k8D)
  //
  // Visual design:
  //   - Left accent bar with app gradient colour
  //   - Quoted text in italic
  //   - Source badge at bottom (app icon + source name)
  //   - Click opens embed fullscreen and highlights the quoted text
  //
  // Architecture context: See docs/architecture/source-quotes.md
  // Tests: (none yet)

  import { embedStore, embedRefIndexVersion } from '../../services/embedStore';

  interface Props {
    /** The exact quoted text from the source */
    quoteText: string;
    /** Short slug from the LLM (e.g. "wikipedia.org-k8D") */
    embedRef: string;
    /** app_id hint from parse-time — may be null */
    appId?: string | null;
  }

  let { quoteText, embedRef, appId = null }: Props = $props();

  // Reactively resolve the effective appId (same pattern as EmbedInlineLink).
  // Reading $embedRefIndexVersion registers it as a reactive dependency so
  // the badge colour self-corrects when new refs are registered during streaming.
  let effectiveAppId = $derived.by(() => {
    void $embedRefIndexVersion;
    return appId ?? embedStore.resolveAppIdByRef(embedRef);
  });

  // Left accent bar colour — uses the app gradient start colour.
  // Falls back to a neutral accent border when appId is unknown.
  let accentStyle = $derived(
    effectiveAppId
      ? `border-left-color: var(--color-app-${effectiveAppId}-start);`
      : '',
  );

  // Badge gradient (small circular icon background)
  let badgeGradientStyle = $derived(
    effectiveAppId
      ? `background: var(--color-app-${effectiveAppId});`
      : 'background: var(--color-grey-30);',
  );

  // Display the embed_ref as the source label — strip the random suffix for readability.
  // e.g. "wikipedia.org-k8D" → "wikipedia.org"
  let sourceLabel = $derived(
    embedRef.replace(/-[a-zA-Z0-9]{3}$/, '') || embedRef,
  );

  /**
   * Open embed fullscreen on click, passing the quote text so the fullscreen
   * can highlight it within the source content.
   */
  async function handleClick(e: MouseEvent) {
    e.preventDefault();
    e.stopPropagation();

    const resolvedEmbedId = embedStore.resolveByRef(embedRef);

    if (!resolvedEmbedId) {
      console.warn(
        `[SourceQuoteBlock] Cannot open fullscreen: embed_ref "${embedRef}" not yet resolved`,
      );
      return;
    }

    // Resolve child → parent if needed (same pattern as EmbedInlineLink)
    let targetEmbedId = resolvedEmbedId;
    let focusChildEmbedId: string | undefined;
    try {
      const rawEntry = await embedStore.getRawEntry(`embed:${resolvedEmbedId}`);
      if (rawEntry?.parent_embed_id) {
        targetEmbedId = rawEntry.parent_embed_id;
        focusChildEmbedId = resolvedEmbedId;
      }
    } catch (err) {
      console.debug('[SourceQuoteBlock] getRawEntry failed, using child embed_id:', err);
    }

    console.debug(
      `[SourceQuoteBlock] Opening fullscreen for embed_ref "${embedRef}" → ${targetEmbedId}` +
        (focusChildEmbedId ? ` (focus child: ${focusChildEmbedId})` : '') +
        `, highlight: "${quoteText.substring(0, 50)}..."`,
    );

    document.dispatchEvent(
      new CustomEvent('embedfullscreen', {
        detail: {
          embedId: targetEmbedId,
          embedType: 'app-skill-use',
          focusChildEmbedId,
          // Pass the quote text so the fullscreen can highlight it
          highlightQuoteText: quoteText,
        },
        bubbles: true,
      }),
    );
  }
</script>

<!-- Source quote block — distinct from plain blockquotes.
     Uses <button> for proper semantic click handling + keyboard accessibility. -->
<button
  class="source-quote-block"
  style={accentStyle}
  type="button"
  onclick={handleClick}
>
  <!-- Quoted text -->
  <div class="source-quote-text">
    <span class="source-quote-mark">&ldquo;</span>{quoteText}<span class="source-quote-mark">&rdquo;</span>
  </div>

  <!-- Source badge -->
  <div class="source-quote-badge">
    <span class="source-quote-badge-icon" style={badgeGradientStyle} aria-hidden="true">
      <span class="icon_rounded {effectiveAppId || ''}"></span>
    </span>
    <span class="source-quote-badge-label">{sourceLabel}</span>
  </div>
</button>

<style>
  /* ── Source Quote Block ────────────────────────────────────────────────── */

  .source-quote-block {
    display: flex;
    flex-direction: column;
    gap: 8px;
    padding: 12px 16px;
    margin: 8px 0;
    border-left: 3px solid var(--color-border-accent, #d0d7de);
    border-radius: 0 8px 8px 0;
    background-color: var(--color-background-tertiary, #f8f9fa);
    cursor: pointer;
    transition: background-color 0.15s ease, box-shadow 0.15s ease;
    user-select: none;
  }

  .source-quote-block:hover {
    background-color: var(--color-background-secondary, #f0f2f4);
    box-shadow: 0 1px 4px rgba(0, 0, 0, 0.06);
  }

  .source-quote-block:active {
    background-color: var(--color-background-tertiary, #f8f9fa);
  }

  /* ── Quoted text ─────────────────────────────────────────────────────── */

  .source-quote-text {
    font-size: 14px;
    font-style: italic;
    line-height: 1.5;
    color: var(--color-font-primary, #000);
    /* Limit to 5 lines max */
    display: -webkit-box;
    -webkit-line-clamp: 5;
    line-clamp: 5;
    -webkit-box-orient: vertical;
    overflow: hidden;
    text-overflow: ellipsis;
    word-break: break-word;
  }

  .source-quote-mark {
    font-style: normal;
    font-weight: 600;
    color: var(--color-grey-40);
    font-size: 16px;
  }

  /* ── Source badge ────────────────────────────────────────────────────── */

  .source-quote-badge {
    display: flex;
    align-items: center;
    gap: 6px;
  }

  .source-quote-badge-icon {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 18px;
    height: 18px;
    min-width: 18px;
    border-radius: 50%;
    flex-shrink: 0;
  }

  /* Scale down the icon_rounded icon inside the small badge */
  .source-quote-badge-icon :global(.icon_rounded) {
    width: 9px !important;
    height: 9px !important;
    min-width: 9px;
    position: relative;
    bottom: auto;
    left: auto;
    z-index: auto;
    background: transparent !important;
  }

  .source-quote-badge-icon :global(.icon_rounded::after) {
    filter: brightness(0) invert(1);
    width: 100%;
    height: 100%;
    background-size: contain !important;
  }

  .source-quote-badge-label {
    font-size: 12px;
    font-weight: 500;
    color: var(--color-grey-60);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    max-width: 200px;
  }

  /* ── Dark mode adjustments ──────────────────────────────────────────── */

  :global([data-theme="dark"]) .source-quote-block {
    background-color: var(--color-background-tertiary, rgba(255, 255, 255, 0.04));
  }

  :global([data-theme="dark"]) .source-quote-block:hover {
    background-color: var(--color-background-secondary, rgba(255, 255, 255, 0.07));
  }

  :global([data-theme="dark"]) .source-quote-mark {
    color: var(--color-grey-50);
  }
</style>
