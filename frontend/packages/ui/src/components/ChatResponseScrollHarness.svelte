<!-- Deterministic header/stream ordering for response-scroll verification. -->
<script lang="ts">
  import ChatHistory from './ChatHistory.svelte';
  import type { Message, ProcessingPhase } from '../types/chat';

  const chatId = 'preview-response-scroll';
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
  let history: { updateMessages(messages: Message[], isNewChat?: boolean): void };
  let titlePending = $state(true);
  let phase = $state<ProcessingPhase>(null);
  let chunks = 0;
  let responseContent = '';

  function send() {
    phase = { phase: 'sending', statusLines: ['Sending…'] };
    history.updateMessages([user], true);
  }

  function stream() {
    phase = null;
    chunks += 1;
    responseContent += chunks === 1 ? 'Here is the beginning of the answer.' :
      `\n\nStream update ${chunks}.` + '\n\nThe response keeps building below the opening.'.repeat(12);
    history.updateMessages([user, assistant(responseContent)]);
  }
</script>

<main>
  <nav aria-label="Response scroll fixture">
    <button type="button" data-testid="send-prompt" onclick={send}>Send prompt</button>
    <button type="button" data-testid="update-header" onclick={() => { titlePending = false; }}>Update header</button>
    <button type="button" data-testid="stream-response" onclick={stream}>Stream response</button>
    <button type="button" data-testid="clear-chat" onclick={() => history.updateMessages([])}>Clear chat</button>
  </nav>
  <section>
    <ChatHistory bind:this={history} currentChatId={chatId}
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
