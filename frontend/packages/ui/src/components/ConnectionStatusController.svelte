<script lang="ts">
  import { authStore, isCheckingAuth } from '../stores/authStore';
  import { isOnline } from '../stores/networkStatusStore';
  import { websocketStatus } from '../stores/websocketStatusStore';
  import { chatSyncActivity } from '../stores/chatSyncActivityStore';
  import { connectionFeedback } from '../stores/connectionFeedbackStore';
  import { webSocketService } from '../services/websocketService';

  $effect(() => {
    connectionFeedback.update({
      online: $isOnline,
      authenticated: $authStore.isAuthenticated,
      checkingAuth: $isCheckingAuth,
      websocketStatus: $websocketStatus.status,
      syncing: $chatSyncActivity.active,
    });
  });

  $effect(() => {
    const resume = () => connectionFeedback.resume();
    const updating = () => connectionFeedback.serverUpdating();
    webSocketService.addEventListener('resuming', resume);
    webSocketService.addEventListener('serverRestarting', updating);
    return () => {
      webSocketService.removeEventListener('resuming', resume);
      webSocketService.removeEventListener('serverRestarting', updating);
      connectionFeedback.reset();
    };
  });
</script>

<!-- Headless: transient connectivity feedback belongs beside the profile. -->
