<script lang="ts">
    import { text } from '@repo/ui';
    import AppDetailsHeader from './AppDetailsHeader.svelte';
    import TeamAvatar from '../teams/TeamAvatar.svelte';
    import { loadTeamMembers, type TeamViewModel } from '../../services/teamService';
    import { userProfile } from '../../stores/userProfile';

    let { activeSettingsView, team, memberName = '', scrollTop = 0, onBack }: {
        activeSettingsView: string;
        team?: TeamViewModel | null;
        memberName?: string;
        scrollTop?: number;
        onBack?: () => void;
    } = $props();
    const parts = $derived(activeSettingsView.split('/'));
    const isNew = $derived(parts[1] === 'new');
    const section = $derived(parts[2] ?? '');
    const memberId = $derived(section === 'members' && parts[3] ? decodeURIComponent(parts[3]) : null);
    const suppliedMemberName = $derived(memberName.startsWith('[T:') ? '' : memberName);
    let loadedMemberName = $state('');
    $effect(() => {
        const teamId = team?.team_id;
        const targetMemberId = memberId;
        const accountId = $userProfile.user_id;
        loadedMemberName = '';
        if (!teamId || !targetMemberId || !accountId || suppliedMemberName) return;
        // A chat/cold deep link has no navigation title. Resolve its encrypted
        // member identity rather than treating the member UUID as an i18n key.
        let cancelled = false;
        void loadTeamMembers(teamId).then(members => {
            const member = members.find(item => (item.user_id ?? item.hashed_user_id) === targetMemberId);
            if (!cancelled) loadedMemberName = member?.profile?.display_name?.trim() ?? '';
        }).catch(() => { /* Keep the translated Team member heading if unavailable. */ });
        return () => { cancelled = true; };
    });
    const key = $derived(isNew ? section === 'avatar' ? 'profile_image' : 'create_title'
        : section === 'members' ? parts[3] ? 'team_member' : 'members'
        : section === 'security' ? 'security' : section === 'name' ? 'team_name'
        : section === 'avatar' ? 'profile_image' : section === 'delete' ? 'delete_team' : '');
    const billingTitle = $derived(parts[3] === 'address' ? $text('settings.billing.billing_address')
        : parts[3] === 'invoices' ? $text('common.invoices')
        : parts[3] === 'buy-credits' ? $text('common.buy_credits')
        : parts[3] === 'auto-topup' ? $text('settings.billing.auto_topup')
        : $text('settings.teams_ui.billing'));
    const title = $derived(section === 'billing' ? billingTitle : memberId ? suppliedMemberName || loadedMemberName || $text('settings.teams_ui.team_member')
        : key ? $text(`settings.teams_ui.${key}`) : team?.name ?? $text('settings.teams'));
    const descriptionKey = $derived(isNew ? section === 'avatar' ? 'profile_description' : 'create_description'
        : section === 'members' ? parts[3] ? 'member_detail_description' : 'members_description'
        : section === 'security' ? 'security_description' : section === 'name' ? 'name_description'
        : section === 'avatar' ? 'profile_description' : section === 'delete' ? 'delete_description'
        : team ? 'detail_description' : 'description');
    const icon = $derived(section === 'billing' ? 'coins' : section === 'security' ? 'safety'
        : section === 'avatar' ? 'image' : section === 'name' ? 'text' : section === 'delete' ? 'delete' : 'team');
    const breadcrumb = $derived(isNew && section === 'avatar' ? `... / ${$text('settings.teams_ui.new_team')}`
        : team && section ? `... / ${$text('settings.teams')} / ${team.name}` : `${$text('settings.settings')} / ${$text('settings.teams')}`);
</script>

{#snippet avatar()}
    {#if team}<TeamAvatar {team} size={53} testId="team-settings-header-avatar" />{/if}
{/snippet}
<div data-testid="team-settings-header">
    <AppDetailsHeader {scrollTop} {onBack} breadcrumbLabel={breadcrumb} fullBreadcrumbLabel={breadcrumb}
        settingsLayout="teams" settingsIcon={team && !section ? avatar : undefined}
        settingsPage={{ title, icon, description: section === 'billing' ? $text('settings.billing.team_billing_description') : $text(`settings.teams_ui.${descriptionKey}`) }} />
</div>
