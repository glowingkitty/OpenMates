<!--
  Saved preview action shared by every result toolbar.
  Shows the Saved heart when the embed carries the encrypted saved flag;
  clicking it clears the flag through savedEmbedService. Unsaved embeds
  show the shared "more" action.
-->
<script lang="ts">
  import { text } from '../../i18n/translations';
  import { toggleEmbedSaved } from '../../services/savedEmbedService';

  let { embedId, saved, onMore, decorative = false }: { embedId: string; saved: boolean; onMore: (event: MouseEvent) => void; decorative?: boolean } = $props();
  let updating = $state(false);

  function handleActionClick(event: MouseEvent) {
    if (updating) { event.stopPropagation(); return; }
    if (saved) void unsave(event);
    else onMore(event);
  }

  async function unsave(event: MouseEvent) {
    event.stopPropagation();
    if (updating) return;
    updating = true;
    try {
      await toggleEmbedSaved(embedId);
    } finally {
      updating = false;
    }
  }
</script>

{#if decorative && saved}
  <span class="saved-memory-marker" aria-hidden="true" data-testid="result-preview-saved-marker"><span style:mask-image="var(--icon-url-heart)"></span></span>
{:else}
  <button
    type="button"
    class:saved-memory-action={!!saved}
    aria-label={$text(saved ? 'embeds.saved_item' : 'common.more_actions')}
    aria-pressed={saved ? 'true' : undefined}
    aria-busy={updating || undefined}
    aria-disabled={updating || undefined}
    onclick={handleActionClick}
    data-testid={saved ? 'result-preview-forget' : 'result-preview-more'}
  ><span class="clickable-icon" style:mask-image={saved ? 'var(--icon-url-heart)' : 'var(--icon-url-more)'} aria-hidden="true"></span></button>
{/if}

<style>
  .saved-memory-marker { position: absolute; top: var(--spacing-3); right: var(--spacing-3); z-index: 3; display: grid; place-items: center; width: 22px; height: 22px; color: var(--color-app-health-start); pointer-events: none; }
  .saved-memory-marker > span { display: block; width: 22px; height: 22px; background: currentColor; mask-size: contain; mask-repeat: no-repeat; mask-position: center; }
</style>
