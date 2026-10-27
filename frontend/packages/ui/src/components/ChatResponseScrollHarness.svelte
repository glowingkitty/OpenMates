<!-- Deterministic header/stream ordering for response-scroll verification. -->
<script lang="ts">
  import { untrack } from 'svelte';
  import ChatHistory from './ChatHistory.svelte';
  import ChatTimelineToggle from './ChatTimelineToggle.svelte';
  import type { Message, ProcessingPhase } from '../types/chat';

  let { existing = false }: { existing?: boolean } = $props();
  const chatId = 'preview-response-scroll';
  const prior: Message[] = Array.from({ length: 6 }, (_, index) => ({
    message_id: `prior-${index}`, chat_id: chatId, role: index % 2 ? 'assistant' : 'user',
    created_at: 1788870000 + index, status: 'synced',
    content: index % 2 ? 'An earlier answer.\n\n'.repeat(30) : `Earlier question ${index / 2 + 1}`,
  }));
  const user: Message = {
    message_id: 'scroll-user', chat_id: chatId, role: 'user', created_at: 1788870532,
    status: 'sending', content: [
      'First requirement.', 'Second requirement.', 'Third requirement.',
      'Fourth requirement.', 'Keep the answer clear.', 'Start with a summary.'
    ].join('  \n'),
  };
  const assistant = (content: string): Message => ({
    message_id: 'scroll-assistant', chat_id: chatId, role: 'assistant',
    user_message_id: user.message_id, created_at: user.created_at + 1,
    status: 'streaming', content,
  });
  let history: { updateMessages(messages: Message[], isNewChat?: boolean): void; revealSubmittedMessage(id: string): Promise<void> };
  let titlePending = $state(untrack(() => !existing));
  let phase = $state<ProcessingPhase>(null);
  let chunks = 0;
  let responseContent = '';
  let timelineOpen = $state(false);
  let timelineAvailable = $state(false);
  let timelineNarrow = $state(false);
  const timelinePanelId = 'response-scroll-timeline';

  function send() {
    phase = { phase: 'sending', statusLines: ['Sending…'] };
    history.updateMessages([...(existing ? prior : []), user], !existing);
    if (existing) void history.revealSubmittedMessage(user.message_id);
  }

  function stream() {
    phase = null;
    chunks += 1;
    responseContent += chunks === 1 ? 'Here is the beginning of the answer.' :
      `\n\nStream update ${chunks}.` + '\n\nThe response keeps building below the opening.'.repeat(12);
    history.updateMessages([...(existing ? prior : []), user, assistant(responseContent)]);
  }
</script>

<main>
  <nav aria-label="Response scroll fixture">
    {#if existing && timelineAvailable && timelineNarrow}
      <ChatTimelineToggle open={timelineOpen} controls={timelinePanelId} onToggle={() => timelineOpen = !timelineOpen} />
    {/if}
    <button type="button" data-testid="send-prompt" onclick={send}>Send prompt</button>
    <button type="button" data-testid="update-header" onclick={() => { titlePending = false; }}>Update header</button>
    <button type="button" data-testid="stream-response" onclick={stream}>Stream response</button>
    <button type="button" data-testid="clear-chat" onclick={() => history.updateMessages([])}>Clear chat</button>
  </nav>
  <section>
    <ChatHistory bind:this={history} currentChatId={chatId} bind:timelineOverlayOpen={timelineOpen} {timelinePanelId}
      on:timelineStateChange={(event) => { timelineAvailable = event.detail.available; timelineNarrow = event.detail.narrow; }}
      sourceMessages={existing ? prior : []}
      chatTitle={titlePending ? '' : 'A clear summary'}
      chatSummary={titlePending ? null : 'Answer the six requirements clearly.'}
      isNewChatGeneratingTitle={titlePending} processingPhase={phase} />
  </section>
</main>

<style>
  main { width: 100%; height: 100%; display: flex; flex-direction: column; }
  nav { display: flex; flex-wrap: wrap; gap: var(--spacing-2); padding: var(--spacing-3); }
  section { position: relative; flex: 1; min-height: 0; }
</style>
