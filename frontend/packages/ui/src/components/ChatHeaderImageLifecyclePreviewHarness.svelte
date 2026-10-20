<script lang="ts">
  import { onMount } from 'svelte';
  import ChatHeader from './ChatHeader.svelte';

  let chatId = $state('header-image-lifecycle');
  let bubbles = $state([{
    imageUrl: '/header-image-lifecycle-unavailable.jpg',
    parentEmbedId: 'image-search', childEmbedId: 'image-result', title: 'Class photo',
  }]);
  onMount(() => {
    const refresh = () => { bubbles = bubbles.map(bubble => ({ ...bubble })); };
    const switchChat = () => { chatId = 'header-image-lifecycle-next'; };
    window.addEventListener('preview:header-refresh', refresh);
    window.addEventListener('preview:header-switch-chat', switchChat);
    return () => {
      window.removeEventListener('preview:header-refresh', refresh);
      window.removeEventListener('preview:header-switch-chat', switchChat);
    };
  });
</script>

<ChatHeader
  title="Capoeira classes"
  currentChatId={chatId}
  headerImageBubbles={bubbles}
  writable={false}
  onSaveTitle={async () => {}}
  onSaveDescription={async () => {}}
/>
