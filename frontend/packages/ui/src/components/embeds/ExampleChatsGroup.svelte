<!--
  frontend/packages/ui/src/components/embeds/ExampleChatsGroup.svelte
  
  A horizontal scrollable container displaying a group of ChatEmbedPreview
  components for example/demo chats.
  
  This component is rendered within demo chat messages when the
  {example_chats_group} placeholder is encountered.
  
  Features:
  - Horizontal scrolling with smooth scrolling behavior
  - Touch-friendly scrolling on mobile
  - Displays community demo chats and static intro chats (excluding the current chat)
  - Click on a chat card navigates to that demo chat
-->

<script lang="ts">
import ChatEmbedPreview from './ChatEmbedPreview.svelte';
  import { getAllCommunityDemoChats, INTRO_CHATS } from '../../demo_chats';
  import { communityDemoStore } from '../../demo_chats/communityDemoStore';
  import type { DemoChat } from '../../demo_chats/types';
  import { activeChatStore } from '../../stores/activeChatStore';
  
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
  
  // Get all example chats to display (excluding current chat and legal chats)
  let exampleChats = $derived((() => {
    // Ensure reactivity by referencing the store
    void _communityDemoStoreValue;
    
    // Get static intro chats (excluding the current chat)
    const introDemoChats: DemoChat[] = INTRO_CHATS
      .filter(chat => chat.chat_id !== excludeChatId);
    
    // Get community demo chats from the store (these are already Chat objects)
    const communityChats = getAllCommunityDemoChats();
    
    // Convert community chats back to DemoChat format for ChatEmbedPreview
    // Community chats have: chat_id, title, category, icon, etc.
    const communityDemoChats: DemoChat[] = communityChats
      .filter(chat => chat.chat_id !== excludeChatId)
      .map(chat => ({
        chat_id: chat.chat_id,
        slug: chat.chat_id.replace('demo-', ''),
        title: chat.title || '',
        description: '',
        keywords: [],
        messages: [],
        metadata: {
          category: chat.category || chat.encrypted_category || 'general_knowledge',
          icon_names: (chat.icon || chat.encrypted_icon || 'chat').split(','),
          featured: true,
          order: 100,
          lastUpdated: new Date().toISOString()
        }
      }));
    
    // Combine and sort by order
    return [...introDemoChats, ...communityDemoChats]
      .sort((a, b) => a.metadata.order - b.metadata.order);
  })());
  
  // Handle click on a chat card - navigate to the demo chat
  function handleChatClick(chatId: string) {
    console.debug('[ExampleChatsGroup] Chat clicked:', chatId);
    
    // Use activeChatStore to navigate to the chat
    // This is the standard pattern used throughout the app for chat navigation
    activeChatStore.setActiveChat(chatId);
    
    // Also update the URL hash for deep linking support
    if (typeof window !== 'undefined') {
      window.location.hash = `chat-id=${chatId}`;
    }
  }
</script>

{#if exampleChats.length > 0}
  <div class="example-chats-group-wrapper">
    <div class="example-chats-group">
      {#each exampleChats as demoChat (demoChat.chat_id)}
        <ChatEmbedPreview
          {demoChat}
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
  
  .example-chats-group {
    display: flex;
    flex-direction: row;
    gap: 16px;
    padding: 8px 4px;
    /* Enable horizontal scrolling */
    overflow-x: auto;
    overflow-y: hidden;
    /* Smooth scrolling on touch devices */
    -webkit-overflow-scrolling: touch;
    scroll-behavior: smooth;
    /* Snap scrolling for better UX */
    scroll-snap-type: x proximity;
    /* Hide scrollbar but keep functionality */
    scrollbar-width: thin;
    scrollbar-color: var(--color-grey-40) transparent;
  }
  
  /* Custom scrollbar styling for WebKit browsers */
  .example-chats-group::-webkit-scrollbar {
    height: 6px;
  }
  
  .example-chats-group::-webkit-scrollbar-track {
    background: transparent;
  }
  
  .example-chats-group::-webkit-scrollbar-thumb {
    background-color: var(--color-grey-40);
    border-radius: 3px;
  }
  
  .example-chats-group::-webkit-scrollbar-thumb:hover {
    background-color: var(--color-grey-50);
  }
  
  /* Ensure cards don't shrink */
  .example-chats-group > :global(*) {
    flex-shrink: 0;
    scroll-snap-align: start;
  }
</style>
