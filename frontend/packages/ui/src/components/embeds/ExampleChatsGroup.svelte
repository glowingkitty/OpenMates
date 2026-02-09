<!--
  frontend/packages/ui/src/components/embeds/ExampleChatsGroup.svelte
  
  A horizontal scrollable container displaying ChatEmbedPreview cards
  for EXAMPLE CHATS (community demos fetched from server).
  
  This component is rendered within demo chat messages when the
  [[example_chats_group]] placeholder is encountered.
  
  Only shows community demo chats (the "EXAMPLE CHATS" section in the sidebar),
  NOT intro chats (which are the static "For everyone", "For developers", etc.).
  
  Each card shows:
  - Chat summary (AI-generated description) in the center content area
  - Bottom bar with consistent chat icon + title + small category circle
  
  Scrolling behavior matches the standard embed group layout used by
  other embed types (smooth horizontal scroll, no snap).
-->

<script lang="ts">
  import ChatEmbedPreview from './ChatEmbedPreview.svelte';
  import { getAllCommunityDemoChats } from '../../demo_chats';
  import { communityDemoStore } from '../../demo_chats/communityDemoStore';
  import { activeChatStore } from '../../stores/activeChatStore';
  import { getCommunityDemoChat, getCommunityDemoMessages } from '../../demo_chats/communityDemoStore';
  
  /**
   * Props interface for ExampleChatsGroup
   */
  interface Props {
    /** Current chat ID to exclude from the list */
    excludeChatId?: string;
  }
  
  let {
    excludeChatId = 'demo-for-everyone'
  }: Props = $props();
  
  // Reference communityDemoStore for reactivity
  let _communityDemoStoreValue = $derived($communityDemoStore);
  
  // Get community demo chats (example chats) to display, excluding current chat
  // These are already Chat objects with cleartext fields (title, category, icon, chat_summary)
  // IMPORTANT: Do NOT include INTRO_CHATS here - only community demos from the server
  let exampleChats = $derived((() => {
    // Ensure reactivity by referencing the store
    void _communityDemoStoreValue;
    
    // Get community demo chats from the store
    const communityChats = getAllCommunityDemoChats();
    
    // Filter out the current chat and return as-is (already Chat objects)
    return communityChats.filter(chat => chat.chat_id !== excludeChatId);
  })());
  
  /**
   * Get the preview text for a chat embed card.
   * Prefers the chat_summary (AI-generated description of the chat topic)
   * over the first user message, as the summary is more informative
   * and matches the Figma design reference.
   */
  function getPreviewText(chatId: string, chatSummary: string | null | undefined): string {
    // Prefer summary - it's a concise AI-generated description of the chat topic
    if (chatSummary) {
      return chatSummary;
    }
    
    // Fall back to first user message if no summary available
    const messages = getCommunityDemoMessages(chatId);
    const firstUserMsg = messages.find(m => m.role === 'user');
    if (firstUserMsg && firstUserMsg.content) {
      return firstUserMsg.content;
    }
    
    return '';
  }
  
  // Handle click on a chat card - navigate to the demo chat
  // CRITICAL: Must both update the sidebar highlight AND trigger chat loading
  // activeChatStore.setActiveChat() alone only updates the store + URL hash,
  // but the hashchange handler ignores programmatic hash updates (isProgrammaticHashUpdate).
  // We need to dispatch a window event so +page.svelte can call activeChat.loadChat().
  function handleChatClick(chatId: string) {
    console.debug('[ExampleChatsGroup] Chat clicked:', chatId);
    
    // Get the full Chat object from the community demo store
    const chat = getCommunityDemoChat(chatId);
    if (!chat) {
      console.warn('[ExampleChatsGroup] Chat not found in community demo store:', chatId);
      return;
    }
    
    // Update sidebar highlight via activeChatStore (also updates URL hash)
    activeChatStore.setActiveChat(chatId);
    
    // Dispatch event to trigger chat loading in +page.svelte
    // This is needed because activeChatStore.setActiveChat() triggers a programmatic
    // hash update that the hashchange handler intentionally ignores (to prevent loops)
    window.dispatchEvent(new CustomEvent('demoChatSelected', {
      detail: { chat },
      bubbles: true,
      composed: true
    }));
  }
</script>

{#if exampleChats.length > 0}
  <div class="example-chats-group-wrapper">
    <div class="example-chats-group">
      {#each exampleChats as chat (chat.chat_id)}
        <ChatEmbedPreview
          chatId={chat.chat_id}
          title={chat.title || ''}
          previewText={getPreviewText(chat.chat_id, chat.chat_summary)}
          category={chat.category || 'general_knowledge'}
          iconName={chat.icon || 'message-circle'}
          onClick={handleChatClick}
        />
      {/each}
    </div>
  </div>
{/if}

<style>
  .example-chats-group-wrapper {
    /* Full width of the message content area */
    width: 100%;
    margin: 16px 0;
    /* Needed for proper overflow handling */
    overflow: hidden;
  }
  
  /* Match the standard embed group scroll container layout:
     - Smooth horizontal scrolling (no snap)
     - Same gap, padding, and scrollbar styling as group-scroll-container */
  .example-chats-group {
    display: flex;
    gap: 8px;
    align-items: flex-start;
    overflow-x: auto;
    overflow-y: hidden;
    padding: 4px 0;
    scrollbar-width: thin;
    scrollbar-color: var(--color-grey-60) transparent;
  }
  
  /* Custom scrollbar styling for WebKit browsers (matches embed groups) */
  .example-chats-group::-webkit-scrollbar {
    height: 4px;
  }
  
  .example-chats-group::-webkit-scrollbar-track {
    background: transparent;
  }
  
  .example-chats-group::-webkit-scrollbar-thumb {
    background-color: var(--color-grey-60);
    border-radius: 2px;
  }
  
  /* Ensure cards don't shrink */
  .example-chats-group > :global(*) {
    flex-shrink: 0;
  }
</style>
