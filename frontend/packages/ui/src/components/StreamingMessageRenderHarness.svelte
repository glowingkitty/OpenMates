<!--
  frontend/packages/ui/src/components/StreamingMessageRenderHarness.svelte
  Deterministic deployed-browser harness for the assistant streaming pipeline.
  It drives ChatHistory through realistic cumulative snapshots without backend,
  provider, persisted-chat, or private user data dependencies.
  Spec: docs/specs/streaming-message-render-convergence/spec.yml
-->

<script lang="ts">
  import { onMount } from 'svelte';
  import ChatHistory from './ChatHistory.svelte';
  import type { Message } from '../types/chat';
  import { getStreamingRenderMetrics } from '../message_parsing/streamingRenderMetrics';

  const CHUNK_INTERVAL_MS = 35;
  const CHUNK_SIZE = 240;
  const TARGET_CHARACTER_COUNT = 10_000;
  const MESSAGE_ID = 'streaming-render-harness-message';
  const CHAT_ID = 'streaming-render-harness-chat';
  const PREFIX = [
    'Streaming render benchmark with a complete preview:',
    '',
  ].join('\n');
  const TARGET_CONTENT = `${PREFIX}${'Bounded canonical rendering remains responsive. '.repeat(240)}`.slice(0, TARGET_CHARACTER_COUNT);

  type ChatHistoryApi = {
    updateMessages(messages: Message[]): void;
  };

  let chatHistory: ChatHistoryApi;
  let phase = $state<'waiting' | 'streaming' | 'complete'>('waiting');

  function message(content: string, status: Message['status']): Message {
    return {
      message_id: MESSAGE_ID,
      role: 'assistant',
      content,
      status,
    } as Message;
  }

  onMount(() => {
    const metrics = getStreamingRenderMetrics();
    if (metrics) {
      for (const key of Object.keys(metrics) as Array<keyof typeof metrics>) metrics[key] = 0;
    }
    performance.clearMeasures('openmates.streaming.compile');
    performance.clearMeasures('openmates.streaming.apply');

    let characterCount = CHUNK_SIZE;
    phase = 'streaming';
    chatHistory.updateMessages([message(TARGET_CONTENT.slice(0, characterCount), 'streaming')]);
    const timer = setInterval(() => {
      characterCount = Math.min(characterCount + CHUNK_SIZE, TARGET_CONTENT.length);
      const isComplete = characterCount === TARGET_CONTENT.length;
      const status: Message['status'] = isComplete ? 'synced' : 'streaming';
      chatHistory.updateMessages([message(TARGET_CONTENT.slice(0, characterCount), status)]);
      if (isComplete) {
        clearInterval(timer);
        phase = 'complete';
      }
    }, CHUNK_INTERVAL_MS);

    return () => clearInterval(timer);
  });
</script>

<main data-testid="streaming-render-harness" data-phase={phase}>
  <ChatHistory bind:this={chatHistory} currentChatId={CHAT_ID} containerWidth={960} />
</main>

<style>
  main {
    width: min(100%, 960px);
    height: 760px;
    margin: 0 auto;
  }
</style>
