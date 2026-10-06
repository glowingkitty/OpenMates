<!--
  Apple counterpart: apple/OpenMates/Sources/Features/Settings/Views/SettingsTeamsView.swift
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
        loadTeamStorage,
        loadTeamStorageNotice,
        type TeamBillingSummary,
        type TeamStorageNotice,
        type TeamStorageSummary,
        type TeamStorageUnit,
        type TeamViewModel,
    } from '../../services/teamService';

    let { activeSettingsView = 'teams', previewData = null }: {
        activeSettingsView?: string;
        previewData?: { team?: TeamViewModel; teams?: TeamViewModel[]; billing: TeamBillingSummary; storage?: TeamStorageSummary; notice?: TeamStorageNotice | null } | null;
    } = $props();

    const dispatch = createEventDispatcher();

    let teams = $state<TeamViewModel[]>([]);
    let billing = $state<TeamBillingSummary | null>(null);
    let teamMemoryCount = $state(0);
    let storage = $state<TeamStorageSummary | null>(null);
    let storageNotice = $state<TeamStorageNotice | null>(null);
    let storageError = $state(false);
    let noticeError = $state(false);
    let noticeLoading = $state(false);
    let noticeRequestGeneration = 0;
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
    let canManageStorage = $derived(selectedTeam?.role === 'owner' || selectedTeam?.role === 'admin');

    function formatBytes(bytes: number): string {
        if (!Number.isFinite(bytes) || bytes < 0) return '—';
        if (bytes === 0) return '0 B';
        const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB'];
        const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
        const value = bytes / 1024 ** index;
        return `${index >= 2 ? value.toFixed(1) : Math.round(value)} ${units[index]}`;
    }

    function formatUtc(timestamp: number): string {
        return new Date(timestamp * 1000).toLocaleString(undefined, { timeZone: 'UTC', dateStyle: 'medium', timeStyle: 'short' }) + ' UTC';
    }

    function unitLabel(unit: TeamStorageUnit): string {
        return $text(`settings.storage.storage_unit_${unit.kind}`);
    }

    async function fetchStorage(teamId: string): Promise<void> {
        // A route change invalidates any notice request still awaiting a response.
        noticeRequestGeneration += 1;
        noticeLoading = false;
        storage = null;
        storageNotice = null;
        storageError = false;
        noticeError = false;
        try {
            const next = await loadTeamStorage(teamId);
            if (selectedTeamId !== teamId) return;
            storage = next;
            if (next.billing_status !== 'disabled_pending_validation') void fetchNotice(teamId);
        } catch (error) {
            console.error('[SettingsTeams] Failed to load team storage:', error);
            if (selectedTeamId === teamId) storageError = true;
        }
    }

    async function fetchNotice(teamId: string, loadMore = false): Promise<void> {
        if (noticeLoading) return;
        const requestGeneration = ++noticeRequestGeneration;
        noticeLoading = true;
        noticeError = false;
        const previous = loadMore ? storageNotice : null;
        try {
            const next = await loadTeamStorageNotice(teamId, previous?.next_after_unit_id ?? undefined);
            if (selectedTeamId !== teamId || requestGeneration !== noticeRequestGeneration) return;
            if (previous && previous.episode_id === next.episode_id) {
                const known = new Set(previous.units.map((unit) => unit.unit_id));
                next.units = [...previous.units, ...next.units.filter((unit) => !known.has(unit.unit_id))];
            }
            storageNotice = next;
        } catch (error) {
            console.error('[SettingsTeams] Failed to load team storage notice:', error);
            if (selectedTeamId === teamId && requestGeneration === noticeRequestGeneration) noticeError = true;
        } finally {
            if (requestGeneration === noticeRequestGeneration) noticeLoading = false;
        }
    }

    $effect(() => {
        if (loadedRoute === activeSettingsView) return;
        loadedRoute = activeSettingsView;
        void loadTeams();
    });

    async function loadTeams(): Promise<void> {
        // Fixtures are accepted only by the runner-local, development preview route.
        if (previewData && import.meta.env.DEV && typeof window !== 'undefined' && window.location.pathname.startsWith('/dev/preview/')) {
            teams = previewData.teams ?? (previewData.team ? [previewData.team] : []);
            billing = previewData.billing;
            storage = previewData.storage ?? null;
            storageNotice = previewData.notice ?? null;
            teamMemoryCount = 0;
            isLoading = false;
            const team = teams.find((candidate) => candidate.team_id === selectedTeamId);
            if (team && !previewData.storage && (team.role === 'owner' || team.role === 'admin')) void fetchStorage(team.team_id);
            return;
        }
        isLoading = true;
        loadError = '';
        try {
            const nextTeams = await listTeams();
            teams = nextTeams;
            const team = selectedTeamId
                ? nextTeams.find((candidate) => candidate.team_id === selectedTeamId)
                : null;
            if (team) {
                storage = null;
                storageNotice = null;
                storageError = false;
                noticeError = false;
                const [nextBilling, nextMemoryCount] = await Promise.all([
                    loadTeamBilling(team),
                    loadTeamMemoryCount(team.team_id),
                ]);
                billing = nextBilling;
                teamMemoryCount = nextMemoryCount;
                if (team.role === 'owner' || team.role === 'admin') void fetchStorage(team.team_id);
            } else {
                billing = null;
                teamMemoryCount = 0;
                storage = null;
                storageNotice = null;
            }
        } catch (error) {
            console.error('[SettingsTeams] Failed to load Teams settings:', error);
            loadError = 'Teams could not be loaded. Please try again.';
            teams = [];
            billing = null;
            teamMemoryCount = 0;
            storage = null;
            storageNotice = null;
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

                {#if canManageStorage}
                    <SettingsSectionHeading title={$text('settings.team_storage_title')} icon="storage" />
                    {#if storage}
                        <SettingsInfoBox type="info" data-testid="team-storage-policy">
                            {$text('settings.team_storage_policy')}
                        </SettingsInfoBox>
                        <SettingsCard dataTestid="team-storage-summary">
                            <SettingsDetailRow label={$text('settings.storage.storage_total_used')} value={formatBytes(storage.total_bytes)} highlight />
                            <SettingsDetailRow label={$text('settings.storage.storage_measured_at')} value={formatUtc(storage.measurement_at)} />
                            <SettingsDetailRow label={$text('settings.team_storage_free_tier')} value={formatBytes(storage.free_bytes)} />
                            <SettingsDetailRow label={$text('settings.team_storage_billable')} value={`${storage.billable_gib} GiB`} />
                            <SettingsDetailRow label={$text('settings.storage.storage_weekly_cost')} value={$text('settings.storage.storage_credits_per_week', { values: { credits: storage.weekly_cost_credits } })} />
                        </SettingsCard>
                        {#if storage.billing_status === 'disabled_pending_validation'}
                            <SettingsInfoBox type="info" data-testid="team-storage-preview">
                                {$text('settings.team_storage_preview')}
                            </SettingsInfoBox>
                        {:else}
                            {#if storage.billing_status === 'unpaid'}
                                <SettingsInfoBox type="warning">{$text('settings.team_storage_payment_due')}</SettingsInfoBox>
                            {:else if storage.billing_status === 'manual_review'}
                                <SettingsInfoBox type="warning">{$text('settings.team_storage_review')}</SettingsInfoBox>
                            {/if}
                            <SettingsSectionHeading title={$text('settings.team_storage_notice_title')} icon="storage" />
                            {#if storageNotice?.episode_id}
                                <SettingsInfoBox type="warning" data-testid="team-storage-active-notice">
                                    {$text('settings.team_storage_notice_policy')}
                                </SettingsInfoBox>
                                <SettingsCard>
                                    <SettingsDetailRow label={$text('settings.storage.storage_notices_delivered')} value={`${storageNotice.warning_count} / 4`} />
                                    {#if storageNotice.deadline_at}
                                        <SettingsDetailRow label={$text('settings.storage.storage_notice_deadline')} value={formatUtc(storageNotice.deadline_at)} />
                                    {/if}
                                </SettingsCard>
                                {#if storageNotice.manual_review}
                                    <SettingsInfoBox type="warning">{$text('settings.team_storage_review')}</SettingsInfoBox>
                                {/if}
                                {#each storageNotice.units as unit (unit.unit_id)}
                                    <SettingsCard dataTestid="team-storage-affected-unit">
                                        <SettingsDetailRow label={$text('settings.storage.storage_unit_type')} value={unitLabel(unit)} />
                                        <SettingsDetailRow label={$text('settings.storage.storage_unit_oldest')} value={formatUtc(unit.oldest_at)} />
                                        <SettingsDetailRow label={$text('settings.storage.storage_unit_size')} value={formatBytes(unit.bytes)} />
                                    </SettingsCard>
                                {/each}
                                {#if storageNotice.has_more}
                                    <SettingsButton variant="secondary" loading={noticeLoading} dataTestid="team-storage-load-more" onClick={() => void fetchNotice(selectedTeam.team_id, true)}>
                                        {$text('settings.storage.storage_notice_load_more')}
                                    </SettingsButton>
                                {/if}
                            {:else if storageNotice && !noticeError}
                                <SettingsInfoBox data-testid="team-storage-notice-empty">{$text('settings.team_storage_notice_empty')}</SettingsInfoBox>
                            {/if}
                            {#if noticeError}
                                <SettingsInfoBox type="warning">{$text('settings.team_storage_notice_error')}</SettingsInfoBox>
                                <SettingsButton variant="secondary" onClick={() => void fetchNotice(selectedTeam.team_id, Boolean(storageNotice?.has_more))}>
                                    {$text('settings.storage.storage_retry')}
                                </SettingsButton>
                            {/if}
                        {/if}
                    {:else if storageError}
                        <SettingsInfoBox type="warning">{$text('settings.team_storage_error')}</SettingsInfoBox>
                        <SettingsButton variant="secondary" onClick={() => void fetchStorage(selectedTeam.team_id)}>{$text('settings.storage.storage_retry')}</SettingsButton>
                    {/if}
                {/if}

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
