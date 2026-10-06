<script lang="ts">
  import { text } from '../../i18n/translations';
  import type { TeamViewModel } from '../../services/teamService';
  import SettingsItem from '../SettingsItem.svelte';
  import TeamContextPicker from './TeamContextPicker.svelte';

  let {
    teams, activeTeamId, loading, onTeamContextChange, onCreateTeam, onTeamToggle, onOpenTeams,
  }: {
    teams: TeamViewModel[];
    activeTeamId: string | null;
    loading: boolean;
    onTeamContextChange: (contextId: string) => void;
    onCreateTeam: () => void;
    onTeamToggle: () => void;
    onOpenTeams: () => void;
  } = $props();

  let toggleInProgress = false;
  function handleToggle() {
    // The checkbox label can synthesize a second click on some browsers.
    if (toggleInProgress) return;
    toggleInProgress = true;
    queueMicrotask(() => { toggleInProgress = false; });
    onTeamToggle();
  }
</script>

{#snippet teamPicker()}
  <span role="presentation" onclick={(event) => event.stopPropagation()} onkeydown={(event) => event.stopPropagation()}>
    <TeamContextPicker {teams} {activeTeamId} disabled={loading} compact
      testId="team-quick-context-dropdown" avatarTestId="team-quick-active-team-avatar"
      {onTeamContextChange} {onCreateTeam} />
  </span>
{/snippet}

<SettingsItem
  type="quickaction"
  icon="team"
  title={$text('settings.teams')}
  hasToggle={true}
  checked={activeTeamId !== null}
  onClick={onOpenTeams}
  onToggleClick={handleToggle}
  rightContent={teamPicker}
  data-testid="settings-teams-item"
/>
