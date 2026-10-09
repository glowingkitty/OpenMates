<!-- Focus preview using the ordinary public-safe guest Daily Inspiration fallback. -->
<script lang="ts">
  import { onMount } from 'svelte';
  import ActiveChat from './ActiveChat.svelte';
  import { dailyInspirationStore } from '../stores/dailyInspirationStore';
  import { getHardcodedInspirationsForSurface } from '../demo_chats/hardcodedInspirations';

  onMount(() => {
    dailyInspirationStore.restoreGuestOnboarding(getHardcodedInspirationsForSurface('en', 'chats'));
    return () => dailyInspirationStore.reset();
  });
</script>

<ActiveChat />
