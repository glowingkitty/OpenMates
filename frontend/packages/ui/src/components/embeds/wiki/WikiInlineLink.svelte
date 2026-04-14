<script lang="ts">
  // frontend/packages/ui/src/components/embeds/wiki/WikiInlineLink.svelte
  //
  // Compact inline Wikipedia topic link rendered inside ReadOnlyMessage.
  //
  // Visuals (left to right):
  //   1. Small 20 px circular badge: study app gradient background + study icon
  //   2. Display text in study app start/end colors (matches EmbedInlineLink pattern)
  //
  // On click: dispatches a document-level "wikifullscreen" CustomEvent so
  // ActiveChat can open the Wikipedia fullscreen panel — same event-dispatch
  // pattern used by EmbedInlineLink for embed references.
  //
  // Styling uses the "study" app color scheme (orange/red gradient) since
  // Wikipedia topics are study-related knowledge references.

  interface Props {
    /** The matched topic phrase as it appears in the message text */
    displayText: string;
    /** Canonical Wikipedia article title (e.g. "Albert_Einstein") */
    wikiTitle: string;
    /** Wikidata QID (e.g. "Q937") — may be null */
    wikidataId?: string | null;
    /** Thumbnail URL from Wikipedia batch validation — may be null */
    thumbnailUrl?: string | null;
    /** Short description from Wikipedia/Wikidata — may be null */
    description?: string | null;
  }

  let { displayText, wikiTitle, wikidataId = null, thumbnailUrl = null, description = null }: Props = $props();

  function handleClick(e: MouseEvent) {
    e.preventDefault();
    e.stopPropagation();

    document.dispatchEvent(
      new CustomEvent('wikifullscreen', {
        detail: {
          wikiTitle,
          wikidataId,
          displayText,
          thumbnailUrl,
          description,
        },
        bubbles: true,
      }),
    );
  }
</script>

<!-- Inline badge + link, rendered as a <span> so it flows within text -->
<span class="wiki-inline-link" role="link" tabindex="0" data-testid="wiki-inline-link" onclick={handleClick} onkeydown={(e) => { if (e.key === 'Enter') handleClick(e as unknown as MouseEvent); }}>
  <!-- Small circular study-app-gradient badge with study icon -->
  <span class="wiki-inline-badge" aria-hidden="true">
    <span class="icon_rounded study"></span>
  </span>
  <!-- Display text in study app colors -->
  <span class="wiki-inline-text">{displayText}</span>
</span>

<style>
  /* Outer wrapper — true inline so it flows naturally within paragraph text.
   * Matches EmbedInlineLink pattern for consistent visual flow. */
  .wiki-inline-link {
    display: inline;
    cursor: pointer;
    text-decoration: none;
    transition: opacity var(--duration-fast) var(--easing-default);
    user-select: none;
  }

  .wiki-inline-link:hover {
    opacity: 0.8;
  }

  /* 20 px circular badge — study gradient background, icon rendered inside at 10 px.
   * Matches EmbedInlineLink dimensions exactly for visual consistency. */
  .wiki-inline-badge {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 20px;
    height: 20px;
    min-width: 20px;
    border-radius: 50%;
    vertical-align: middle;
    margin-right: 3px;
    background: var(--color-app-study);
  }

  /* Scale down the icon_rounded icon inside the small badge (same as EmbedInlineLink).
     The gradient is on the outer badge; the inner icon stays transparent. */
  .wiki-inline-badge :global(.icon_rounded) {
    width: 10px !important;
    height: 10px !important;
    min-width: 10px;
    position: relative;
    bottom: auto;
    left: auto;
    z-index: auto;
    background: transparent !important;
  }

  .wiki-inline-badge :global(.icon_rounded::after) {
    filter: brightness(0) invert(1);
    width: 100%;
    height: 100%;
    background-size: contain !important;
  }

  /* Display text — uses study app start color (darker, readable on light bg)
   * Wiki links use the study-app colour scheme because Wikipedia topics are
   * study-related knowledge references. */
  .wiki-inline-text {
    display: inline;
    font-size: inherit;
    font-weight: 500;
    line-height: inherit;
    color: var(--color-app-study-start);
  }

  /* Dark mode: use study app end color (brighter, readable on dark bg) */
  :global([data-theme="dark"]) .wiki-inline-text {
    color: var(--color-app-study-end);
  }
</style>
