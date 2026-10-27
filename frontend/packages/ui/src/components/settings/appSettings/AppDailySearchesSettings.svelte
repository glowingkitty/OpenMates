<script lang="ts">
    import { authStore } from '../../../stores/authState';
    import { userProfile } from '../../../stores/userProfile';
    import { activeTeamContext } from '../../../stores/teamStore';
    import { notificationStore } from '../../../stores/notificationStore';
    import { text } from '../../../i18n/translations';
    import { getAppsLibrary, setAppsDailySearches } from '../../../services/appsWorkspaceLibraryService';
    import SettingsCard from '../elements/SettingsCard.svelte';
    import SettingsItem from '../elements/SettingsItem.svelte';

    let { appId }: { appId: string } = $props();
    const owner = $derived($authStore.isAuthenticated ? $userProfile.user_id : null);
    const teamId = $derived($activeTeamContext.teamId ?? undefined);
    const viewer = $derived(Boolean(teamId && $activeTeamContext.team?.role === 'viewer'));
    const identity = $derived(`${owner ?? 'guest'}:${teamId ?? 'personal'}:${$activeTeamContext.epoch}:${appId}`);
    let snapshot = $state<{ identity: string; enabled: boolean } | null>(null);
    let saving = $state(false);
    let generation = 0;
    const ready = $derived(Boolean(owner && snapshot?.identity === identity));

    $effect(() => {
        const currentIdentity = identity;
        const selectedApp = appId;
        const selectedTeam = teamId;
        const current = ++generation;
        snapshot = null;
        saving = false;
        if (!owner) return;
        const controller = new AbortController();
        void getAppsLibrary(selectedApp, selectedTeam, controller.signal).then(library => {
            if (current === generation && currentIdentity === identity) {
                snapshot = { identity: currentIdentity, enabled: library.daily_searches_enabled };
            }
        }).catch(() => {
            if (!controller.signal.aborted && current === generation && currentIdentity === identity) {
                notificationStore.error($text('apps_workspace.library_error'));
            }
        });
        return () => { controller.abort(); generation++; };
    });

    async function toggle(): Promise<void> {
        if (!ready || viewer || saving || !snapshot) return;
        const currentIdentity = identity;
        const current = generation;
        const selectedApp = appId;
        const selectedTeam = teamId;
        saving = true;
        try {
            const library = await setAppsDailySearches(selectedApp, !snapshot.enabled, selectedTeam);
            if (current !== generation || currentIdentity !== identity) return;
            snapshot = { identity: currentIdentity, enabled: library.daily_searches_enabled };
            window.dispatchEvent(new CustomEvent('appsWorkspaceLibraryUpdated', {
                detail: { appId: selectedApp, teamId: selectedTeam }
            }));
        } catch {
            if (current === generation && currentIdentity === identity) notificationStore.error($text('apps_workspace.library_error'));
        } finally {
            if (current === generation && currentIdentity === identity) saving = false;
        }
    }
</script>

{#if owner}
    <SettingsCard>
        <SettingsItem
            title={$text('apps_workspace.daily_searches')}
            subtitleBottom={$text('apps_workspace.daily_searches_description')}
            hasToggle
            checked={ready && snapshot?.enabled === true}
            disabled={!ready || viewer || saving}
            onToggleClick={() => void toggle()}
            data-testid="apps-daily-searches"
        />
    </SettingsCard>
{/if}
