<!--
  Isolated saved-preview evidence using production cards and the memory store.
  Synthetic decrypted entries seed the existing public store snapshot before
  cards mount. The real forget service and store deletion run unchanged.
  Only deletion transport is isolated; a failure variant rejects local storage.
  No account, save operation, reminder, or real saved entity is created.
-->
<script lang="ts">
  import { onMount, type Component } from 'svelte';
  import { get } from 'svelte/store';
  import { appSettingsMemoriesStore } from '../../stores/appSettingsMemoriesStore';
  import { notificationStore } from '../../stores/notificationStore';
  import { chatSyncService } from '../../services/chatSyncService';
  import { chatDB } from '../../services/db';
  import HomePreview from './home/HomeListingEmbedPreview.svelte';
  import HealthPreview from './health/HealthAppointmentEmbedPreview.svelte';
  import EventPreview from './events/EventEmbedPreview.svelte';
  import CodePreview from './code/CodeEmbedPreview.svelte';

  let { family = 'home', saved = true, failDelete = false, mode = 'chat', collidingKeys = false, deferSync = false }: {
    family?: 'home' | 'health' | 'events' | 'code'; saved?: boolean; failDelete?: boolean; mode?: 'chat' | 'grid'; collidingKeys?: boolean; deferSync?: boolean;
  } = $props();
  const embedId = 'saved-preview-fixture-result';
  const entryId = 'saved-preview-fixture-memory';
  const unrelatedId = 'saved-preview-fixture-other-memory';
  const title = 'Saved preview result';
  const itemType = 'saved_results';
  let ready = $state(false);
  let attempts = $state<string[]>([]);
  let expanded = $state(0);
  let menus = $state(0);
  const onFullscreen = () => { expanded += 1; };
  // Registry-style dynamic mounting keeps each production preview's own props.
  const preview = $derived.by(() => {
    if (family === 'health') return { component: HealthPreview, props: { id: embedId, name: title, speciality: 'General medicine', onFullscreen } };
    if (family === 'events') return { component: EventPreview, props: { id: embedId, event: { embed_id: embedId, title, date_start: '2026-10-30T11:00:00Z' }, onFullscreen } };
    if (family === 'code') return { component: CodePreview, props: { id: embedId, filename: 'Saved preview result with a deliberately long filename to verify marker clearance.py', language: 'python', codeContent: 'print("preview")', status: 'finished', onFullscreen } };
    return { component: HomePreview, props: { embed_id: embedId, title, price_label: '850 EUR/month', onSelect: onFullscreen } };
  });
  // Component contracts differ, as they do in the preview registry.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const renderable = (component: unknown): Component<any> => component as Component<any>;

  onMount(() => {
    const state = get(appSettingsMemoriesStore);
    const rows = [
      ...(saved ? [{ id: entryId, embed: embedId, title }] : []),
      { id: unrelatedId, embed: `${embedId}-unrelated`, title: 'Unrelated saved result' },
    ].map(row => ({ id: row.id, app_id: family, item_key: collidingKeys ? 'saved_results.shared' : `saved_results.${row.id}`,
      item_value: { embed_id: row.embed, title: row.title }, settings_group: itemType,
      created_at: 1, updated_at: 1, item_version: 1 }));
    // A repeated key must never let the earlier unrelated entry win lookup.
    if (collidingKeys) rows.reverse();
    // Seed only fixture-owned entries; retain any other entries in this snapshot.
    const groups = state.entriesByApp.get(family) ?? {};
    state.entriesByApp.set(family, { ...groups, [itemType]: [...(groups[itemType] ?? []), ...rows] });
    rows.forEach(row => state.decryptedEntries.set(row.id, row));
    const deleteLocal = chatDB.deleteAppSettingsMemoriesEntry;
    const sendDelete = chatSyncService.sendDeleteAppSettingsMemoriesEntry;
    const isolatedDelete: typeof deleteLocal = async function (id) {
      attempts = [...attempts, id];
      if (failDelete) return false;
      await chatDB.init({ skipOrphanDetection: true });
      return deleteLocal.call(chatDB, id);
    };
    chatDB.deleteAppSettingsMemoriesEntry = isolatedDelete;
    let releaseSync: (() => void) | undefined;
    const isolatedTransport = () => deferSync ? new Promise<boolean>(resolve => { releaseSync = () => resolve(true); }) : Promise.resolve(true);
    chatSyncService.sendDeleteAppSettingsMemoriesEntry = isolatedTransport;
    const onReleaseSync = () => releaseSync?.();
    window.addEventListener('saved-preview-release-delete', onReleaseSync);
    const onMenu = () => { menus += 1; };
    window.addEventListener('embed-context-menu', onMenu);
    ready = true;
    return () => {
      if (chatDB.deleteAppSettingsMemoriesEntry === isolatedDelete) chatDB.deleteAppSettingsMemoriesEntry = deleteLocal;
      if (chatSyncService.sendDeleteAppSettingsMemoriesEntry === isolatedTransport) chatSyncService.sendDeleteAppSettingsMemoriesEntry = sendDelete;
      window.removeEventListener('embed-context-menu', onMenu);
      window.removeEventListener('saved-preview-release-delete', onReleaseSync);
      releaseSync?.();
      const current = get(appSettingsMemoriesStore);
      rows.forEach(row => current.decryptedEntries.delete(row.id));
      const currentGroups = current.entriesByApp.get(family);
      if (currentGroups) currentGroups[itemType] = (currentGroups[itemType] ?? []).filter(row => !rows.some(own => own.id === row.id));
    };
  });
</script>

<div data-testid="saved-result-fixture" data-ready={ready} data-expanded={expanded} data-menus={menus}
  data-deletions={JSON.stringify(attempts)} data-unrelated-present={ready && $appSettingsMemoriesStore.decryptedEntries.has(unrelatedId)}>
  {#if ready}
    <div class:read-only-message={mode === 'chat'} class="cards" data-embed-result-context={mode === 'grid' ? 'results' : undefined}>
      {#each [0, 1] as index}
        {@const Preview = renderable(preview.component)}
        <div class="preview-host" data-testid={`saved-result-copy-${index}`}>
          <Preview {...preview.props} />
        </div>
      {/each}
    </div>
  {/if}
  <div data-testid="saved-result-notifications" aria-live="polite">
    {#each $notificationStore.notifications as notification}
      <p data-notification-type={notification.type}>{notification.message}</p>
    {/each}
  </div>
</div>

<style>
  .cards { display: flex; flex-wrap: wrap; gap: 20px; }
  .preview-host { width: 300px; container: embed-preview / inline-size; }
</style>
