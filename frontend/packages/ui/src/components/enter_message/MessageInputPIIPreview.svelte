<!-- Test-only bare composer fixture with the normal global notification deck. -->
<script lang="ts">
  import { onMount } from 'svelte';
  import { authStore } from '../../stores/authState';
  import MessageInputFocusFixture from './MessageInputFocusFixture.svelte';
  import NotificationStack from '../NotificationStack.svelte';
  let { coldStart = false }: { coldStart?: boolean } = $props();
  onMount(() => {
    if (!coldStart) return;
    // Let the real composer register its subscriptions before auth hydrates.
    const timer = setTimeout(() => authStore.set({ isInitialized: true, isAuthenticated: false }), 50);
    return () => clearTimeout(timer);
  });
</script>

<MessageInputFocusFixture emptyDraft={true} />
<NotificationStack />
