<!-- Focus preview with the guest intro data needed to leave its covered state. -->
<script lang="ts">
  import { onMount } from 'svelte';
  import ActiveChat from './ActiveChat.svelte';
  import { dailyInspirationStore, type DailyInspiration } from '../stores/dailyInspirationStore';

  const previewInspirations: DailyInspiration[] = [
    {
      inspiration_id: 'openmates-intro', phrase: 'Meet your AI team', category: 'general_knowledge',
      content_type: 'feature', video: null, generated_at: 1,
      feature: { feature_id: 'openmates-intro', icon: 'sparkles', title: 'Meet your AI team',
        description: 'Explore what OpenMates can do.', settings_path: null },
    },
    {
      inspiration_id: 'openmates-actionable-events', phrase: 'Find things to do nearby',
      category: 'general_knowledge', content_type: 'feature', video: null, generated_at: 1,
      feature: { feature_id: 'openmates-actionable-events', icon: 'calendar', title: 'Find things to do nearby',
        description: 'Discover local events.', settings_path: null },
    },
  ];

  onMount(() => {
    dailyInspirationStore.setInspirations(previewInspirations, { source: 'guest-onboarding' });
    return () => dailyInspirationStore.reset();
  });
</script>

<ActiveChat />
