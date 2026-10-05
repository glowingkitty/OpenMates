<!-- Isolated composer preview with the same global notification deck as the chat route. -->
<script lang="ts">
  import MessageInput from './MessageInput.svelte';
  import NotificationStack from '../NotificationStack.svelte';
</script>

<div class="preview-composer">
  <MessageInput showActionButtons={false} />
</div>
<NotificationStack />

<style>
  .preview-composer { width: min(100%, 680px); box-sizing: border-box; }
</style>
