<script lang="ts">
  import { text } from '@repo/ui';
  import { SettingsPageContainer, SettingsPageHeader, SettingsInput, SettingsInfoBox, SettingsButton, SettingsButtonGroup } from './elements';
  let { status = 'ready', email = $bindable(''), error = '', onAccept, onDecline }: {
    status?: 'ready' | 'accepting' | 'joined' | 'pending' | 'missing-key' | 'error' | 'declined';
    email?: string;
    error?: string;
    onAccept: () => void;
    onDecline: () => void;
  } = $props();
</script>

<SettingsPageContainer>
  <SettingsPageHeader title={$text('settings.team_invitation.title')} description={$text('settings.team_invitation.description')} />
  {#if status === 'missing-key'}
    <SettingsInfoBox type="error" data-testid="team-invite-missing-key">{$text('settings.team_invitation.missing_key')}</SettingsInfoBox>
  {:else if status === 'joined' || status === 'pending' || status === 'declined'}
    <SettingsInfoBox type="success" data-testid="team-invite-result">{$text(`settings.team_invitation.${status}`)}</SettingsInfoBox>
  {:else}
    <SettingsInput type="email" bind:value={email} autocomplete="email" ariaLabel={$text('settings.team_invitation.email')} placeholder={$text('settings.team_invitation.email')} disabled={status === 'accepting'} dataTestid="team-invite-recipient-email" />
    {#if error}<SettingsInfoBox type="error" data-testid="team-invite-error">{error}</SettingsInfoBox>{/if}
    <SettingsButtonGroup>
      <SettingsButton variant="secondary" onClick={onDecline} disabled={!email.trim() || status === 'accepting'} dataTestid="team-invite-decline">{$text('settings.team_invitation.decline')}</SettingsButton>
      <SettingsButton onClick={onAccept} disabled={!email.trim()} loading={status === 'accepting'} dataTestid="team-invite-accept">{$text('settings.team_invitation.accept')}</SettingsButton>
    </SettingsButtonGroup>
  {/if}
</SettingsPageContainer>
