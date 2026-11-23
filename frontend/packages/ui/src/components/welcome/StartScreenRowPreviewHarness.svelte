<!--
  StartScreenRowPreviewHarness.svelte — /dev/preview harness for the start-screen
  row (TASK-1321) with synthetic chats and inspirations. It uses the production
  rhythm (interleaveStartRow, at most 10 cards), StartScreenChatCard, the row-end
  StartScreenRowActions, StartScreenUpcomingEntry and the suggestions below, so
  the focused component spec judges the real cards without a signed-in account.
  The route-level E2E covers the wiring inside ActiveChat. Running chats come first with
  the "Active" label; the "make active" control lets the spec record a chat becoming
  active (fade in from below at the front, others slide right; startRowMotion.ts).
-->
<script lang="ts">
  import StartScreenChatCard from './StartScreenChatCard.svelte';
  import StartScreenUpcomingEntry from './StartScreenUpcomingEntry.svelte';
  import StartScreenRowActions, { type StartScreenRowAction } from './StartScreenRowActions.svelte';
  import StartScreenChatSuggestions from './StartScreenChatSuggestions.svelte';
  import { onMount } from 'svelte';
  import { interleaveStartRow } from '../../utils/startScreenRow';
  import { startRowCardFlip, startRowCardIn } from '../../utils/startRowMotion';

  type PreviewChat = { id: string; title: string; summary: string; category: string; icon: string; pinned?: boolean };
  type PreviewInspiration = { id: string; title: string; phrase: string; category: string; contentType: 'video' | 'wiki' };

  type Props = {
    ownCount: number;
    inspirationCount: number;
    showUpcoming: boolean;
    /** Signed-out actions (Select interests, Show all) instead of Show all / Search. */
    guest: boolean;
    /** How many of the chats start as running (shown first, marked active). */
    activeCount?: number;
    /** Puts a draft-only chat (label plus draft text) first in the row. */
    draft?: boolean;
  };

  let { ownCount, inspirationCount, showUpcoming, guest, activeCount = 0, draft = false }: Props = $props();
  // Same 120-character cut as ActiveChat; long enough to need the third line.
  const DRAFT_TEXT = 'Can you help me plan a surprise birthday dinner for eight people next Saturday, with a vegetarian menu and a small budget?'.slice(0, 120);

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
    { id: 'insp-octopus', title: 'How octopuses change colour', phrase: 'Why can an octopus match a rock it has never seen?', category: 'science', contentType: 'video' },
    { id: 'insp-bridge', title: 'The bridge that sings in the wind', phrase: 'What makes some bridges hum on stormy days?', category: 'history', contentType: 'wiki' },
    { id: 'insp-bees', title: 'Bees count to four', phrase: 'How do researchers test whether bees understand numbers?', category: 'science', contentType: 'video' },
  ];

  type RowChat = PreviewChat & { key: string; active: boolean };
  // Chats made active with the control below; the fixture's first `activeCount` chats start active.
  let activatedIds = $state<string[]>([]);
  let activeIds = $derived([...activatedIds, ...CHATS.slice(0, activeCount).map((chat) => chat.id)]);
  let own = $derived<RowChat[]>([
    ...activeIds.map((id) => CHATS.find((chat) => chat.id === id)).filter((chat): chat is PreviewChat => !!chat).map((chat) => ({ ...chat, key: `active:${chat.id}`, active: true })),
    ...CHATS.slice(0, ownCount).filter((chat) => !activeIds.includes(chat.id)).map((chat) => ({ ...chat, key: `recent:${chat.id}`, active: false })),
  ]);
  let inspirations = $derived(INSPIRATIONS.slice(0, inspirationCount).map((inspiration) => ({ ...inspiration, key: `inspiration:${inspiration.id}` })));
  let entries = $derived(interleaveStartRow(own, inspirations));
  let motionEnabled = $state(false);
  onMount(() => {
    const timer = setTimeout(() => (motionEnabled = true), 300);
    return () => clearTimeout(timer);
  });
  /** Makes the last inactive chat of the row active, like a chat that starts running. */
  function activateNext(): void {
    const next = own.filter((chat) => !chat.active).at(-1);
    if (next) activatedIds = [next.id, ...activatedIds];
  }
  let lastActivated = $state('');
  let actions = $derived<StartScreenRowAction[]>(
    guest
      ? [
          { id: 'interests', label: 'Select interests', icon: 'heart', testId: 'guest-interest-select-interests', onActivate: () => (lastActivated = 'interests') },
          { id: 'show-all', label: 'Show all examples', icon: 'messages-square', testId: 'guest-show-all-examples', surface: 'chats', onActivate: () => (lastActivated = 'show-all') },
        ]
      : [
          { id: 'show-all', label: 'Show all chats', icon: 'messages-square', testId: 'chat-show-all', surface: 'chats', onActivate: () => (lastActivated = 'show-all') },
          { id: 'search', label: 'Search', icon: 'search', testId: 'chat-search', onActivate: () => (lastActivated = 'search') },
        ]
  );
</script>

<div class="start-row-harness" data-testid="start-row-harness" data-last-activated={lastActivated}>
  <div class="harness-row start-row" data-testid="recent-chats-scroll-container">
    {#if draft}
      <div class="harness-slot">
        <StartScreenChatCard
          testId="start-row-draft-card"
          title=""
          preview={{ label: 'Draft', text: DRAFT_TEXT }}
          gestures={null}
          onActivate={() => (lastActivated = 'draft')}
        />
      </div>
    {/if}
    {#each entries as entry (entry.item.key)}
      <div class="harness-slot" animate:startRowCardFlip={{ enabled: motionEnabled }} in:startRowCardIn={{ enabled: motionEnabled }}>
      {#if entry.kind === 'inspiration'}
        {@const inspiration = entry.item}
        <StartScreenChatCard
          testId="start-row-inspiration-card"
          title={inspiration.title}
          summary={inspiration.phrase}
          category={inspiration.category}
          badge={{ label: 'Daily inspiration', testId: 'start-row-inspiration-label', icon: inspiration.contentType === 'video' ? 'play' : 'book-open' }}
          dataAttributes={{ 'data-inspiration-id': inspiration.id, 'data-content-type': inspiration.contentType }}
          gestures={null}
          onActivate={() => (lastActivated = inspiration.id)}
        />
      {:else}
        {@const chat = entry.item}
        <StartScreenChatCard
          testId={chat.active ? 'start-row-active-card' : 'resume-chat-large-card'}
          title={chat.title}
          summary={chat.summary}
          category={chat.category}
          icon={chat.icon}
          chatId={chat.id}
          pinned={!!chat.pinned}
          active={chat.active ? { label: 'Active', testId: 'start-row-active-pill' } : null}
          gestures={null}
          onActivate={() => (lastActivated = chat.id)}
        />
      {/if}
      </div>
    {/each}
    <StartScreenRowActions testId="start-row-actions" {actions} />
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
  {#if activeCount > 0}
    <button type="button" class="harness-activate" data-testid="start-row-harness-activate" onclick={activateNext}>Make a chat active</button>
  {/if}
  <StartScreenChatSuggestions
    isAuthenticated={false}
    selectedInterestTagIds={[]}
    reloadKey="preview"
    onSuggestionClick={(suggestion) => (lastActivated = `suggestion:${suggestion}`)}
  />
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

  .harness-slot {
    display: flex;
    flex-shrink: 0;
  }

  .harness-activate {
    font-size: var(--font-size-xxs);
  }

  .harness-upcoming {
    display: flex;
    justify-content: center;
    width: 100%;
    padding: 0 var(--spacing-8);
    box-sizing: border-box;
  }
</style>
