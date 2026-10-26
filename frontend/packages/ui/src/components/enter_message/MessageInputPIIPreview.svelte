<!-- Test-only bare composer fixture with the normal global notification deck. -->
<script lang="ts">
  import MessageInputFocusFixture from './MessageInputFocusFixture.svelte';
  import NotificationStack from '../NotificationStack.svelte';
</script>

<MessageInputFocusFixture emptyDraft={true} />
<NotificationStack />
