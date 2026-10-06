<script lang="ts">
    import { text } from '@repo/ui';
    import AppDetailsHeader from './AppDetailsHeader.svelte';
    import TeamAvatar from '../teams/TeamAvatar.svelte';
    import type { TeamViewModel } from '../../services/teamService';

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
    const key = $derived(isNew ? section === 'avatar' ? 'profile_image' : 'create_title'
        : section === 'members' ? parts[3] ? 'team_member' : 'members'
        : section === 'security' ? 'security' : section === 'name' ? 'team_name'
        : section === 'avatar' ? 'profile_image' : section === 'delete' ? 'delete_team' : '');
    const billingTitle = $derived(parts[3] === 'address' ? $text('settings.billing.billing_address')
        : parts[3] === 'invoices' ? $text('common.invoices')
        : parts[3] === 'buy-credits' ? $text('common.buy_credits')
        : parts[3] === 'auto-topup' ? $text('settings.billing.auto_topup')
        : $text('settings.teams_ui.billing'));
    const title = $derived(section === 'billing' ? billingTitle : section === 'members' && parts[3] && memberName ? memberName
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
