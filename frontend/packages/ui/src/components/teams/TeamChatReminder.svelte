<script lang="ts">
  import { text } from '../../i18n/translations';
  import { settingsDeepLink } from '../../stores/settingsDeepLinkStore';
  import { panelState } from '../../stores/panelStateStore';
  import SettingsInfoBox from '../settings/elements/SettingsInfoBox.svelte';

  const parts = $derived($text('settings.teams_ui.chat_ai_reminder').split('@openmates'));
  function openMates(): void {
    settingsDeepLink.set('mates');
    panelState.openSettings();
  }
</script>

<SettingsInfoBox type="info" plain data-testid="team-chat-ai-reminder">
  <p>{parts[0]}<button type="button" class="mate-link" data-testid="team-reminder-openmates" onclick={openMates}>@openmates</button>{parts.slice(1).join('@openmates')}</p>
</SettingsInfoBox>

<style>
  p { margin: 0; }
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
