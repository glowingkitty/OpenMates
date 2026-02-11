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
  import { convertDemoChatToChat } from '../../demo_chats/convertToChat';
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
   * then dispatches a demoChatSelected window event so +page.svelte loads the chat.
   * 
   * CRITICAL: We must dispatch a window event instead of relying on hash navigation,
   * because activeChatStore.setActiveChat() marks the hash change as programmatic
   * and the hashchange handler in +page.svelte intentionally ignores programmatic
   * hash updates (to prevent infinite loops). This matches the pattern used by
   * ExampleChatsGroup for community demo chats.
   */
  function handleChatClick(_chatId: string) {
    console.log('[IntroChatEmbed] === CLICK HANDLER START ===');
    console.log('[IntroChatEmbed] introChatId:', introChatId, '_chatId:', _chatId);
    
    // Get the intro chat data and convert it to a Chat object for loading
    const introChat = getIntroChatById(introChatId);
    if (!introChat) {
      console.warn('[IntroChatEmbed] Intro chat not found for navigation:', introChatId);
      return;
    }
    console.log('[IntroChatEmbed] Found intro chat:', introChat.chat_id, 'title:', introChat.title);
    
    // Translate and convert to Chat format (same as handleChatDeepLink does for public chats)
    const translated = translateDemoChat(introChat);
    const chat = convertDemoChatToChat(translated);
    console.log('[IntroChatEmbed] Converted chat object:', { chat_id: chat.chat_id, title: chat.title, category: chat.category });
    
    // Update sidebar highlight via activeChatStore (also updates URL hash)
    activeChatStore.setActiveChat(introChatId);
    console.log('[IntroChatEmbed] Called activeChatStore.setActiveChat()');
    
    // Dispatch demoChatSelected event to trigger chat loading in +page.svelte
    // This is the same pattern used by ExampleChatsGroup - needed because
    // activeChatStore.setActiveChat() triggers a programmatic hash update
    // that the hashchange handler intentionally ignores (to prevent loops)
    const event = new CustomEvent('demoChatSelected', {
      detail: { chat },
      bubbles: true,
      composed: true
    });
    console.log('[IntroChatEmbed] Dispatching demoChatSelected event with chat:', chat.chat_id);
    window.dispatchEvent(event);
    console.log('[IntroChatEmbed] === CLICK HANDLER END ===');
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
