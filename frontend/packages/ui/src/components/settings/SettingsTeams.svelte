<!--
  SettingsTeams.svelte
  Settings-only Teams V1 management surface. It reuses the encrypted browser
  team service for create/list/detail/invite without exposing a top-level Teams
  workspace. Active personal/team context switching stays in the profile menu.
  Spec: docs/specs/teams-v1/spec.yml
-->

<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import { text } from '@repo/ui';
    import {
        SettingsButton,
        SettingsButtonGroup,
        SettingsCard,
        SettingsDetailRow,
        SettingsInfoBox,
        SettingsInput,
        SettingsItem,
        SettingsPageContainer,
        SettingsSectionHeading,
        SettingsTextarea,
    } from './elements';
    import { notificationStore } from '../../stores/notificationStore';
    import { notifyTeamsUpdated } from '../../stores/teamStore';
    import {
        createTeam,
        createTeamEmailInvite,
        listTeams,
        loadTeamBilling,
        loadTeamMemoryCount,
        type TeamBillingSummary,
        type TeamViewModel,
    } from '../../services/teamService';

    let { activeSettingsView = 'teams' }: { activeSettingsView?: string } = $props();

    const dispatch = createEventDispatcher();

    let teams = $state<TeamViewModel[]>([]);
    let billing = $state<TeamBillingSummary | null>(null);
    let teamMemoryCount = $state(0);
    let isLoading = $state(true);
    let isCreating = $state(false);
    let isInviting = $state(false);
    let loadError = $state('');
    let inviteStatus = $state('');
    let newTeamName = $state('');
    let newTeamDescription = $state('');
    let inviteEmail = $state('');
    let loadedRoute = $state('');

    let selectedTeamId = $derived(activeSettingsView.match(/^teams\/([^/]+)$/)?.[1] ?? null);
    let selectedTeam = $derived(teams.find((team) => team.team_id === selectedTeamId) ?? null);
    let sortedTeams = $derived([...teams].sort((a, b) => b.createdAt - a.createdAt));
    let canCreateTeam = $derived(newTeamName.trim().length > 0 && !isCreating);
    let canInvite = $derived(!!selectedTeam && inviteEmail.trim().length > 0 && !isInviting);

    $effect(() => {
        if (loadedRoute === activeSettingsView) return;
        loadedRoute = activeSettingsView;
        void loadTeams();
    });

    async function loadTeams(): Promise<void> {
        isLoading = true;
        loadError = '';
        try {
            const nextTeams = await listTeams();
            teams = nextTeams;
            const team = selectedTeamId
                ? nextTeams.find((candidate) => candidate.team_id === selectedTeamId)
                : null;
            if (team) {
                const [nextBilling, nextMemoryCount] = await Promise.all([
                    loadTeamBilling(team),
                    loadTeamMemoryCount(team.team_id),
                ]);
                billing = nextBilling;
                teamMemoryCount = nextMemoryCount;
            } else {
                billing = null;
                teamMemoryCount = 0;
            }
        } catch (error) {
            console.error('[SettingsTeams] Failed to load Teams settings:', error);
            loadError = 'Teams could not be loaded. Please try again.';
            teams = [];
            billing = null;
            teamMemoryCount = 0;
        } finally {
            isLoading = false;
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
            notifyTeamsUpdated();
            notificationStore.success('Team created');
            openTeam(team);
        } catch (error) {
            console.error('[SettingsTeams] Failed to create team:', error);
            notificationStore.error('Failed to create team');
        } finally {
            isCreating = false;
        }
    }

    async function handleInvite(): Promise<void> {
        if (!selectedTeam || !canInvite) return;
        isInviting = true;
        inviteStatus = '';
        try {
            const invite = await createTeamEmailInvite(selectedTeam, inviteEmail);
            inviteEmail = '';
            inviteStatus = invite.deliveryStatus === 'sent' ? 'Invite sent' : 'Invite created';
            notificationStore.success(inviteStatus);
        } catch (error) {
            console.error('[SettingsTeams] Failed to create team invite:', error);
            inviteStatus = 'Invite could not be created';
            notificationStore.error('Failed to create invite');
        } finally {
            isInviting = false;
        }
    }

    function openTeam(team: TeamViewModel): void {
        dispatch('openSettings', {
            settingsPath: `teams/${team.team_id}`,
            direction: 'forward',
            icon: 'team',
            title: team.name || 'Untitled team',
            cameFrom: 'teams',
        });
    }
</script>

<SettingsPageContainer maxWidth="wide">
    <div data-testid="teams-settings-page">
        {#if isLoading}
            <SettingsInfoBox type="info">
                <p><strong>Loading Teams</strong></p>
                <p>Decrypting your joined team list on this device.</p>
            </SettingsInfoBox>
        {:else if loadError}
            <SettingsInfoBox type="warning">
                <p><strong>Teams unavailable</strong></p>
                <p>{loadError}</p>
            </SettingsInfoBox>
            <SettingsButton variant="secondary" dataTestid="teams-settings-retry-button" onClick={() => void loadTeams()}>
                Retry
            </SettingsButton>
        {:else if selectedTeamId && selectedTeam}
            <div data-testid="teams-settings-detail">
                <SettingsSectionHeading title={selectedTeam.name || 'Untitled team'} icon="team" />
                <SettingsCard>
                    <SettingsDetailRow label="Name" value={selectedTeam.name || 'Untitled team'} highlight />
                    <SettingsDetailRow label="Description" value={selectedTeam.description || 'Shared encrypted team'} />
                    <SettingsDetailRow label="Role" value={selectedTeam.role} />
                    <SettingsDetailRow label="Status" value={selectedTeam.status} />
                    <SettingsDetailRow label="Team credits" value={`${billing?.balanceCredits ?? 0}`} />
                    <SettingsDetailRow label="Team memories" value={`${teamMemoryCount}`} />
                    <SettingsDetailRow label="Connected accounts" value="Disabled in V1" muted />
                </SettingsCard>

                <SettingsInfoBox type="info">
                    <p><strong>Personal data boundary</strong></p>
                    <p>Personal memories and personal connected accounts stay outside team context.</p>
                </SettingsInfoBox>

                <SettingsSectionHeading title="Invite members" icon="team" />
                <SettingsInput
                    bind:value={inviteEmail}
                    type="email"
                    placeholder="teammate@example.com"
                    ariaLabel="Invite by email"
                    dataTestid="team-invite-email-input"
                />
                <SettingsButtonGroup align="left">
                    <SettingsButton
                        disabled={!canInvite}
                        loading={isInviting}
                        dataTestid="team-invite-submit"
                        onClick={() => void handleInvite()}
                    >
                        Send invite
                    </SettingsButton>
                </SettingsButtonGroup>
                {#if inviteStatus}
                    <SettingsInfoBox type={inviteStatus.includes('could not') ? 'warning' : 'success'}>
                        <p data-testid="team-invite-status">{inviteStatus}</p>
                    </SettingsInfoBox>
                {/if}
            </div>
        {:else if selectedTeamId}
            <SettingsInfoBox type="warning">
                <p><strong>Team not found</strong></p>
                <p>This team may have been removed or may not be available on this device.</p>
            </SettingsInfoBox>
        {:else}
            <SettingsSectionHeading title={$text('settings.teams')} icon="team" />
            <SettingsInfoBox type="info">
                <p><strong>Teams are account settings.</strong></p>
                <p>Create and manage encrypted teams here. Switch personal/team context from the profile menu.</p>
            </SettingsInfoBox>

            <SettingsSectionHeading title="Create team" icon="team" />
            <SettingsInput
                bind:value={newTeamName}
                placeholder="Team name"
                ariaLabel="Team name"
                dataTestid="team-name-input"
            />
            <SettingsTextarea
                bind:value={newTeamDescription}
                placeholder="What this team works on"
                ariaLabel="Team description"
                rows={3}
                dataTestid="team-description-input"
            />
            <SettingsButtonGroup align="left">
                <SettingsButton
                    disabled={!canCreateTeam}
                    loading={isCreating}
                    dataTestid="team-create-submit"
                    onClick={() => void handleCreateTeam()}
                >
                    Create team
                </SettingsButton>
            </SettingsButtonGroup>

            <SettingsSectionHeading title="Joined teams" icon="team" />
            {#if sortedTeams.length === 0}
                <SettingsInfoBox type="info">
                    <p><strong>No teams yet</strong></p>
                    <p>Create your first encrypted team, then invite teammates from its team settings.</p>
                </SettingsInfoBox>
            {:else}
                {#each sortedTeams as team (team.team_id)}
                    <SettingsItem
                        type="subsubmenu"
                        icon="team"
                        title={team.name || 'Untitled team'}
                        subtitleTop={`${team.role} · ${team.description || 'Shared encrypted team'}`}
                        data-testid="team-settings-team-row"
                        onClick={() => openTeam(team)}
                    />
                {/each}
            {/if}
        {/if}
    </div>
</SettingsPageContainer>
