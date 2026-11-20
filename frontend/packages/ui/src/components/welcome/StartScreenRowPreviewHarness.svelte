<!--
  StartScreenRowPreviewHarness.svelte — /dev/preview harness for the start-screen
  row (TASK-1321) with synthetic chats and inspirations. It uses the production
  rhythm (interleaveStartRow), StartScreenChatCard and StartScreenUpcomingEntry, so
  the focused component spec judges the real cards without a signed-in account.
  The route-level E2E covers the wiring inside ActiveChat.
-->
<script lang="ts">
  import StartScreenChatCard from './StartScreenChatCard.svelte';
  import StartScreenUpcomingEntry from './StartScreenUpcomingEntry.svelte';
  import { interleaveStartRow } from '../../utils/startScreenRow';

  type PreviewChat = { id: string; title: string; summary: string; category: string; icon: string; pinned?: boolean };
  type PreviewInspiration = { id: string; title: string; phrase: string; category: string; contentType: 'video' | 'wiki'; image: string | null };

  type Props = {
    ownCount: number;
    inspirationCount: number;
    showUpcoming: boolean;
    showInspirationMedia: boolean;
  };

  let { ownCount, inspirationCount, showUpcoming, showInspirationMedia }: Props = $props();

  const CHATS: PreviewChat[] = [
    { id: 'chat-garden', title: 'Balcony herb garden plan', summary: 'Which herbs grow well together on a sunny balcony and how often to water them.', category: 'life_coach_psychology', icon: 'sprout', pinned: true },
    { id: 'chat-trip', title: 'Weekend trip to the coast', summary: 'Train times, a cheap guesthouse and a short hiking route for Saturday.', category: 'activities', icon: 'map' },
    { id: 'chat-python', title: 'Speed up the CSV import', summary: 'Profiling showed the slow part is parsing dates; switch to a vectorised parser.', category: 'software_development', icon: 'code' },
    { id: 'chat-bread', title: 'Sourdough starter problems', summary: 'The starter smells like acetone. Feed more often and keep it warmer.', category: 'cooking_food', icon: 'chef-hat' },
    { id: 'chat-budget', title: 'Monthly budget review', summary: 'Groceries went up by 12 percent; two subscriptions can be cancelled.', category: 'finance', icon: 'wallet' },
    { id: 'chat-spanish', title: 'Spanish lessons: past tense', summary: 'Practice sentences for the preterite with common irregular verbs.', category: 'general_knowledge', icon: 'languages' },
    { id: 'chat-run', title: 'First 10k training plan', summary: 'Eight weeks, three runs a week, one long run on Sundays.', category: 'activities', icon: 'activity' },
    { id: 'chat-lamp', title: 'Fix the flickering desk lamp', summary: 'Likely a loose contact in the switch; check before replacing the bulb.', category: 'electrical_engineering', icon: 'lightbulb' },
    { id: 'chat-book', title: 'Book club: next pick', summary: 'Three short novels under 300 pages that are easy to discuss.', category: 'general_knowledge', icon: 'book-open' },
    { id: 'chat-desk', title: 'Standing desk comparison', summary: 'Two models within budget; the quieter motor wins for a shared flat.', category: 'design', icon: 'ruler' },
  ];

  const INSPIRATIONS: PreviewInspiration[] = [
    { id: 'insp-octopus', title: 'How octopuses change colour', phrase: 'Why can an octopus match a rock it has never seen?', category: 'science', contentType: 'video', image: null },
    { id: 'insp-bridge', title: 'The bridge that sings in the wind', phrase: 'What makes some bridges hum on stormy days?', category: 'history', contentType: 'wiki', image: null },
    { id: 'insp-bees', title: 'Bees count to four', phrase: 'How do researchers test whether bees understand numbers?', category: 'science', contentType: 'video', image: null },
  ];

  const MEDIA_IMAGE = 'data:image/svg+xml;utf8,' + encodeURIComponent(
    '<svg xmlns="http://www.w3.org/2000/svg" width="600" height="400"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#2b6cb0"/><stop offset="1" stop-color="#9f7aea"/></linearGradient></defs><rect width="600" height="400" fill="url(#g)"/><circle cx="420" cy="140" r="90" fill="#f6e05e" opacity="0.8"/><rect x="0" y="280" width="600" height="120" fill="#2c5282" opacity="0.7"/></svg>'
  );

  let own = $derived(CHATS.slice(0, ownCount));
  let inspirations = $derived(
    INSPIRATIONS.slice(0, inspirationCount).map((item) => ({ ...item, image: showInspirationMedia ? MEDIA_IMAGE : null }))
  );
  let entries = $derived(interleaveStartRow(own, inspirations));
  let lastActivated = $state('');
</script>

<div class="start-row-harness" data-testid="start-row-harness" data-last-activated={lastActivated}>
  <div class="harness-row start-row" data-testid="recent-chats-scroll-container">
    {#each entries as entry (entry.item.id)}
      {#if entry.kind === 'inspiration'}
        {@const inspiration = entry.item}
        <StartScreenChatCard
          testId="start-row-inspiration-card"
          title={inspiration.title}
          summary={inspiration.phrase}
          category={inspiration.category}
          mediaImageUrl={inspiration.image}
          badge={{ label: 'Daily inspiration', testId: 'start-row-inspiration-label', icon: inspiration.contentType === 'video' ? 'play' : 'book-open' }}
          dataAttributes={{ 'data-inspiration-id': inspiration.id, 'data-content-type': inspiration.contentType }}
          gestures={null}
          onActivate={() => (lastActivated = inspiration.id)}
        />
      {:else}
        {@const chat = entry.item}
        <StartScreenChatCard
          testId="resume-chat-large-card"
          title={chat.title}
          summary={chat.summary}
          category={chat.category}
          icon={chat.icon}
          chatId={chat.id}
          pinned={!!chat.pinned}
          gestures={null}
          onActivate={() => (lastActivated = chat.id)}
        />
      {/if}
    {/each}
  </div>
  {#if showUpcoming}
    <div class="harness-upcoming">
      <StartScreenUpcomingEntry
        title="Dentist appointment"
        timeLabel="Today, 15:30"
        appId="calendar"
        icon="calendar"
        category={null}
        variant="pill"
        onActivate={() => (lastActivated = 'upcoming')}
      />
    </div>
  {/if}
</div>

<style>
  .start-row-harness {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: var(--spacing-6);
    width: 100%;
    padding: var(--spacing-12) 0;
    background: var(--color-grey-20);
  }

  /* Mirrors .recent-chats-scroll-container.large-continue-cards.start-row in ActiveChat.svelte:
     the first card is centred. */
  .harness-row {
    display: flex;
    gap: var(--spacing-8);
    width: 100%;
    overflow-x: auto;
    scrollbar-width: none;
    padding: 17.5px 48px 17px calc(50% - 150px);
    box-sizing: border-box;
  }

  @media (max-width: 480px) {
    .harness-row {
      padding-left: calc(50% - min(140px, 38vw));
      padding-right: var(--spacing-8);
    }
  }

  .harness-upcoming {
    display: flex;
    justify-content: center;
    width: 100%;
    padding: 0 var(--spacing-8);
    box-sizing: border-box;
  }
</style>
