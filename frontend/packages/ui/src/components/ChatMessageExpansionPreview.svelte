<script lang="ts">
  import ChatMessage from './ChatMessage.svelte';
  import type { MessageStatus } from '../types/chat';
  let { containerWidth = 700 }: { containerWidth?: number } = $props();

  const text = 'Explain these saved appointments.\n\nResult context (data supplied by the user):\n' +
    'Verified appointment data. '.repeat(55) + '\nSynthetic Practice alpha. Contact [EMAIL_PREVIEW].';
  let status = $state<MessageStatus>('sending');
  let piiRevealed = $state(false);
  const document = { type: 'doc', content: [{ type: 'paragraph', content: [{ type: 'text', text: text.slice(0, 1000) + '...' }] }] };
  let original = $state({ message_id: 'preview-full-user', chat_id: 'preview-full-chat', role: 'user' as const,
    content: text, status: 'sending' as MessageStatus, created_at: 1 });
  function refresh(next: MessageStatus) { status = next; original = { ...original, status: next }; }
</script>
<div class="controls">
  <button onclick={() => refresh('processing')}>Refresh processing</button>
  <button onclick={() => refresh('synced')}>Refresh synced</button>
  <button onclick={() => { piiRevealed = !piiRevealed; }}>Toggle private data</button>
</div>
<div data-testid="expansion-message" data-status={status}>
  <ChatMessage role="user" content={document} {status} original_message={original}
    messageId={original.message_id} is_truncated={true} {containerWidth}
    piiMappings={[{ placeholder: '[EMAIL_PREVIEW]', original: 'person@example.test', type: 'EMAIL' }]}
    {piiRevealed} />
</div>
<style>.controls { display:flex; flex-wrap:wrap; gap:12px; margin-bottom:16px; }</style>
