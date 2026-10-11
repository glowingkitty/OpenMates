<!--
  Team member profile action for starting a two-person private chat.
  It uses canonical Settings controls so keyboard, loading and warning states
  match the rest of Settings. The caller owns Team/member validation and chat
  navigation; this component presents recoverable pending-key feedback.
-->
<script lang="ts">
  import { text } from '@repo/ui';
  import { DirectChatError } from '../../services/directChatService';
  import { SettingsButton, SettingsInfoBox } from './elements';

  let { onMessage }: { onMessage: () => Promise<void> } = $props();
  let loading = $state(false);
  let error = $state('');

  async function openMessage(): Promise<void> {
    if (loading) return;
    loading = true;
    error = '';
    try {
      await onMessage();
    } catch (cause) {
      error = cause instanceof DirectChatError && cause.code === 'pending'
        ? $text('settings.teams_ui.direct_message_pending')
        : $text('settings.teams_ui.direct_message_failed');
    } finally {
      loading = false;
    }
  }
</script>

<div data-testid="team-member-message-action">
  <SettingsButton variant="secondary" loading={loading} dataTestid="team-member-message" onClick={() => void openMessage()}>
    {$text('settings.teams_ui.direct_message_action')}
  </SettingsButton>
  {#if error}<SettingsInfoBox type="warning"><p>{error}</p></SettingsInfoBox>{/if}
  <SettingsInfoBox type="info"><p>{$text('settings.teams_ui.direct_message_scope')}</p></SettingsInfoBox>
</div>
