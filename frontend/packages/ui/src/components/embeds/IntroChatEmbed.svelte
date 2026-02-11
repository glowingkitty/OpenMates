<!--
  frontend/packages/ui/src/components/embeds/IntroChatEmbed.svelte
  
  Renders an embedded preview card for a static intro chat (e.g. "For Developers").
  Used within the for-everyone intro chat to link developers to the for-developers chat,
  rendered via the [[for_developers_embed]] placeholder.
  
  Uses ExampleChatsGroup-style layout (horizontal scrollable container with a single card)
  to maintain visual consistency with other embedded groups in the intro chat.
  
  The preview uses ChatEmbedPreview to render the card with:
  - The intro chat's translated title as the card title
  - The intro chat's translated description as the preview text
  - The intro chat's category and first icon
  
  Clicking navigates to the intro chat via activeChatStore + hash navigation.
-->

<script lang="ts">
  import ChatEmbedPreview from './ChatEmbedPreview.svelte';
  import { getIntroChatById } from '../../demo_chats';
  import { translateDemoChat } from '../../demo_chats/translateDemoChat';
  import { activeChatStore } from '../../stores/activeChatStore';
  
  /**
   * Props interface for IntroChatEmbed
   */
  interface Props {
    /** The intro chat ID to embed (e.g. "demo-for-developers") */
    introChatId: string;
  }
  
  let {
    introChatId
  }: Props = $props();
  
  /**
   * Get the intro chat data and translate it for display.
   * Returns null if the chat is not found.
   */
  let translatedChat = $derived((() => {
    const chat = getIntroChatById(introChatId);
    if (!chat) {
      console.warn('[IntroChatEmbed] Intro chat not found:', introChatId);
      return null;
    }
    // Translate the demo chat to resolve translation keys to actual content
    return translateDemoChat(chat);
  })());
  
  /** Extract display values from the translated intro chat */
  let chatTitle = $derived(translatedChat?.title || '');
  let chatDescription = $derived(translatedChat?.description || chatTitle);
  let chatCategory = $derived(translatedChat?.metadata?.category || 'openmates_official');
  let chatIconName = $derived(
    translatedChat?.metadata?.icon_names?.[0] || 'message-circle'
  );
  
  /**
   * Handle click on the embed card - navigate to the intro chat.
   * Uses activeChatStore to update the sidebar highlight and URL hash,
   * then dispatches a custom event so +page.svelte loads the chat.
   */
  function handleChatClick(_chatId: string) {
    console.debug('[IntroChatEmbed] Chat clicked:', introChatId);
    
    // Update sidebar highlight via activeChatStore (also updates URL hash)
    activeChatStore.setActiveChat(introChatId);
    
    // Also update the URL hash directly for intro chats
    // (intro chats are loaded via hash navigation, not the community demo store)
    window.location.hash = `chat-id=${introChatId}`;
  }
</script>

{#if translatedChat}
  <div class="intro-chat-embed-wrapper">
    <div class="intro-chat-embed">
      <ChatEmbedPreview
        chatId={introChatId}
        title={chatTitle}
        previewText={chatDescription}
        category={chatCategory}
        iconName={chatIconName}
        onClick={handleChatClick}
      />
    </div>
  </div>
{/if}

<style>
  .intro-chat-embed-wrapper {
    /* Full width of the message content area */
    width: 100%;
    margin: 16px 0;
    /* Needed for proper overflow handling */
    overflow: hidden;
  }
  
  /* Match the standard embed group scroll container layout for consistency */
  .intro-chat-embed {
    display: flex;
    gap: 8px;
    align-items: flex-start;
    overflow-x: auto;
    overflow-y: hidden;
    padding: 4px 0;
    scrollbar-width: thin;
    scrollbar-color: var(--color-grey-60) transparent;
  }
  
  /* Custom scrollbar styling for WebKit browsers */
  .intro-chat-embed::-webkit-scrollbar {
    height: 4px;
  }
  
  .intro-chat-embed::-webkit-scrollbar-track {
    background: transparent;
  }
  
  .intro-chat-embed::-webkit-scrollbar-thumb {
    background-color: var(--color-grey-60);
    border-radius: 2px;
  }
  
  /* Ensure cards don't shrink */
  .intro-chat-embed > :global(*) {
    flex-shrink: 0;
  }
</style>
