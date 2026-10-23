<script lang="ts">
  import { onMount, untrack } from 'svelte';
  import ChatMessageTimeline from './ChatMessageTimeline.svelte';
  import fixture, { variants } from './ChatMessageTimeline.preview';
  import type { TimelineEntry } from '../utils/chatTimeline';

  let { bookmarks = false, failSave = false }: { bookmarks?: boolean; failSave?: boolean } = $props();
  const original = untrack(() => bookmarks ? variants.dense.entries : fixture.entries);
  let bookmarkedIds = $state(untrack(() => new Set(bookmarks ? ['timeline-user-4711'] : [])));
  let entries = $state<TimelineEntry[]>(original);
  const displayed = $derived(entries.map(entry => ({ ...entry, bookmarked: bookmarkedIds.has(entry.message_id) })));
  let attempts = 0;
  async function toggle(messageId: string): Promise<void> {
    if (failSave && attempts++ === 0) throw new Error('Fictional offline save');
    const next = new Set(bookmarkedIds);
    if (next.has(messageId)) next.delete(messageId); else next.add(messageId);
    bookmarkedIds = next;
  }
  let batch = 0;
  onMount(() => {
    const prepend = () => {
      const oldest = entries[0].created_at;
      const generation = ++batch;
      entries = [...Array.from({ length: 24 }, (_, index): TimelineEntry => ({
        message_id: `timeline-earlier-${generation}-${index}`,
        created_at: oldest - (24 - index) * 10, role: 'user',
      })), ...entries];
    };
    window.addEventListener('preview:timeline-prepend', prepend);
    return () => window.removeEventListener('preview:timeline-prepend', prepend);
  });
</script>

<ChatMessageTimeline {...fixture} entries={displayed} {bookmarkedIds} onToggleBookmark={toggle} />
