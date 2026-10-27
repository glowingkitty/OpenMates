<script lang="ts">
  import { onMount, untrack } from 'svelte';
  import ChatMessageTimeline from './ChatMessageTimeline.svelte';
  import fixture, { variants } from './ChatMessageTimeline.preview';
  import type { TimelineEntry } from '../utils/chatTimeline';

  let { bookmarks = false, failSave = false, followUp = false }: { bookmarks?: boolean; failSave?: boolean; followUp?: boolean } = $props();
  const original = untrack(() => bookmarks ? variants.dense.entries : followUp ? fixture.entries.slice(0, 1) : fixture.entries);
  let bookmarkedIds = $state(untrack(() => new Set(bookmarks ? ['timeline-assistant-4711'] : [])));
  let entries = $state<TimelineEntry[]>(original);
  const displayed = $derived(entries.map(entry => ({ ...entry, bookmarked: bookmarkedIds.has(entry.response_id ?? '') })));
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
    const append = () => { entries = fixture.entries.slice(0, 2); };
    window.addEventListener('preview:timeline-follow-up', append);
    window.addEventListener('preview:timeline-prepend', prepend);
    return () => { window.removeEventListener('preview:timeline-prepend', prepend); window.removeEventListener('preview:timeline-follow-up', append); };
  });
</script>

<ChatMessageTimeline {...fixture} entries={displayed} answeredCount={entries.length} currentId={bookmarks ? 'timeline-user-4711' : fixture.currentId} {bookmarkedIds} onToggleBookmark={toggle} />
