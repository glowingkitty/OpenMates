<!--
  Saved preview action shared by every result toolbar.
  The owning shell supplies its reference from the real memory store.
  Forgetting delegates to the existing memory service and notification flow;
  no optimistic saved flag or saved-entity deletion is introduced here.
-->
<script lang="ts">
  import { text } from '../../i18n/translations';
  import { notificationStore } from '../../stores/notificationStore';
  import { forgetEmbedMemory, type SavedEmbedMemoryReference } from '../../services/savedEmbedMemoryService';

  let { memory, onMore, decorative = false }: { memory?: SavedEmbedMemoryReference; onMore: (event: MouseEvent) => void; decorative?: boolean } = $props();
  let forgetting = $state(false);

  function handleActionClick(event: MouseEvent) {
    if (forgetting) { event.stopPropagation(); return; }
    if (memory) void forget(event);
    else onMore(event);
  }

  async function forget(event: MouseEvent) {
    event.stopPropagation();
    if (!memory || forgetting) return;
    forgetting = true;
    try {
      await forgetEmbedMemory(memory);
    } catch (error) {
      console.error('[SavedEmbedPreviewAction] Failed to forget saved memory:', error);
      notificationStore.error('Failed to update saved memory.');
    } finally {
      forgetting = false;
    }
  }
</script>

{#if decorative && memory}
  <span class="saved-memory-marker" aria-hidden="true" data-testid="result-preview-saved-marker"><span style:mask-image="var(--icon-url-heart)"></span></span>
{:else}
  <button
    type="button"
    class:saved-memory-action={!!memory}
    aria-label={$text(memory ? 'embeds.forget_memory' : 'common.more_actions')}
    aria-pressed={memory ? 'true' : undefined}
    aria-busy={forgetting || undefined}
    aria-disabled={forgetting || undefined}
    onclick={handleActionClick}
    data-testid={memory ? 'result-preview-forget' : 'result-preview-more'}
  ><span class="clickable-icon" style:mask-image={memory ? 'var(--icon-url-heart)' : 'var(--icon-url-more)'} aria-hidden="true"></span></button>
{/if}

<style>
  .saved-memory-marker { position: absolute; top: var(--spacing-3); right: var(--spacing-3); z-index: 3; display: grid; place-items: center; width: 22px; height: 22px; color: var(--color-app-health-start); pointer-events: none; }
  .saved-memory-marker > span { display: block; width: 22px; height: 22px; background: currentColor; mask-size: contain; mask-repeat: no-repeat; mask-position: center; }
</style>
