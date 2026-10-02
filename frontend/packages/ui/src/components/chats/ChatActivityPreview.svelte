<!--
  Dev-only fixture renders the production chat row during task lifecycle changes.
  No account, transport or transcript is needed.
  Activity uses the same observable task map as normal WebSocket handlers.
  Cleanup leaves the preview's stores empty.
  Used by isolated component CI.
-->
<script lang="ts">
  import { onMount } from 'svelte';
  import type { Chat as ChatRecord } from '../../types/chat';
  import { chatSyncService } from '../../services/chatSyncService';
  import Chat from './Chat.svelte';
  const chat = { chat_id: '0fb6086b-120d-4e02-ad88-0b2cf8fffe2c', title: 'Launch copy',
    encrypted_title: null, encrypted_chat_key: null, messages_v: 0, title_v: 0,
    unread_count: 0, created_at: 1700000000, updated_at: 1700000000,
    last_edited_overall_timestamp: 1700000000 } as ChatRecord;
  onMount(() => {
    chatSyncService.activeAITasks.set(chat.chat_id, { taskId: 'preview-task', userMessageId: '' });
    return () => { chatSyncService.activeAITasks.delete(chat.chat_id); };
  });
</script>
<Chat {chat} highlightedTitle="Launch copy" />
<button type="button" data-testid="preview-complete-chat" onclick={() => chatSyncService.activeAITasks.delete(chat.chat_id)}>Complete processing</button>
