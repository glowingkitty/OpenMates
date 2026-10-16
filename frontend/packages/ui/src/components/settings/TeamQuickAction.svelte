<script lang="ts">
  import { text } from '../../i18n/translations';
  import type { TeamViewModel } from '../../services/teamService';
  import SettingsItem from '../SettingsItem.svelte';
  import { Plus } from '@lucide/svelte';
  import SettingsButton from './elements/SettingsButton.svelte';
  import TeamContextPicker from './TeamContextPicker.svelte';
  import { orderTeamsByRecent, rememberTeamSelection } from '../../stores/teamStore';

  let {
    teams, activeTeamId, loading, onTeamContextChange, onCreateTeam, onTeamToggle, onOpenTeams,
  }: {
    teams: TeamViewModel[];
    activeTeamId: string | null;
    loading: boolean;
    onTeamContextChange: (contextId: string) => void;
    onCreateTeam: () => void;
    onTeamToggle: (teamId: string | null) => void;
    onOpenTeams: () => void;
  } = $props();

  // Choosing a Team while the toggle is off must not enter its workspace.
  let selectedTeamId = $state<string | null>(null);
  let selectedTeam = $derived(teams.find(team => team.team_id === (activeTeamId ?? selectedTeamId)) ?? orderTeamsByRecent(teams)[0] ?? null);
  $effect(() => { if (activeTeamId) selectedTeamId = activeTeamId; });

  function selectTeam(teamId: string) {
    selectedTeamId = teamId;
    rememberTeamSelection(teamId);
    if (activeTeamId !== null) onTeamContextChange(teamId);
  }

  let toggleInProgress = false;
  function handleToggle() {
    // The checkbox label can synthesize a second click on some browsers.
    if (loading || toggleInProgress || !selectedTeam) return;
    toggleInProgress = true;
    queueMicrotask(() => { toggleInProgress = false; });
    selectedTeamId = selectedTeam.team_id;
    onTeamToggle(activeTeamId !== null ? null : selectedTeam.team_id);
  }
</script>

{#snippet teamPicker()}
  <span role="presentation" onclick={(event) => event.stopPropagation()} onkeydown={(event) => event.stopPropagation()}>
    <TeamContextPicker {teams} activeTeamId={selectedTeam?.team_id ?? null} disabled={loading} compact
      testId="team-quick-context-dropdown" avatarTestId="team-quick-active-team-avatar"
      onTeamContextChange={selectTeam} {onCreateTeam} />
  </span>
{/snippet}

{#snippet createButton()}
  <span role="presentation" onclick={(event) => event.stopPropagation()} onkeydown={(event) => event.stopPropagation()}>
    <SettingsButton variant="cta" size="sm" ariaLabel={$text('settings.teams_ui.new_team')}
      dataTestid="team-quick-create" disabled={loading} onClick={onCreateTeam}>
      <Plus size={22} aria-hidden="true" />
    </SettingsButton>
  </span>
{/snippet}

<SettingsItem
  type="quickaction"
  icon="team"
  title={$text('settings.teams')}
  hasToggle={teams.length > 0}
  checked={activeTeamId !== null}
  disabled={loading}
  onClick={onOpenTeams}
  onToggleClick={handleToggle}
  rightContent={teams.length > 0 ? teamPicker : createButton}
  data-testid="settings-teams-item"
/>
