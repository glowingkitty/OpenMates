<!--
  TeamsWorkspacePage.svelte
  Authenticated Teams V1 web workspace. It keeps the browser slice deliberately
  small: encrypted team create/list/switch, read-only context panels, team
  billing/memory visibility, and email invite creation. Destructive lifecycle
  actions stay in CLI/SDK until the larger Teams UI is reviewed.
-->

<script lang="ts">
  import { onMount } from 'svelte';
  import WorkspaceHomeShell from '../workspace/WorkspaceHomeShell.svelte';
  import { featureAvailabilityStore, initializeFeatureAvailability } from '../../stores/appSkillsStore';
  import { notificationStore } from '../../stores/notificationStore';
  import { userProfile } from '../../stores/userProfile';
  import { activeTeamId, setActiveTeamContext } from '../../stores/teamStore';
  import { isWorkspaceFeatureAvailable } from '../../config/workspaceFeatureGates';
  import {
    createTeam,
    createTeamEmailInvite,
    listTeams,
    loadTeamBilling,
    loadTeamMemoryCount,
    type TeamBillingSummary,
    type TeamViewModel,
  } from '../../services/teamService';

  let teams = $state<TeamViewModel[]>([]);
  let selectedTeam = $state<TeamViewModel | null>(null);
  let billing = $state<TeamBillingSummary | null>(null);
  let teamMemoryCount = $state(0);
  let isLoading = $state(true);
  let hasLoadError = $state(false);
  let isCreating = $state(false);
  let isLoadingContext = $state(false);
  let isInviting = $state(false);
  let newTeamName = $state('');
  let newTeamDescription = $state('');
  let inviteEmail = $state('');
  let inviteStatus = $state('');

  let teamsEnabled = $derived(isWorkspaceFeatureAvailable('platform:teams', $featureAvailabilityStore.disabledById));
  let greetingName = $derived(formatGreetingName($userProfile.username));
  let sortedTeams = $derived([...teams].sort((a, b) => b.createdAt - a.createdAt));
  let canCreateTeam = $derived(newTeamName.trim().length > 0 && teamsEnabled && !isCreating);
  let canInvite = $derived(!!selectedTeam && inviteEmail.trim().length > 0 && !isInviting);

  function formatGreetingName(username: string): string {
    const trimmed = username.trim();
    return trimmed ? trimmed.split(/\s+/)[0] : 'there';
  }

  async function refreshTeams(): Promise<void> {
    if (!teamsEnabled) {
      teams = [];
      selectedTeam = null;
      setActiveTeamContext(null);
      isLoading = false;
      return;
    }
    isLoading = true;
    try {
      hasLoadError = false;
      teams = await listTeams();
      const persistedTeam = teams.find((team) => team.team_id === $activeTeamId) ?? teams[0] ?? null;
      if (persistedTeam) {
        await selectTeam(persistedTeam, { notify: false });
      } else {
        selectedTeam = null;
        billing = null;
        teamMemoryCount = 0;
        setActiveTeamContext(null);
      }
    } catch (error) {
      hasLoadError = true;
      console.error('[TeamsWorkspacePage] Failed to load teams:', error);
      notificationStore.error('Failed to load teams');
    } finally {
      isLoading = false;
    }
  }

  async function selectTeam(team: TeamViewModel, options: { notify?: boolean } = {}): Promise<void> {
    selectedTeam = team;
    setActiveTeamContext(team);
    inviteStatus = '';
    isLoadingContext = true;
    try {
      const [nextBilling, nextMemoryCount] = await Promise.all([
        loadTeamBilling(team),
        loadTeamMemoryCount(team.team_id),
      ]);
      billing = nextBilling;
      teamMemoryCount = nextMemoryCount;
      if (options.notify !== false) notificationStore.success('Team context switched');
    } catch (error) {
      console.error('[TeamsWorkspacePage] Failed to load team context:', error);
      notificationStore.error('Failed to load team context');
    } finally {
      isLoadingContext = false;
    }
  }

  async function handleCreateTeam(): Promise<void> {
    if (!canCreateTeam) return;
    isCreating = true;
    try {
      const team = await createTeam({ name: newTeamName, description: newTeamDescription });
      teams = [team, ...teams.filter((candidate) => candidate.team_id !== team.team_id)];
      newTeamName = '';
      newTeamDescription = '';
      await selectTeam(team, { notify: false });
      notificationStore.success('Team created');
    } catch (error) {
      console.error('[TeamsWorkspacePage] Failed to create team:', error);
      notificationStore.error('Failed to create team');
    } finally {
      isCreating = false;
    }
  }

  async function handleInvite(): Promise<void> {
    if (!selectedTeam || !canInvite) return;
    isInviting = true;
    try {
      const invite = await createTeamEmailInvite(selectedTeam, inviteEmail);
      inviteEmail = '';
      inviteStatus = invite.deliveryStatus === 'sent' ? 'Invite sent' : 'Invite created';
      notificationStore.success(inviteStatus);
    } catch (error) {
      console.error('[TeamsWorkspacePage] Failed to create team invite:', error);
      inviteStatus = 'Invite could not be created';
      notificationStore.error('Failed to create invite');
    } finally {
      isInviting = false;
    }
  }

  onMount(() => {
    initializeFeatureAvailability().catch((error: unknown) => {
      console.warn('[TeamsWorkspacePage] Failed to load feature availability:', error);
    });
  });

  $effect(() => {
    if (!$featureAvailabilityStore.initialized || $featureAvailabilityStore.disabledById === null) return;
    void refreshTeams();
  });
</script>

{#if !teamsEnabled}
  <section class="teams-page" data-testid="teams-feature-disabled">
    <div class="teams-state">
      <h2>Teams unavailable</h2>
      <p>Teams are disabled on this server.</p>
    </div>
  </section>
{:else}
  <section class="teams-page" data-testid="teams-page">
    <WorkspaceHomeShell
      surface="teams"
      testId="teams-workspace-home"
      centerTestId="teams-greeting"
      contentSlotVisible
      contentSlotTestId="teams-workspace-content"
      heading={`Hey ${greetingName}!`}
      subtitle="Create a shared encrypted team context."
      showReportIssue
    >
      <section class="teams-grid" data-testid="teams-grid" aria-label="Teams workspace">
        <form
          class="team-create-card"
          data-testid="team-create-form"
          onsubmit={(event) => {
            event.preventDefault();
            void handleCreateTeam();
          }}
        >
          <div>
            <p class="eyebrow">New team</p>
            <h3>Create an encrypted team</h3>
            <p>Team names, descriptions, profile metadata, and zero balance are encrypted before leaving this browser.</p>
          </div>
          <label>
            <span>Team name</span>
            <input bind:value={newTeamName} data-testid="team-name-input" placeholder="e.g. Launch team" autocomplete="off" />
          </label>
          <label>
            <span>Description</span>
            <textarea bind:value={newTeamDescription} data-testid="team-description-input" placeholder="What this team works on" rows="3"></textarea>
          </label>
          <button type="submit" data-testid="team-create-submit" disabled={!canCreateTeam}>{isCreating ? 'Creating...' : 'Create team'}</button>
        </form>

        <section class="team-list-panel" data-testid="team-list-panel" aria-label="Your teams">
          <div class="panel-heading">
            <p class="eyebrow">Your teams</p>
            <h3>Switch context</h3>
          </div>
          {#if isLoading}
            <div class="teams-state" data-testid="teams-loading">Loading teams...</div>
          {:else if hasLoadError}
            <div class="teams-state" data-testid="teams-load-error">
              <p>Teams could not be loaded.</p>
              <button type="button" onclick={() => void refreshTeams()}>Retry</button>
            </div>
          {:else if sortedTeams.length === 0}
            <div class="teams-state" data-testid="teams-empty">Create your first encrypted team.</div>
          {:else}
            <div class="team-card-list" data-testid="team-list">
              {#each sortedTeams as team (team.team_id)}
                <button
                  type="button"
                  class="team-card"
                  class:active={selectedTeam?.team_id === team.team_id}
                  data-testid="team-card"
                  data-team-role={team.role}
                  data-team-id={team.team_id}
                  onclick={() => void selectTeam(team)}
                >
                  <span class="team-avatar" aria-hidden="true"></span>
                  <span>
                    <strong>{team.name}</strong>
                    <small>{team.description || 'Shared encrypted workspace'}</small>
                  </span>
                  <em>{team.role}</em>
                </button>
              {/each}
            </div>
          {/if}
        </section>

        <section class="team-context-panel" data-testid="team-context-panel" aria-live="polite">
          {#if selectedTeam}
            <div class="context-header">
              <span class="context-badge" data-testid="team-context-badge">Team context</span>
              <span class="role-badge" data-testid="team-role-badge">{selectedTeam.role}</span>
              <h2 data-testid="active-team-name">{selectedTeam.name}</h2>
              <p data-testid="active-team-description">{selectedTeam.description || 'Shared encrypted workspace'}</p>
            </div>

            <div class="team-metrics">
              <article data-testid="team-billing-panel">
                <span>Team credits</span>
                <strong data-testid="team-credit-balance">{billing?.balanceCredits ?? 0}</strong>
                <small>{isLoadingContext ? 'Refreshing balance...' : 'Shared team balance'}</small>
              </article>
              <article data-testid="team-memories-panel">
                <span>Team memories</span>
                <strong>{teamMemoryCount}</strong>
                <small>{teamMemoryCount === 1 ? 'team memory' : 'team memories'}</small>
              </article>
              <article data-testid="team-connected-accounts-panel">
                <span>Team connected accounts</span>
                <strong>Disabled in V1</strong>
                <small>Team-owned credentials fail closed until a later release.</small>
              </article>
            </div>

            <p class="privacy-guard" data-testid="team-personal-data-guard">
              Personal memories stay in personal context. Personal connected accounts stay in personal context.
            </p>

            <form
              class="team-invite-form"
              data-testid="team-invite-form"
              onsubmit={(event) => {
                event.preventDefault();
                void handleInvite();
              }}
            >
              <label>
                <span>Invite by email</span>
                <input bind:value={inviteEmail} data-testid="team-invite-email-input" type="email" placeholder="teammate@example.com" autocomplete="off" />
              </label>
              <button type="submit" data-testid="team-invite-submit" disabled={!canInvite}>{isInviting ? 'Sending...' : 'Send invite'}</button>
              {#if inviteStatus}
                <p class="invite-status" data-testid="team-invite-status">{inviteStatus}</p>
              {/if}
            </form>
          {:else}
            <div class="teams-state" data-testid="team-context-empty">Select or create a team to inspect its context.</div>
          {/if}
        </section>
      </section>
    </WorkspaceHomeShell>
  </section>
{/if}

<style>
  .teams-page {
    display: flex;
    width: 100%;
    min-width: 0;
    height: 100%;
    min-height: 0;
    flex-direction: column;
    overflow: hidden;
    border-radius: 17px;
    background: var(--color-grey-20);
    box-shadow: 0 0 12px rgba(0, 0, 0, 0.25);
    color: var(--color-font-primary);
  }

  .teams-page :global(.workspace-home-shell) {
    flex: 1;
    min-height: 0;
  }

  @media (min-width: 900px) {
    .teams-page :global(.workspace-home-shell.content-slot-mode .workspace-center-content.center-content) {
      margin-top: clamp(8px, 1.4vh, 18px);
    }

    .teams-page :global(.workspace-content-slot) {
      margin-top: clamp(12px, 2vh, 24px);
    }
  }

  .teams-grid {
    display: grid;
    grid-template-columns: minmax(220px, 0.9fr) minmax(240px, 1fr) minmax(280px, 1.25fr);
    gap: 16px;
  }

  .team-create-card,
  .team-list-panel,
  .team-context-panel {
    display: flex;
    min-width: 0;
    flex-direction: column;
    gap: 14px;
    border: 1px solid color-mix(in srgb, var(--color-grey-40) 50%, transparent);
    border-radius: 24px;
    padding: 18px;
    background: color-mix(in srgb, var(--color-grey-0) 92%, transparent);
    box-shadow: 0 12px 30px rgba(0, 0, 0, 0.08);
  }

  .eyebrow,
  .panel-heading p,
  .context-badge,
  .role-badge {
    margin: 0;
    color: var(--color-grey-60);
    font-size: var(--font-size-xs);
    font-weight: 800;
    letter-spacing: 0.08em;
    text-transform: uppercase;
  }

  h2,
  h3,
  p {
    margin: 0;
  }

  h2,
  h3 {
    color: var(--color-font-primary);
  }

  p,
  small,
  label span {
    color: var(--color-font-secondary);
  }

  label {
    display: grid;
    gap: 6px;
    font-weight: 700;
  }

  input,
  textarea {
    width: 100%;
    border: 1px solid var(--color-grey-30);
    border-radius: 14px;
    padding: 11px 12px;
    background: var(--color-grey-0);
    color: var(--color-font-primary);
    font: inherit;
    box-sizing: border-box;
  }

  textarea {
    resize: vertical;
  }

  button {
    border: 0;
    border-radius: var(--radius-full);
    padding: 10px 14px;
    background: var(--color-button-primary);
    color: var(--color-font-button);
    font: inherit;
    font-weight: 800;
    cursor: pointer;
  }

  button:disabled {
    opacity: 0.55;
    cursor: not-allowed;
  }

  .teams-state {
    border: 1px dashed var(--color-grey-30);
    border-radius: 18px;
    padding: 22px;
    color: var(--color-font-secondary);
    text-align: center;
  }

  .teams-state button {
    margin-top: 12px;
  }

  .team-card-list {
    display: grid;
    gap: 10px;
  }

  .team-card {
    display: grid;
    grid-template-columns: 42px minmax(0, 1fr) auto;
    align-items: center;
    gap: 12px;
    border: 1px solid transparent;
    border-radius: 18px;
    padding: 12px;
    background: var(--color-grey-10);
    color: var(--color-font-primary);
    text-align: start;
  }

  .team-card.active {
    border-color: color-mix(in srgb, var(--color-primary) 45%, transparent);
    background: color-mix(in srgb, var(--color-primary) 12%, var(--color-grey-10));
  }

  .team-avatar {
    display: grid;
    width: 42px;
    height: 42px;
    place-items: center;
    border-radius: 15px;
    background: linear-gradient(135deg, #4d73ff, #9b6dff);
  }

  .team-avatar::after {
    width: 22px;
    height: 22px;
    background: white;
    content: '';
    -webkit-mask: url('@openmates/ui/static/icons/team.svg') center / contain no-repeat;
    mask: url('@openmates/ui/static/icons/team.svg') center / contain no-repeat;
  }

  .team-card span:nth-child(2) {
    display: grid;
    min-width: 0;
    gap: 3px;
  }

  .team-card strong,
  .team-card small {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .team-card em,
  .role-badge,
  .context-badge {
    border-radius: var(--radius-full);
    padding: 5px 8px;
    background: color-mix(in srgb, var(--color-grey-80) 10%, transparent);
    font-style: normal;
  }

  .context-header {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px;
  }

  .context-header h2,
  .context-header p {
    width: 100%;
  }

  .team-metrics {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 10px;
  }

  .team-metrics article {
    display: grid;
    gap: 6px;
    border-radius: 18px;
    padding: 14px;
    background: var(--color-grey-10);
  }

  .team-metrics span {
    color: var(--color-font-secondary);
    font-size: var(--font-size-small);
    font-weight: 800;
  }

  .team-metrics strong {
    font-size: 1.3rem;
  }

  .privacy-guard {
    border-radius: 18px;
    padding: 12px;
    background: color-mix(in srgb, var(--color-primary) 10%, var(--color-grey-10));
    font-weight: 700;
  }

  .team-invite-form {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    align-items: end;
    gap: 10px;
  }

  .invite-status {
    grid-column: 1 / -1;
    color: var(--color-success, #138a35);
    font-weight: 800;
  }

  @media (max-width: 1100px) {
    .teams-grid {
      grid-template-columns: 1fr;
    }

    .team-metrics {
      grid-template-columns: 1fr;
    }
  }

  @media (max-width: 620px) {
    .team-invite-form {
      grid-template-columns: 1fr;
    }
  }
</style>
