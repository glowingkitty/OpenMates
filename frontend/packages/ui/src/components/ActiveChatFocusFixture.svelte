<!-- Focus preview using the ordinary public-safe guest Daily Inspiration fallback. -->
<script lang="ts">
  import { onMount } from 'svelte';
  import ActiveChat from './ActiveChat.svelte';
  import { getExampleChat } from '../demo_chats';

  let activeChat: ReturnType<typeof ActiveChat>;
  let loaded = $state('');
  let loadCount = $state(0);
  import { dailyInspirationStore } from '../stores/dailyInspirationStore';
  import { getHardcodedInspirationsForSurface } from '../demo_chats/hardcodedInspirations';

  onMount(() => {
    dailyInspirationStore.restoreGuestOnboarding(getHardcodedInspirationsForSurface('en', 'chats'));
    const openExample = async (event: Event) => {
      const id = (event as CustomEvent<string>).detail;
      const chat = getExampleChat(id);
      if (!chat) throw new Error(`Unknown public focus fixture chat: ${id}`);
      await activeChat.loadChat(chat);
      loaded = id;
      loadCount += 1;
    };
    window.addEventListener('fixtureOpenExample', openExample);
    return () => {
      window.removeEventListener('fixtureOpenExample', openExample);
      dailyInspirationStore.reset();
    };
  });
</script>

<div data-testid="example-focus-fixture" data-loaded={loaded} data-load-count={loadCount}></div>
<ActiveChat bind:this={activeChat} />
