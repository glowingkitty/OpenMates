<!-- Development preview harness for a Team route change while a notice request is pending. -->
<script lang="ts">
    import SettingsTeams from './SettingsTeams.svelte';
    import { SettingsButton } from './elements';
    import type { TeamBillingSummary, TeamViewModel } from '../../services/teamService';

    const first: TeamViewModel = {
        team_id: 'first-team', name: 'First team', description: '', role: 'owner', status: 'active',
        profileImageMetadata: {}, zeroBalance: 0, createdAt: 1_700_000_000, updatedAt: 1_700_000_000,
        encrypted: { team_id: 'first-team' },
    };
    const second: TeamViewModel = {
        ...first, team_id: 'second-team', name: 'Second team', encrypted: { team_id: 'second-team' },
    };
    const billing: TeamBillingSummary = { balanceCredits: 12, version: 1, raw: { balance_credits: 12, version: 1 } };
    let activeSettingsView = $state('teams/first-team');
</script>

<div class="team-race-preview">
<div class="preview-actions">
<SettingsButton dataTestid="team-preview-switch" onClick={() => activeSettingsView = 'teams/second-team'}>
    Switch team
</SettingsButton>
<SettingsButton dataTestid="team-preview-delete" onClick={() => activeSettingsView = 'teams/first-team/delete'}>
    Open delete confirmation
</SettingsButton>
</div>
<div data-testid="team-preview-active-route" data-active-view={activeSettingsView}>
    <SettingsTeams
        {activeSettingsView}
        previewData={{ teams: [first, second], billing, loadStorage: true }}
        on:openSettings={(event) => activeSettingsView = event.detail.settingsPath}
    />
</div>

</div>
<style>
  .team-race-preview { width: 100%; max-width: 323px; min-width: 0; }
  .preview-actions { display: flex; flex-wrap: wrap; gap: var(--spacing-4); margin-bottom: var(--spacing-6); }
</style>
