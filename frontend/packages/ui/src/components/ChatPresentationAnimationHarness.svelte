<!-- Deterministic, private-data-free preview for the two chat presentation animations. -->
<script lang="ts">
  import ChatHistory from './ChatHistory.svelte';
  import type { Message } from '../types/chat';

  const chatId = 'preview-chat-presentation-animation';
  const savedUser = {
    message_id: 'saved-user', chat_id: chatId, role: 'user',
    content: 'A saved question.', status: 'synced'
  } as Message;
  const savedAssistant = {
    message_id: 'saved-assistant', chat_id: chatId, role: 'assistant',
    content: 'A saved answer.', status: 'synced'
  } as Message;
  const liveUser = {
    message_id: 'live-user', chat_id: chatId, role: 'user',
    content: 'Write a short response.', status: 'sending'
  } as Message;
  const assistant = (content: string, status: Message['status'] = 'streaming') => ({
    message_id: 'live-assistant', chat_id: chatId, role: 'assistant', content, status
  }) as Message;

  let history: { updateMessages(messages: Message[], isNewChat?: boolean): void };
  let current = $state<Message[]>([]);

  function render(messages: Message[], isNewChat = false) {
    current = messages;
    history.updateMessages(messages, isNewChat);
  }
</script>

<main data-testid="chat-presentation-animation-harness">
  <nav>
    <button type="button" data-testid="load-saved-history" onclick={() => render([savedUser, savedAssistant])}>Load saved history</button>
    <button type="button" data-testid="append-saved-row" onclick={() => render([...current, { ...savedUser, message_id: 'later-saved-user', content: 'A later synced row.' }])}>Append synced row</button>
    <button type="button" data-testid="start-live-stream" onclick={() => render([liveUser, assistant('Stable opening.')], true)}>Start stream</button>
    <button type="button" data-testid="append-live-chunk" onclick={() => render([liveUser, assistant('Stable opening. New chunk.')])}>Append chunk</button>
    <button type="button" data-testid="append-second-chunk" onclick={() => render([liveUser, assistant('Stable opening. New chunk. Another chunk.')])}>Append second chunk</button>
    <button type="button" data-testid="finish-live-stream" onclick={() => render([liveUser, assistant('Stable opening. New chunk. Another chunk.', 'synced')])}>Finish stream</button>
  </nav>
  <section>
    <ChatHistory bind:this={history} currentChatId={chatId} containerWidth={760} />
  </section>
</main>

<style>
  main { width: min(100%, 900px); height: 700px; margin: 0 auto; }
  nav { display: flex; flex-wrap: wrap; gap: 8px; padding: 12px; }
  section { position: relative; height: 620px; }
</style>
