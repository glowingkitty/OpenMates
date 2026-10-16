<script lang="ts">
  import { text } from '../../i18n/translations';
  import { settingsDeepLink } from '../../stores/settingsDeepLinkStore';
  import { panelState } from '../../stores/panelStateStore';
  import SystemMessageNotice from '../SystemMessageNotice.svelte';

  const parts = $derived($text('settings.teams_ui.chat_ai_reminder').split('@openmates'));
  function openMates(): void {
    settingsDeepLink.set('mates');
    panelState.openSettings();
  }
</script>

<div class="chat-message system">
  <SystemMessageNotice testId="team-chat-ai-reminder">
    <p>{parts[0]}<button type="button" class="mate-link" data-testid="team-reminder-openmates" onclick={openMates}>@openmates</button>{parts.slice(1).join('@openmates')}</p>
  </SystemMessageNotice>
</div>

<style>
  p { margin: 0; }
  .chat-message.system { display: flex; justify-content: center; padding: var(--spacing-4) 0; }
  .mate-link {
    border: 0;
    padding: 0;
    font: inherit;
    font-weight: var(--font-weight-semibold, 600);
    background: var(--gradient-primary);
    background-clip: text;
    -webkit-background-clip: text;
    color: transparent;
    box-shadow: none;
    cursor: pointer;
  }
  .mate-link:focus-visible { outline: 2px solid var(--color-button-primary); outline-offset: 3px; }
</style>
