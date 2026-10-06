<!-- Teams settings. Figma board PzgE78TVxG0eWuEeO6o8ve, node 6118:63631. -->
<script lang="ts">
    import { createEventDispatcher, onDestroy } from 'svelte';
    import { text } from '@repo/ui';
    import TeamAvatar from '../teams/TeamAvatar.svelte';
    import SettingsItem from '../SettingsItem.svelte';
    import TeamSettingsHeader from './TeamSettingsHeader.svelte';
    import {
        SettingsAvatar, SettingsButton,
        SettingsCard, SettingsCheckboxList, SettingsConfirmBlock, SettingsDetailRow, SettingsDropdown,
        SettingsFileUpload, SettingsInfoBox, SettingsInput,
        SettingsLoadingState, SettingsPageContainer, SettingsSectionHeading,
    } from './elements';
    import { notifyTeamsUpdated } from '../../stores/teamStore';
    import { authStore } from '../../stores/authStore';
    import { userProfile } from '../../stores/userProfile';
    import {
        approveTeamName, createTeam, createTeamEmailInvite, createTeamLinkInvite, deleteTeam,
        generatedTeamProfileImageMetadata, getTeam, listTeams, loadTeamBilling, loadTeamStorage, loadTeamStorageNotice,
        loadTeamInvites, loadTeamMemberAvatar, loadTeamMembers, removeTeamMember, revokeTeamInvite, updateTeamMemberRole,
        updateTeamName, updateTeamProfileMetadata, updateTeamSecurity, uploadTeamProfileImage,
        TeamApiError, type InviteRole, type TeamBillingSummary, type TeamInvite,
        type TeamMember, type TeamSecurityPolicy, type TeamStorageNotice, type TeamStorageSummary,
        type TeamStorageUnit, type TeamViewModel,
    } from '../../services/teamService';

    interface PreviewData {
        teams: TeamViewModel[];
        billing?: TeamBillingSummary | null;
        members?: TeamMember[];
        invites?: TeamInvite[];
        storage?: TeamStorageSummary;
        notice?: TeamStorageNotice | null;
        loadStorage?: boolean;
    }
    let { activeSettingsView = 'teams', previewData }: { activeSettingsView?: string; previewData?: PreviewData } = $props();
    const dispatch = createEventDispatcher();
    const iconOptions = [
        { value: 'team', label: $text('settings.teams_ui.icon_team') }, { value: 'project', label: $text('settings.teams_ui.icon_project') },
        { value: 'design', label: $text('settings.teams_ui.icon_design') }, { value: 'coding', label: $text('settings.teams_ui.icon_code') },
        { value: 'heart', label: $text('settings.teams_ui.icon_heart') }, { value: 'travel', label: $text('settings.teams_ui.icon_travel') },
    ];
    const colorOptions = [
        { value: '#4d73ff', label: $text('settings.teams_ui.color_blue') }, { value: '#e35d6a', label: $text('settings.teams_ui.color_red') },
        { value: '#5aab77', label: $text('settings.teams_ui.color_green') }, { value: '#8b62c9', label: $text('settings.teams_ui.color_purple') },
        { value: '#db8f36', label: $text('settings.teams_ui.color_orange') },
    ];
    const roleOptions = [
        { value: 'admin', label: $text('settings.teams_ui.role_admin') }, { value: 'member', label: $text('settings.teams_ui.role_member') },
        { value: 'viewer', label: $text('settings.teams_ui.role_viewer') },
    ];
    const defaultPolicy: TeamSecurityPolicy = {
        restrict_email_domains: false, allowed_email_domains: [],
        require_invite_link_approval: true, require_strong_auth: false,
    };
    const creationDraftKey = 'openmates:team-create-draft';

    let teams = $state<TeamViewModel[]>([]);
    let billing = $state<TeamBillingSummary | null>(null);
    let members = $state<TeamMember[]>([]);
    let memberAvatarUrls = $state<Record<string, string>>({});
    let avatarLoadGeneration = 0;
    let invites = $state<TeamInvite[]>([]);
    let policy = $state<TeamSecurityPolicy>({ ...defaultPolicy });
    let storage = $state<TeamStorageSummary | null>(null);
    let storageNotice = $state<TeamStorageNotice | null>(null);
    let storageError = $state(false);
    let noticeError = $state(false);
    let noticeLoading = $state(false);
    let loadRequestGeneration = 0;
    let storageRequestGeneration = 0;
    let noticeRequestGeneration = 0;
    let isLoading = $state(true);
    let isBusy = $state(false);
    let loadError = $state('');
    let actionError = $state('');
    let actionSuccess = $state('');
    let name = $state('');
    let editName = $state('');
    let iconName = $state('team');
    let iconColor = $state('#4d73ff');
    let avatarOptionsOpen = $state(false);
    let avatarGeneratedChanged = $state(false);
    let draftFile = $state<File | null>(null);
    let draftPreview = $state('');
    let createdForDraft = $state<TeamViewModel | null>(null);
    let inviteEmail = $state('');
    let inviteError = $state('');
    let inviteDomainRejected = $state(false);
    let inviteLink = $state('');
    let inviteRecipient = $state('');
    let domainInput = $state('');
    let checklistDismissed = $state(false);
    let securityOpened = $state(false);
    let removeConfirmed = $state(false);
    let deleteConfirmed = $state(false);
    let loadedRoute = $state('');

    const routeParts = $derived(activeSettingsView.split('/'));
    const selectedTeamId = $derived(routeParts[1] && routeParts[1] !== 'new' ? routeParts[1] : null);
    const subpage = $derived(routeParts[2] ?? '');
    const selectedMemberId = $derived(routeParts[3] ? decodeURIComponent(routeParts[3]) : null);
    const selectedTeam = $derived(teams.find(team => team.team_id === selectedTeamId) ?? null);
    const selectedMember = $derived(members.find(member => (member.user_id ?? member.hashed_user_id) === selectedMemberId) ?? null);
    const canManage = $derived(selectedTeam?.role === 'owner' || selectedTeam?.role === 'admin');
    const canManageStorage = $derived(canManage && !subpage && (!previewData || !!previewData.storage || !!previewData.loadStorage));
    const sortedTeams = $derived([...teams].sort((a, b) => b.createdAt - a.createdAt));
    const inviteIssued = $derived(invites.some(invite => invite.status !== 'revoked'));
    const checklistDone = $derived((billing?.balanceCredits ?? 0) > 0 && securityOpened && inviteIssued);
    const draftTeam = $derived({
        team_id: 'draft', name, description: '', role: 'owner' as const, status: 'draft',
        profileImageMetadata: generatedTeamProfileImageMetadata(iconName, iconColor),
        zeroBalance: 0, createdAt: 0, updatedAt: 0, encrypted: {}, securityPolicy: defaultPolicy,
    } satisfies TeamViewModel);

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

    function storageRouteIsCurrent(teamId: string): boolean {
        return activeSettingsView === `teams/${teamId}` && selectedTeam?.team_id === teamId &&
            (selectedTeam.role === 'owner' || selectedTeam.role === 'admin');
    }

    function resetStorage(): void {
        storageRequestGeneration += 1;
        noticeRequestGeneration += 1;
        storage = null;
        storageNotice = null;
        storageError = false;
        noticeError = false;
        noticeLoading = false;
    }

    async function fetchStorage(teamId: string): Promise<void> {
        if (!storageRouteIsCurrent(teamId) || (previewData && !previewData.loadStorage)) return;
        const requestGeneration = ++storageRequestGeneration;
        noticeRequestGeneration += 1;
        noticeLoading = false;
        storage = null;
        storageNotice = null;
        storageError = false;
        noticeError = false;
        try {
            const next = await loadTeamStorage(teamId);
            if (!storageRouteIsCurrent(teamId) || requestGeneration !== storageRequestGeneration) return;
            storage = next;
            if (next.billing_status !== 'disabled_pending_validation') void fetchNotice(teamId);
        } catch (error) {
            console.error('[SettingsTeams] Failed to load team storage:', error);
            if (storageRouteIsCurrent(teamId) && requestGeneration === storageRequestGeneration) storageError = true;
        }
    }

    async function fetchNotice(teamId: string, loadMore = false): Promise<void> {
        if (!storageRouteIsCurrent(teamId) || (previewData && !previewData.storage && !previewData.loadStorage) || noticeLoading) return;
        const requestGeneration = ++noticeRequestGeneration;
        noticeLoading = true;
        noticeError = false;
        const previous = loadMore ? storageNotice : null;
        try {
            const next = await loadTeamStorageNotice(teamId, previous?.next_after_unit_id ?? undefined);
            if (!storageRouteIsCurrent(teamId) || requestGeneration !== noticeRequestGeneration) return;
            if (previous && previous.episode_id === next.episode_id) {
                const known = new Set(previous.units.map(unit => unit.unit_id));
                next.units = [...previous.units, ...next.units.filter(unit => !known.has(unit.unit_id))];
            }
            storageNotice = next;
        } catch (error) {
            console.error('[SettingsTeams] Failed to load team storage notice:', error);
            if (storageRouteIsCurrent(teamId) && requestGeneration === noticeRequestGeneration) noticeError = true;
        } finally {
            if (requestGeneration === noticeRequestGeneration) noticeLoading = false;
        }
    }

    $effect(() => {
        if (loadedRoute === activeSettingsView) return;
        loadedRoute = activeSettingsView;
        actionError = '';
        actionSuccess = '';
        removeConfirmed = false;
        deleteConfirmed = false;
        avatarOptionsOpen = false;
        avatarGeneratedChanged = false;
        if (activeSettingsView === 'teams/new/avatar' && !previewData) {
            try {
                const saved = JSON.parse(sessionStorage.getItem(creationDraftKey) ?? '{}') as {
                    name?: string; iconName?: string; iconColor?: string; createdTeamId?: string;
                };
                name = saved.name ?? '';
                iconName = saved.iconName ?? 'team';
                iconColor = saved.iconColor ?? '#4d73ff';
            } catch { sessionStorage.removeItem(creationDraftKey); }
        }
        if (selectedTeamId && subpage === 'security') {
            localStorage.setItem(`team-security-opened:${selectedTeamId}`, '1');
            securityOpened = true;
        }
        void loadTeams();
    });

    onDestroy(() => {
        loadRequestGeneration += 1;
        resetStorage();
        if (draftPreview) URL.revokeObjectURL(draftPreview);
        revokeMemberAvatars();
    });

    function revokeMemberAvatars(): void {
        avatarLoadGeneration += 1;
        for (const url of Object.values(memberAvatarUrls)) URL.revokeObjectURL(url);
        memberAvatarUrls = {};
    }

    async function hydrateMemberAvatars(teamId: string, nextMembers: TeamMember[]): Promise<void> {
        const generation = ++avatarLoadGeneration;
        const entries = await Promise.all(nextMembers.map(async member => [
            member.user_id ?? '', await loadTeamMemberAvatar(teamId, member).catch(() => null),
        ] as const));
        if (generation !== avatarLoadGeneration) {
            for (const [, url] of entries) if (url) URL.revokeObjectURL(url);
            return;
        }
        memberAvatarUrls = Object.fromEntries(entries.filter((entry): entry is readonly [string, string] => !!entry[0] && !!entry[1]));
    }

    function navigate(path: string, title: string, cameFrom = activeSettingsView): void {
        dispatch('openSettings', { settingsPath: path, direction: 'forward', icon: 'team', title, cameFrom });
    }

    function saveCreationDraft(teamId?: string): void {
        sessionStorage.setItem(creationDraftKey, JSON.stringify({
            name, iconName, iconColor, createdTeamId: teamId ?? createdForDraft?.team_id,
        }));
    }

    async function loadTeams(): Promise<void> {
        const requestGeneration = ++loadRequestGeneration;
        const route = activeSettingsView;
        resetStorage();
        isLoading = true;
        loadError = '';
        revokeMemberAvatars();
        try {
            const next = previewData?.teams ?? await listTeams();
            if (requestGeneration !== loadRequestGeneration) return;
            teams = next;
            const team = selectedTeamId ? next.find(item => item.team_id === selectedTeamId) : null;
            if (team) {
                policy = { ...defaultPolicy, ...team.securityPolicy };
                if (subpage === 'avatar') {
                    iconName = team.profileImageMetadata?.icon_name ?? 'team';
                    iconColor = team.profileImageMetadata?.background_color ?? '#4d73ff';
                }
                securityOpened = localStorage.getItem(`team-security-opened:${team.team_id}`) === '1';
                checklistDismissed = localStorage.getItem(`team-checklist-dismissed:${team.team_id}`) === '1';
                const manager = team.role === 'owner' || team.role === 'admin';
                const [nextBilling, nextMembers, nextInvites] = previewData
                    ? [previewData.billing ?? null, previewData.members ?? [], previewData.invites ?? []]
                    : await Promise.all([
                        manager ? loadTeamBilling(team) : Promise.resolve(null),
                        loadTeamMembers(team.team_id),
                        manager ? loadTeamInvites(team) : Promise.resolve([]),
                    ]);
                if (requestGeneration !== loadRequestGeneration) return;
                billing = nextBilling;
                members = nextMembers;
                invites = nextInvites;
                if (!previewData) void hydrateMemberAvatars(team.team_id, nextMembers);
                if (route === `teams/${team.team_id}` && manager) {
                    if (previewData?.storage) {
                        storage = previewData.storage;
                        storageNotice = previewData.notice ?? null;
                    } else if (!previewData || previewData.loadStorage) {
                        void fetchStorage(team.team_id);
                    }
                }
            } else {
                billing = null; members = []; invites = [];
            }
        } catch (error) {
            if (requestGeneration !== loadRequestGeneration) return;
            console.error('[SettingsTeams] Load failed', error);
            loadError = $text('settings.teams_ui.load_failed');
        } finally {
            if (requestGeneration === loadRequestGeneration) isLoading = false;
        }
    }

    async function continueCreation(): Promise<void> {
        if (!name.trim() || isBusy) return;
        isBusy = true; actionError = '';
        try {
            await approveTeamName(name);
            saveCreationDraft();
            navigate('teams/new/avatar', 'Profile image', 'teams/new');
        } catch (error) {
            actionError = error instanceof TeamApiError && error.detail === 'TEAM_NAME_BLOCKED'
                ? $text('settings.teams_ui.blocked_name')
                : $text('settings.teams_ui.name_check_failed');
        } finally { isBusy = false; }
    }

    async function chooseImage(file: File): Promise<void> {
        actionError = '';
        if (!['image/jpeg', 'image/png'].includes(file.type)) {
            actionError = $text('settings.teams_ui.jpg_png_only'); return;
        }
        if (file.size > 20 * 1024 * 1024) {
            actionError = $text('settings.teams_ui.image_too_large'); return;
        }
        try {
            const source = URL.createObjectURL(file);
            const image = new Image();
            image.src = source;
            await image.decode();
            const canvas = document.createElement('canvas');
            canvas.width = 340; canvas.height = 340;
            const side = Math.min(image.naturalWidth, image.naturalHeight);
            canvas.getContext('2d')?.drawImage(image,
                (image.naturalWidth - side) / 2, (image.naturalHeight - side) / 2, side, side,
                0, 0, 340, 340);
            URL.revokeObjectURL(source);
            const blob = await new Promise<Blob>((resolve, reject) => canvas.toBlob(
                result => result ? resolve(result) : reject(new Error('Image processing failed')), 'image/jpeg', 0.9));
            if (draftPreview) URL.revokeObjectURL(draftPreview);
            draftFile = new File([blob], 'team-profile.jpg', { type: 'image/jpeg' });
            draftPreview = URL.createObjectURL(blob);
        } catch {
            actionError = $text('settings.teams_ui.image_open_failed');
        }
    }

    async function finishCreation(): Promise<void> {
        if (isBusy || !name.trim()) return;
        isBusy = true; actionError = '';
        try {
            // Keep the created record on image failure so Retry never creates a duplicate.
            let team = createdForDraft;
            if (!team) {
                const saved = JSON.parse(sessionStorage.getItem(creationDraftKey) ?? '{}') as { createdTeamId?: string };
                if (saved.createdTeamId) {
                    team = await getTeam(saved.createdTeamId);
                    createdForDraft = team;
                }
            }
            if (!team) {
                team = await createTeam({ name, profileImageMetadata: generatedTeamProfileImageMetadata(iconName, iconColor) });
                createdForDraft = team;
                saveCreationDraft(team.team_id);
                teams = [team, ...teams.filter(item => item.team_id !== team!.team_id)];
                notifyTeamsUpdated();
            }
            if (draftFile) team = await uploadTeamProfileImage(team, draftFile);
            createdForDraft = null;
            sessionStorage.removeItem(creationDraftKey);
            name = ''; draftFile = null;
            if (draftPreview) URL.revokeObjectURL(draftPreview);
            draftPreview = '';
            teams = [team, ...teams.filter(item => item.team_id !== team!.team_id)];
            notifyTeamsUpdated();
            navigate(`teams/${team.team_id}`, team.name, 'teams');
        } catch (error) {
            if (error instanceof TeamApiError && error.detail === 'ACCOUNT_DELETED') {
                authStore.logout({ skipServerLogout: true, isPolicyViolation: true });
                return;
            }
            actionError = error instanceof TeamApiError && error.detail.startsWith('IMAGE_REJECTED')
                ? $text('settings.teams_ui.image_rejected')
                : createdForDraft ? $text('settings.teams_ui.upload_failed')
                : $text('settings.teams_ui.create_failed');
            if (error instanceof TeamApiError && error.detail === 'IMAGE_REJECTED_FINAL_WARNING') {
                actionError += $text('settings.teams_ui.image_final_warning');
            }
        } finally { isBusy = false; }
    }

    function useGeneratedAvatar(): void {
        avatarGeneratedChanged = true;
        draftFile = null;
        if (draftPreview) URL.revokeObjectURL(draftPreview);
        draftPreview = '';
        actionError = '';
    }

    async function saveName(): Promise<void> {
        if (!selectedTeam || !canManage || !editName.trim()) return;
        isBusy = true; actionError = '';
        try {
            const updated = await updateTeamName(selectedTeam, editName);
            teams = teams.map(item => item.team_id === updated.team_id ? updated : item);
            notifyTeamsUpdated();
            navigate(`teams/${updated.team_id}`, updated.name);
        } catch (error) {
            actionError = error instanceof TeamApiError && error.detail === 'TEAM_NAME_BLOCKED'
                ? $text('settings.teams_ui.blocked_name') : $text('settings.teams_ui.name_save_failed');
        } finally { isBusy = false; }
    }

    async function saveGeneratedAvatar(): Promise<void> {
        if (!selectedTeam || !canManage || (!draftFile && !avatarGeneratedChanged)) return;
        isBusy = true; actionError = '';
        try {
            const updated = draftFile
                ? await uploadTeamProfileImage(selectedTeam, draftFile)
                : await updateTeamProfileMetadata(selectedTeam, generatedTeamProfileImageMetadata(iconName, iconColor));
            teams = teams.map(item => item.team_id === updated.team_id ? updated : item);
            notifyTeamsUpdated();
            navigate(`teams/${updated.team_id}`, updated.name);
        } catch (error) {
            if (error instanceof TeamApiError && error.detail === 'ACCOUNT_DELETED') {
                authStore.logout({ skipServerLogout: true, isPolicyViolation: true });
                return;
            }
            actionError = error instanceof TeamApiError && error.detail.startsWith('IMAGE_REJECTED')
                ? $text('settings.teams_ui.image_rejected_edit') : $text('settings.teams_ui.image_save_failed');
            if (error instanceof TeamApiError && error.detail === 'IMAGE_REJECTED_FINAL_WARNING') {
                actionError += $text('settings.teams_ui.image_final_warning');
            }
        }
        finally { isBusy = false; }
    }

    async function sendInvite(): Promise<void> {
        if (!selectedTeam || !canManage || isBusy) return;
        inviteError = ''; inviteDomainRejected = false; actionSuccess = '';
        const email = inviteEmail.trim().toLowerCase();
        if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
            inviteError = $text('settings.teams_ui.invalid_email'); return;
        }
        const domain = email.split('@')[1];
        if (policy.restrict_email_domains && !policy.allowed_email_domains.includes(domain)) {
            inviteDomainRejected = true;
            inviteError = $text('settings.teams_ui.domain_disallowed'); return;
        }
        isBusy = true;
        try {
            const result = await createTeamEmailInvite(selectedTeam, email);
            inviteEmail = '';
            inviteLink = result.inviteUrl ?? '';
            inviteRecipient = email;
            actionSuccess = $text('settings.teams_ui.invite_ready');
            invites = await loadTeamInvites(selectedTeam);
        } catch { inviteError = $text('settings.teams_ui.invite_failed'); }
        finally { isBusy = false; }
    }

    async function copyInviteLink(): Promise<void> {
        if (!selectedTeam || !canManage || isBusy) return;
        isBusy = true; actionError = '';
        try {
            const invite = await createTeamLinkInvite(selectedTeam);
            inviteLink = invite.inviteUrl ?? '';
            await navigator.clipboard.writeText(inviteLink);
            actionSuccess = $text('settings.teams_ui.link_copied_24h');
            invites = await loadTeamInvites(selectedTeam);
        } catch { actionError = $text('settings.teams_ui.link_failed'); }
        finally { isBusy = false; }
    }

    function openInviteEmailDraft(): void {
        // Figma's "sent" state is a ready-to-share draft: the fragment key must stay client-side.
        if (!inviteRecipient || !inviteLink) return;
        const subject = encodeURIComponent($text('settings.teams_ui.mail_subject'));
        const body = encodeURIComponent(`${$text('settings.teams_ui.mail_body_intro')}\n\n${inviteLink}\n\n${$text('settings.teams_ui.mail_body_privacy')}`);
        window.location.href = `mailto:${encodeURIComponent(inviteRecipient)}?subject=${subject}&body=${body}`;
    }

    async function copyCurrentInvite(): Promise<void> {
        if (!inviteLink) return;
        await navigator.clipboard.writeText(inviteLink);
        actionSuccess = $text('settings.teams_ui.link_copied');
    }

    async function revokeInvite(inviteId: string): Promise<void> {
        if (!selectedTeam || !canManage) return;
        isBusy = true; actionError = '';
        try {
            await revokeTeamInvite(selectedTeam.team_id, inviteId);
            invites = invites.filter(invite => invite.invite_id !== inviteId);
            actionSuccess = $text('settings.teams_ui.invite_revoked');
        } catch { actionError = $text('settings.teams_ui.invite_revoke_failed'); }
        finally { isBusy = false; }
    }

    async function changeRole(member: TeamMember, role: string): Promise<void> {
        if (!selectedTeam || !canManage || !member.user_id || role === member.role) return;
        isBusy = true; actionError = '';
        try {
            await updateTeamMemberRole(selectedTeam.team_id, member.user_id, role as InviteRole);
            members = members.map(item => item === member ? { ...item, role: role as InviteRole } : item);
            actionSuccess = $text('settings.teams_ui.role_updated');
        } catch { actionError = $text('settings.teams_ui.role_update_failed'); }
        finally { isBusy = false; }
    }

    function memberDisplayName(member: TeamMember): string {
        if (member.profile?.display_name) return member.profile.display_name;
        if (member.user_id && member.user_id === $userProfile.user_id) return $userProfile.username || $text('settings.teams_ui.you');
        return $text('settings.teams_ui.team_member');
    }

    async function removeMember(): Promise<void> {
        if (!selectedTeam || !selectedMember?.user_id || !canManage || selectedMember.role === 'owner' || !removeConfirmed) return;
        isBusy = true; actionError = '';
        try {
            await removeTeamMember(selectedTeam.team_id, selectedMember.user_id);
            members = members.filter(member => member !== selectedMember);
            navigate(`teams/${selectedTeam.team_id}/members`, 'Members');
        } catch { actionError = $text('settings.teams_ui.member_remove_failed'); }
        finally { isBusy = false; }
    }

    async function confirmDeleteTeam(): Promise<void> {
        if (!selectedTeam || selectedTeam.role !== 'owner' || !deleteConfirmed || isBusy) return;
        const teamId = selectedTeam.team_id;
        isBusy = true; actionError = '';
        try {
            await deleteTeam(teamId);
            teams = teams.filter(team => team.team_id !== teamId);
            localStorage.removeItem(`team-security-opened:${teamId}`);
            localStorage.removeItem(`team-checklist-dismissed:${teamId}`);
            notifyTeamsUpdated();
            navigate('teams', $text('settings.teams'), `teams/${teamId}/delete`);
        } catch {
            actionError = $text('settings.teams_ui.delete_failed');
        } finally { isBusy = false; }
    }

    async function savePolicy(next: TeamSecurityPolicy): Promise<void> {
        if (!selectedTeam || !canManage) return;
        const previous = policy;
        policy = next;
        isBusy = true; actionError = '';
        try { policy = await updateTeamSecurity(selectedTeam.team_id, next); }
        catch { policy = previous; actionError = $text('settings.teams_ui.security_save_failed'); }
        finally { isBusy = false; }
    }

    async function addDomain(): Promise<void> {
        const domain = domainInput.trim().toLowerCase().replace(/^@/, '');
        if (!/^[a-z0-9.-]+\.[a-z]{2,}$/.test(domain)) { actionError = $text('settings.teams_ui.invalid_domain'); return; }
        if (policy.allowed_email_domains.includes(domain)) { actionError = $text('settings.teams_ui.duplicate_domain'); return; }
        await savePolicy({ ...policy, restrict_email_domains: true, allowed_email_domains: [...policy.allowed_email_domains, domain] });
        if (!actionError) domainInput = '';
    }

    function openMember(member: TeamMember): void {
        if (selectedTeam) navigate(`teams/${selectedTeam.team_id}/members/${encodeURIComponent(member.user_id ?? member.hashed_user_id ?? '')}`, memberDisplayName(member));
    }

    function regenerateAvatar(): void {
        useGeneratedAvatar();
        avatarGeneratedChanged = true;
        avatarOptionsOpen = true;
        iconName = iconOptions[(iconOptions.findIndex(option => option.value === iconName) + 1) % iconOptions.length].value;
        iconColor = colorOptions[(colorOptions.findIndex(option => option.value === iconColor) + 1) % colorOptions.length].value;
        if (!selectedTeam) saveCreationDraft();
    }

    function dismissChecklist(): void {
        if (!selectedTeam) return;
        localStorage.setItem(`team-checklist-dismissed:${selectedTeam.team_id}`, '1');
        checklistDismissed = true;
    }
</script>

{#snippet memberRow(member: TeamMember)}
    {#snippet portrait()}
        <SettingsAvatar src={member.user_id ? memberAvatarUrls[member.user_id] ?? '' : ''} size="xs"
            ariaLabel={memberDisplayName(member)} generatedIcon={member.profile?.avatar.icon_name ?? ''}
            generatedBackground={member.profile?.avatar.background_color ?? ''} />
    {/snippet}
    <SettingsItem type="subsubmenu" leftContent={portrait} title={memberDisplayName(member)} subtitleBottom={member.role}
        hasModifyButton={canManage && member.role !== 'owner'} data-testid="team-member-row"
        onModifyClick={() => openMember(member)} onClick={() => openMember(member)} />
{/snippet}

{#snippet avatarEditor()}
    <div class="avatar-editor">
        <div class="avatar-stage">
            {#if draftPreview}<SettingsAvatar src={draftPreview} size="xl" ariaLabel={$text('settings.teams_ui.image_preview')} />
            {:else}<SettingsAvatar size="xl" ariaLabel={$text('settings.teams_ui.image_preview')}><TeamAvatar team={selectedTeam && !avatarGeneratedChanged ? selectedTeam : selectedTeam ? { ...selectedTeam, profileImageMetadata: generatedTeamProfileImageMetadata(iconName, iconColor) } : draftTeam} size={144} testId="team-avatar-preview" /></SettingsAvatar>{/if}
            <button class="regenerate-avatar" type="button" data-testid="team-avatar-regenerate" aria-label={$text('settings.teams_ui.change_generated_avatar')}
                disabled={isBusy || (!!selectedTeam && !canManage)} onclick={regenerateAvatar}><span aria-hidden="true"></span></button>
        </div>
        <SettingsFileUpload accept=".jpg,.jpeg,.png,image/jpeg,image/png" label={$text('settings.teams_ui.select_image')}
            disabled={isBusy || (!!selectedTeam && !canManage)} dataTestid="team-avatar-file" onFileSelected={(file) => void chooseImage(file)} />
        {#if avatarOptionsOpen}
            <div class="avatar-options">
                <SettingsDropdown bind:value={iconName} options={iconOptions} ariaLabel={$text('settings.teams_ui.team_icon')} dataTestid="team-avatar-icon" onChange={() => saveCreationDraft()} />
                <SettingsDropdown bind:value={iconColor} options={colorOptions} ariaLabel={$text('settings.teams_ui.team_color')} dataTestid="team-avatar-color" onChange={() => saveCreationDraft()} />
            </div>
        {/if}
        {#if draftFile}<SettingsButton variant="secondary" dataTestid="team-avatar-use-generated" onClick={useGeneratedAvatar}>{$text('settings.teams_ui.use_generated')}</SettingsButton>{/if}
    </div>
{/snippet}

<div class="teams-frame" class:preview-frame={!!previewData}>
    {#if previewData}<TeamSettingsHeader {activeSettingsView} team={selectedTeam} memberName={selectedMember ? memberDisplayName(selectedMember) : ''} />{/if}
<SettingsPageContainer maxWidth="wide">
    <div class="teams-body" class:security-body={subpage === 'security'} data-testid="teams-settings-page">
        {#if isLoading}
            <SettingsLoadingState text={$text('settings.teams_ui.loading_teams')} />
        {:else if loadError}
            <SettingsInfoBox type="error"><p>{loadError}</p></SettingsInfoBox>
            <SettingsButton variant="secondary" dataTestid="teams-settings-retry-button" onClick={() => void loadTeams()}>{$text('settings.teams_ui.retry')}</SettingsButton>
        {:else if activeSettingsView === 'teams'}
            {#each sortedTeams as team (team.team_id)}
                {#snippet teamAvatar()}
                    <TeamAvatar {team} size={43} testId="team-settings-team-avatar" />
                {/snippet}
                <SettingsItem type="subsubmenu" leftContent={teamAvatar} title={team.name} subtitleBottom={`${team.role} ${$text('settings.teams_ui.role_suffix')}`}
                    data-testid="team-settings-team-row" onClick={() => navigate(`teams/${team.team_id}`, team.name, 'teams')} />
            {:else}
                <SettingsInfoBox type="info"><p>{$text('settings.teams_ui.empty_teams')}</p></SettingsInfoBox>
            {/each}
            <SettingsItem type="subsubmenu" icon="create" title={$text('settings.teams_ui.new_team')} data-testid="team-create-open"
                onClick={() => navigate('teams/new', $text('settings.teams_ui.create_title'), 'teams')} />
        {:else if activeSettingsView === 'teams/new'}
            <!-- TODO: Add the source-backed Teams explainer video when available. -->
            <SettingsInput bind:value={name} placeholder={$text('settings.teams_ui.name_placeholder')} ariaLabel={$text('settings.teams_ui.team_name')} dataTestid="team-name-input" />
            <SettingsButton variant="cta" fullWidth disabled={!name.trim()} loading={isBusy} dataTestid="team-create-continue"
                onClick={() => void continueCreation()}>{$text('settings.teams_ui.continue')}</SettingsButton>
            <ul class="creation-benefits">
                {#each ['benefit_multiple_teams', 'benefit_no_subscription', 'benefit_no_minimum', 'benefit_workspaces', 'benefit_encryption'] as key}<li>{$text(`settings.teams_ui.${key}`)}</li>{/each}
            </ul>
        {:else if activeSettingsView === 'teams/new/avatar'}
            {@render avatarEditor()}
            <SettingsButton variant="cta" fullWidth loading={isBusy} dataTestid="team-create-submit" onClick={() => void finishCreation()}>
                <span class="cta-create-icon" aria-hidden="true"></span>
                {createdForDraft && draftFile ? $text('settings.teams_ui.retry_upload') : $text('settings.teams_ui.create_action')}
            </SettingsButton>
        {:else if selectedTeam && subpage === 'members' && selectedMemberId}
            {#if selectedMember}
                <SettingsAvatar src={selectedMember.user_id ? memberAvatarUrls[selectedMember.user_id] ?? '' : ''}
                    size="lg" ariaLabel={memberDisplayName(selectedMember)}
                    generatedIcon={selectedMember.profile?.avatar.icon_name ?? ''}
                    generatedBackground={selectedMember.profile?.avatar.background_color ?? ''} />
                <SettingsCard dataTestid="team-member-detail">
                    <SettingsDetailRow label={$text('settings.teams_ui.role_label')} value={selectedMember.role} />
                    <SettingsDetailRow label={$text('settings.teams_ui.status_label')} value={selectedMember.status} />
                </SettingsCard>
                {#if canManage && selectedMember.role !== 'owner' && selectedMember.user_id}
                    <SettingsSectionHeading title={$text('settings.teams_ui.role_label')} icon="team" />
                    <SettingsDropdown value={selectedMember.role} options={roleOptions} disabled={isBusy} ariaLabel={$text('settings.teams_ui.member_role')}
                        dataTestid="team-member-detail-role" onChange={(role) => void changeRole(selectedMember, role)} />
                    <SettingsSectionHeading title={$text('settings.teams_ui.remove_member')} icon="delete" />
                    <SettingsConfirmBlock warningText={$text('settings.teams_ui.remove_warning')}
                        confirmLabel={$text('settings.teams_ui.remove_confirm')} bind:checked={removeConfirmed} />
                    <SettingsButton variant="danger" disabled={!removeConfirmed} loading={isBusy} dataTestid="team-member-remove"
                        onClick={() => void removeMember()}>{$text('settings.teams_ui.remove_member')}</SettingsButton>
                {:else if !selectedMember.user_id}
                    <SettingsInfoBox type="info"><p>{$text('settings.teams_ui.legacy_member_info')}</p></SettingsInfoBox>
                {/if}
            {:else}
                <SettingsInfoBox type="warning"><p>{$text('settings.teams_ui.member_not_found')}</p></SettingsInfoBox>
            {/if}
        {:else if selectedTeam && subpage === 'members'}
            <SettingsSectionHeading title={$text('settings.teams_ui.admins')} icon="safety" />
            {#each members.filter(member => member.role === 'owner' || member.role === 'admin') as member}
                {@render memberRow(member)}
            {/each}
            <SettingsSectionHeading title={$text('settings.teams_ui.members')} icon="user" />
            {#each members.filter(member => member.role !== 'owner' && member.role !== 'admin') as member}
                {@render memberRow(member)}
            {/each}
            {#if canManage}
                <p class="settings-help">{$text('settings.teams_ui.invite_members_guidance')}</p>
                <SettingsInput bind:value={inviteEmail} type="email" placeholder={$text('settings.teams_ui.invite_email')}
                    ariaLabel={$text('settings.teams_ui.invite_email')} dataTestid="team-invite-email-input" hasError={!!inviteError} />
                {#if inviteError}
                    <SettingsInfoBox type="error" plain data-testid="team-invite-inline-error"><p class="inline-field-error" role="alert">{inviteError}
                        {#if inviteDomainRejected}
                            <a href={`#settings/teams/${selectedTeam.team_id}/security`} onclick={(event) => { event.preventDefault(); navigate(`teams/${selectedTeam.team_id}/security`, $text('settings.teams_ui.security')); }}>{$text('settings.teams_ui.open_security')}</a>
                        {/if}
                    </p></SettingsInfoBox>
                {/if}
                <div class="invite-submit" class:shown={!!inviteEmail.trim()}><SettingsButton variant="cta" fullWidth loading={isBusy} dataTestid="team-invite-submit" onClick={() => void sendInvite()}>{$text('settings.teams_ui.invite_action')}</SettingsButton></div>
                {#if inviteRecipient && inviteLink}
                    <SettingsButton dataTestid="team-invite-open-email" onClick={openInviteEmailDraft}>{$text('settings.teams_ui.open_email_draft')}</SettingsButton>
                    <SettingsButton variant="secondary" dataTestid="team-invite-copy-secure-link" onClick={() => void copyCurrentInvite()}>{$text('settings.teams_ui.copy_secure_link')}</SettingsButton>
                {/if}
                <p class="settings-help">{$text('settings.teams_ui.invite_sharing_guidance')}</p>
                <SettingsItem type="subsubmenu" icon="copy" title={$text('settings.teams_ui.copy_link')} data-testid="team-copy-invite-link" onClick={() => void copyInviteLink()} />
                {#if inviteLink}<SettingsInfoBox type="info"><p>{$text('settings.teams_ui.share_link_info')}</p></SettingsInfoBox>{/if}
                {#if invites.some(invite => invite.status === 'pending' || invite.status === 'created' || invite.status === 'sent')}
                    <SettingsSectionHeading title={$text('settings.teams_ui.pending_invites')} icon="team" />
                    {#each invites.filter(invite => ['pending', 'created', 'sent'].includes(invite.status)) as invite (invite.invite_id)}
                        {#snippet deleteInvite()}
                            <SettingsButton variant="ghost" size="sm" iconOnly ariaLabel={$text('settings.teams_ui.revoke_invite')} dataTestid={`team-invite-revoke-${invite.invite_id}`}
                                onClick={() => void revokeInvite(invite.invite_id)}><span class="delete-row-icon" aria-hidden="true"></span></SettingsButton>
                        {/snippet}
                        <SettingsItem type="subsubmenu" title={invite.recipientEmail || $text('settings.teams_ui.invite_link')}
                            subtitleBottom={$text(invite.kind === 'email' && invite.status !== 'sent' ? 'settings.teams_ui.invite_ready_pending' : 'settings.teams_ui.invite_waiting')}
                            rightContent={deleteInvite} data-testid="team-pending-invite-row" />
                    {/each}
                {/if}
            {/if}
        {:else if selectedTeam && subpage === 'security'}
            <SettingsItem type="quickaction" icon="email" title={$text('settings.teams_ui.domain_restriction')} checked={policy.restrict_email_domains}
                hasToggle disabled={!canManage || isBusy} data-testid="team-security-domain-toggle"
                onClick={() => void savePolicy({ ...policy, restrict_email_domains: !policy.restrict_email_domains })} />
            {#if policy.restrict_email_domains}
                <SettingsInput bind:value={domainInput} placeholder={$text('settings.teams_ui.domain_placeholder')} ariaLabel={$text('settings.teams_ui.domain_placeholder')} dataTestid="team-security-domain-input" />
                {#if domainInput.trim()}<SettingsButton variant="cta" fullWidth disabled={!canManage || isBusy} dataTestid="team-security-domain-add" onClick={() => void addDomain()}>{$text('settings.teams_ui.allow_domain')}</SettingsButton>{/if}
                {#each policy.allowed_email_domains as domain}
                    {#snippet deleteDomain()}
                        {#if canManage}<SettingsButton variant="ghost" size="sm" iconOnly ariaLabel={`${$text('settings.teams_ui.remove')} ${domain}`} dataTestid={`team-security-domain-remove-${domain}`}
                            onClick={() => void savePolicy({ ...policy, allowed_email_domains: policy.allowed_email_domains.filter(value => value !== domain) })}><span class="delete-row-icon" aria-hidden="true"></span></SettingsButton>{/if}
                    {/snippet}
                    <SettingsItem type="subsubmenu" title={domain} rightContent={deleteDomain} data-testid="team-security-domain-row" />
                {/each}
            {/if}
            <SettingsItem type="quickaction" icon="signup-approval" title={$text('settings.teams_ui.signup_approval')} checked={policy.require_invite_link_approval}
                hasToggle disabled={!canManage || isBusy} data-testid="team-security-approval-toggle"
                onClick={() => void savePolicy({ ...policy, require_invite_link_approval: !policy.require_invite_link_approval })} />
            <p class="settings-help">{$text('settings.teams_ui.approval_info')}</p>
            <SettingsItem type="quickaction" icon="passkey" title={$text('settings.teams_ui.strong_auth')} checked={policy.require_strong_auth}
                hasToggle disabled={!canManage || isBusy} data-testid="team-security-strong-auth-toggle"
                onClick={() => void savePolicy({ ...policy, require_strong_auth: !policy.require_strong_auth })} />
            <p class="settings-help">{$text('settings.teams_ui.strong_auth_info')}</p>
            {#if !policy.restrict_email_domains && !policy.require_invite_link_approval}
                <SettingsInfoBox type="warning" data-testid="team-security-open-link-warning"><p>{$text('settings.teams_ui.open_link_warning')}</p></SettingsInfoBox>
            {/if}
        {:else if selectedTeam && subpage === 'name'}
            <SettingsInput bind:value={editName} placeholder={selectedTeam.name} ariaLabel={$text('settings.teams_ui.team_name')} dataTestid="team-edit-name-input" />
            <SettingsButton variant="cta" fullWidth disabled={!canManage || !editName.trim()} loading={isBusy} dataTestid="team-edit-name-save" onClick={() => void saveName()}>{$text('settings.teams_ui.save_name')}</SettingsButton>
        {:else if selectedTeam && subpage === 'avatar'}
            {@render avatarEditor()}
            <SettingsButton variant="cta" fullWidth disabled={!canManage || (!draftFile && !avatarGeneratedChanged)} loading={isBusy} dataTestid="team-avatar-save" onClick={() => void saveGeneratedAvatar()}>{$text('settings.teams_ui.save_profile')}</SettingsButton>
        {:else if selectedTeam && subpage === 'delete'}
            {#if selectedTeam.role === 'owner'}
                <SettingsConfirmBlock warningText={$text('settings.teams_ui.delete_warning')}
                    confirmLabel={$text('settings.teams_ui.delete_confirm')} bind:checked={deleteConfirmed} />
                <SettingsButton variant="danger" disabled={!deleteConfirmed} loading={isBusy} dataTestid="team-delete-submit"
                    onClick={() => void confirmDeleteTeam()}>{$text('settings.teams_ui.delete_team')}</SettingsButton>
            {:else}
                <SettingsInfoBox type="warning"><p>{$text('settings.teams_ui.owner_only_delete')}</p></SettingsInfoBox>
            {/if}
        {:else if selectedTeam && !subpage}
            <div data-testid="teams-settings-detail">
                {#if !checklistDismissed && !checklistDone && canManage}
                    <div class="setup-card" data-testid="team-setup-checklist">
                        <div class="setup-heading"><span class="setup-checkmark" aria-hidden="true"></span><strong>{$text('settings.teams_ui.setup_title')}</strong><span>{$text('settings.teams_ui.next_steps')}:</span></div>
                        <SettingsCheckboxList options={[
                            { id: 'credits', label: $text('settings.teams_ui.buy_credits'), description: $text('settings.teams_ui.credit_purpose'), icon: 'coins', checked: (billing?.balanceCredits ?? 0) > 0 },
                            { id: 'security', label: $text('settings.teams_ui.confirm_security'), icon: 'safety', checked: securityOpened },
                            { id: 'members', label: $text('settings.teams_ui.invite_step'), icon: 'team', checked: inviteIssued },
                        ]} onChange={(id) => {
                            if (id === 'credits') navigate(`teams/${selectedTeam.team_id}/billing`, 'Billing & usage');
                            if (id === 'security') navigate(`teams/${selectedTeam.team_id}/security`, 'Security');
                            if (id === 'members') navigate(`teams/${selectedTeam.team_id}/members`, 'Members');
                        }} />
                        <SettingsButton variant="ghost" dataTestid="team-checklist-dismiss" onClick={dismissChecklist}>{$text('settings.teams_ui.dismiss_checklist')}</SettingsButton>
                    </div>
                {/if}
                {#if canManage}
                    <SettingsItem type="subsubmenu" icon="coins" title={$text('settings.teams_ui.billing')} data-testid="team-billing-open"
                        onClick={() => navigate(`teams/${selectedTeam.team_id}/billing`, $text('settings.teams_ui.billing'))} />
                {/if}
                <SettingsItem type="subsubmenu" icon="team" title={$text('settings.teams_ui.members')} data-testid="team-members-open"
                    onClick={() => navigate(`teams/${selectedTeam.team_id}/members`, $text('settings.teams_ui.members'))} />
                <SettingsItem type="subsubmenu" icon="safety" title={$text('settings.teams_ui.security')} data-testid="team-security-open"
                    onClick={() => navigate(`teams/${selectedTeam.team_id}/security`, $text('settings.teams_ui.security'))} />
                {#if canManage}
                    <SettingsItem type="subsubmenu" icon="text" title={$text('settings.teams_ui.name')} data-testid="team-name-open"
                        onClick={() => { editName = selectedTeam.name; navigate(`teams/${selectedTeam.team_id}/name`, $text('settings.teams_ui.name')); }} />
                    <SettingsItem type="subsubmenu" icon="image" title={$text('settings.teams_ui.profile_image')} data-testid="team-avatar-open"
                        onClick={() => navigate(`teams/${selectedTeam.team_id}/avatar`, $text('settings.teams_ui.profile_image'))} />
                {/if}
                {#if selectedTeam.role === 'owner'}
                    <SettingsItem type="subsubmenu" icon="delete" iconColor="var(--color-error)" title={$text('settings.teams_ui.delete_team')} data-testid="team-delete-open"
                        onClick={() => navigate(`teams/${selectedTeam.team_id}/delete`, $text('settings.teams_ui.delete_team'))} />
                {/if}
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
            </div>
        {:else if selectedTeamId}
            <SettingsInfoBox type="warning"><p>{$text('settings.teams_ui.team_not_found')}</p></SettingsInfoBox>
        {/if}
        {#if actionError}<SettingsInfoBox type="error" data-testid="team-action-error"><p>{actionError}</p></SettingsInfoBox>{/if}
        {#if actionSuccess}<SettingsInfoBox type="success" data-testid="team-invite-status"><p>{actionSuccess}</p></SettingsInfoBox>{/if}
    </div>
</SettingsPageContainer>
</div>

<style>
    .teams-frame { width: 100%; background: var(--color-grey-20); }
    .preview-frame { min-height: 719px; }
    .teams-body { display: flex; flex-direction: column; gap: 16px; padding: 0 3px 8px; }
    .teams-body :global(.menu-item) { margin: 0 10px; padding: 5px 10px; }
    .teams-body :global(.menu-title) { font-size: var(--font-size-p); font-weight: 700; }
    .security-body :global(.menu-item) { padding-inline: 1px; }
    .security-body :global(.icon-container) { margin-inline-end: 17px; }
    .security-body :global(.toggle-container) { padding: 0; }
    .security-body :global(.menu-title) { white-space: normal; overflow: visible; text-overflow: clip; }
    .teams-body :global(.settings-section-heading) { margin: 0; }
    .teams-body :global(.heading-icon) { height: 24px; }
    .teams-body :global(.heading-icon::after) { mask-size: 24px 24px; -webkit-mask-size: 24px 24px; }
    .teams-body :global(.heading-bar) { height: 3px; }
    .teams-body :global(.settings-file-upload) { min-height: 54px; }
    .teams-body :global(.settings-button.cta) { font-size: var(--font-size-p); font-weight: 500; }
    .teams-body :global([data-testid="team-delete-open"] .menu-title) { background: none; -webkit-text-fill-color: var(--color-error); color: var(--color-error); }
    .avatar-stage { position: relative; left: -7.5px; width: 144px; height: 144px; margin: 10px auto 20px; }
    .avatar-editor { margin-bottom: 4px; }
    .regenerate-avatar { min-width: 0; padding: 0; margin: 0; filter: none; scale: 1; box-sizing: border-box; position: absolute; bottom: 0; right: 0; width: 40px; height: 40px; display: grid; place-items: center; border: 0; border-radius: 50%; background: var(--color-grey-0); box-shadow: var(--shadow-sm); cursor: pointer; }
    .regenerate-avatar span { width: 27px; height: 27px; background: var(--color-primary); mask: var(--icon-url-reload) center / contain no-repeat; }
    .regenerate-avatar:focus-visible { outline: 2px solid var(--color-primary-start); outline-offset: 2px; }
    .regenerate-avatar:disabled { opacity: .5; cursor: not-allowed; }
    .avatar-options { display: flex; flex-direction: column; gap: 12px; margin-top: 16px; }
    .delete-row-icon { width: 20px; height: 20px; background: var(--color-error); mask: var(--icon-url-delete) center / contain no-repeat; }
    .cta-create-icon { width: 20px; height: 20px; margin-inline-end: 8px; background: var(--color-font-button); mask: var(--icon-url-create) center / contain no-repeat; }
    .creation-benefits { margin: 8px 20px 0 38px; padding: 0; color: var(--color-font-secondary); font-size: var(--font-size-small); line-height: 1.3; }
    .settings-help { margin: 0 18px; color: var(--color-font-secondary); font-size: var(--font-size-small); line-height: 1.3; }
    .inline-field-error { color: var(--color-error); font-size: var(--font-size-small); line-height: 1.3; }
    .inline-field-error a { color: inherit; text-decoration: underline; }
    .invite-submit { display: none; }
    .invite-submit.shown { display: block; }
    .setup-card { margin: 5px 15px 16px 16px; padding: 8.5px 6px 0; border-radius: 19px; background: var(--color-grey-0); box-shadow: var(--shadow-sm); }
    .setup-heading { display: flex; flex-direction: column; align-items: center; gap: 0; font-size: var(--font-size-p); font-weight: 700; line-height: 1.25; margin-bottom: 17px; }
    .setup-heading > span:last-child { color: var(--color-font-secondary); margin-top: 3px; }
    .setup-checkmark { width: 51px; height: 48px; background: var(--color-success); mask: var(--icon-url-check) center / contain no-repeat; margin: 0 auto; }
    .setup-card :global(.checkbox-item) { margin: 0; padding: 1px 0; gap: 4px; }
    .setup-card :global(.checkbox-input) { width: 20px; height: 20px; margin: 0; }
    .setup-card :global(.checkbox-icon) { width: 16px; height: 16px; margin-top: 2px; background: var(--color-primary); }
    .setup-card :global(.settings-checkbox-list) { gap: 2px; }
    .setup-card :global(.checkbox-label), .setup-card :global(.checkbox-description) { font-size: var(--font-size-p); font-weight: 500; }
    .setup-card :global(.checkbox-content) { min-width: 0; flex: 1; line-height: 1.25; }
    .setup-card :global(.checkbox-description) { margin-inline-start: -18px; width: calc(100% + 18px); margin-top: 0; color: var(--color-font-primary); }
    .setup-card :global(.settings-button-wrapper) { text-align: center; margin-top: 12px; }
    .setup-card :global(.settings-button) { padding: 5.5px 0; font-size: var(--font-size-small); font-weight: 500; }
</style>
