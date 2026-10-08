<!-- Account-free proof of the production chat row and chatListCache read boundary. -->
<script lang="ts">
  import { onMount } from 'svelte';
  import type { Chat as ChatRecord } from '../../types/chat';
  import { chatListCache } from '../../services/chatListCache';
  import Chat from './Chat.svelte';

  const makeChat = (chat_id: string, title: string) => ({
    chat_id, title, encrypted_title: null, encrypted_chat_key: null,
    messages_v: 0, title_v: 0, unread_count: 0,
    created_at: 1700000000, updated_at: 1700000000,
    last_edited_overall_timestamp: 1700000000,
  }) as ChatRecord;
  const kept = makeChat('0fb6086b-120d-4e02-ad88-0b2cf8fffe2c', 'Launch copy');
  const deleted = makeChat('71ecda2f-bd9f-49c1-a521-15d531599a13', 'README review');
  const later = makeChat('9e27f137-2eb6-409c-9bf1-d51e073aa94d', 'Saved notes');
  const staleSnapshot = [kept, deleted];
  let visibleChats: ChatRecord[] = $state([]);
  let finishRead: ((chats: ChatRecord[]) => void) | null = null;

  function refresh(): void {
    visibleChats = chatListCache.getCache(false) ?? [];
  }

  onMount(() => {
    chatListCache.clear();
    chatListCache.setCache(staleSnapshot);
    refresh();
    return () => chatListCache.clear();
  });

  function startRead(): void {
    const version = chatListCache.getContextVersion();
    const read = new Promise<ChatRecord[]>((resolve) => { finishRead = resolve; });
    void read.then((chats) => {
      chatListCache.setCacheIfUnchanged(chats, version);
      refresh();
    });
  }

  function confirmDelete(): void {
    chatListCache.markChatDeleted(deleted.chat_id);
    refresh();
  }

  function completeOldRead(): void {
    finishRead?.(staleSnapshot);
    finishRead = null;
  }

  function refreshAfterDelete(): void {
    chatListCache.setCacheIfUnchanged([...staleSnapshot, later], chatListCache.getContextVersion());
    refresh();
  }
</script>

<div data-testid="chat-list-deletion-preview" style="width: 100%">
  {#each visibleChats as chat (chat.chat_id)}
    <Chat {chat} highlightedTitle={chat.title ?? ''} />
  {/each}
</div>
<button type="button" data-testid="preview-start-chat-read" onclick={startRead}>Start read</button>
<button type="button" data-testid="preview-delete-chat" onclick={confirmDelete}>Confirm deletion</button>
<button type="button" data-testid="preview-complete-old-read" onclick={completeOldRead}>Complete old read</button>
<button type="button" data-testid="preview-refresh-after-delete" onclick={refreshAfterDelete}>Refresh list</button>
