<!-- Real composer and existing-chat rail, including the outside-pointer focus boundary. -->
<script lang="ts">
  import MessageInput from './enter_message/MessageInput.svelte';
  import ChatSearchSuggestions from './ChatSearchSuggestions.svelte';

  let focused = $state(false);
  let query = $state('');
  let selectedEmbed = $state('');
  let selectedOwner = $state('');
</script>

<div class="fixture" data-testid="composer-search-fixture" data-selected-embed={selectedEmbed} data-selected-owner={selectedOwner}>
  {#if focused}
    <ChatSearchSuggestions messageInputContent={query} currentChatId="synthetic-composer-search"
      onChatNavigate={() => {}} onFileSelect={() => {}}
      onEmbedSelect={(embedId, _path, chatId) => { selectedEmbed = embedId; selectedOwner = chatId ?? ''; }} />
  {/if}
  <MessageInput currentChatId="synthetic-composer-search" showActionButtons={false} bind:isFocused={focused}
    on:textchange={(event) => { query = event.detail.text; }} />
</div>

<style>
  .fixture { width: 100%; }
</style>
