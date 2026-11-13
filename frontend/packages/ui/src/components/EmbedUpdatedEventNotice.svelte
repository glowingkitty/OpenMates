<!--
  frontend/packages/ui/src/components/EmbedUpdatedEventNotice.svelte

  Chat-history row for the "embed updated" system event (spec
  embed-user-edits.event.chat-notice / .event.collapse). One quiet, compact,
  centred line such as "Image enhanced · version 3" or
  "Slides edited 4 times · version 7". Pure presentation: the group comes from
  the client core's group_embed_updated_events, onOpen opens the embed.
-->
<script lang="ts">
  import { text } from '../i18n/translations';
  import SystemMessageNotice from './SystemMessageNotice.svelte';
  import type { EmbedUpdatedGroup } from './embedUpdatedGroup';

  let { group, onOpen }: {
    group: EmbedUpdatedGroup;
    onOpen?: () => void;
  } = $props();

  let label = $derived.by(() => {
    const kind = $text(`embed_user_edits.kind.${group.embed_kind}`);
    const version = group.latest_version;
    if (group.change_count > 1) {
      const count = group.change_count;
      return group.latest_action === 'edit'
        ? $text('embed_user_edits.event.edit_many', { values: { kind, count, version } })
        : $text('embed_user_edits.event.updated_many', { values: { kind, count, version } });
    }
    if (group.latest_action === 'restore') {
      const restoredFrom = group.restored_from;
      return restoredFrom === undefined
        ? $text('embed_user_edits.event.restore_plain', { values: { kind, version } })
        : $text('embed_user_edits.event.restore', { values: { kind, version, from: restoredFrom } });
    }
    return $text(`embed_user_edits.event.${group.latest_action}`, { values: { kind, version } });
  });
</script>

<div class="embed-updated-event" data-testid="embed-updated-event" data-action={group.latest_action}
  data-change-count={group.change_count}>
  <SystemMessageNotice>
    {#if onOpen}
      <button type="button" class="open" aria-label={`${label}. ${$text('embed_user_edits.event.open')}`}
        onclick={onOpen}>{label}</button>
    {:else}
      {label}
    {/if}
  </SystemMessageNotice>
</div>

<style>
  .embed-updated-event { display: flex; justify-content: center; width: 100%; }
  .open {
    all: unset;
    cursor: pointer;
    border-radius: var(--radius-3);
  }
  .open:hover { color: var(--color-grey-80); text-decoration: underline; }
  .open:focus-visible { outline: 2px solid var(--color-primary-start); outline-offset: 2px; }
</style>
