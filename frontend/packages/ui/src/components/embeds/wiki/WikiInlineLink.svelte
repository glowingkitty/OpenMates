<script lang="ts">
  // frontend/packages/ui/src/components/embeds/wiki/WikiInlineLink.svelte
  //
  // Compact inline Wikipedia topic link rendered inside ReadOnlyMessage.
  //
  // Visuals (left to right):
  //   1. Small 20 px circular badge: Wikipedia blue background + white "W" letter
  //   2. Display text as a blue-tinted clickable link
  //
  // On click: dispatches a document-level "wikifullscreen" CustomEvent so
  // ActiveChat can open the Wikipedia fullscreen panel — same event-dispatch
  // pattern used by EmbedInlineLink for embed references.

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
  <!-- Small circular Wikipedia badge -->
  <span class="wiki-inline-badge" aria-hidden="true">W</span>
  <!-- Blue display text -->
  <span class="wiki-inline-text">{displayText}</span>
</span>

<style>
  /* Outer wrapper — true inline so it flows naturally within paragraph text. */
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

  /* 20 px circular Wikipedia badge — blue background with white "W" letter */
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
    background: #3366CC;
    color: white;
    font-size: 11px;
    font-weight: 700;
    line-height: 1;
  }

  /* Display text — solid blue link colour */
  .wiki-inline-text {
    display: inline;
    font-size: inherit;
    font-weight: 500;
    line-height: inherit;
    color: #3366CC;
  }

  /* Dark mode: brighter blue for contrast on dark backgrounds */
  :global([data-theme="dark"]) .wiki-inline-text {
    color: #6699FF;
  }
</style>
