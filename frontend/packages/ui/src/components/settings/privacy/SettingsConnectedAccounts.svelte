<!--
  SettingsConnectedAccounts.svelte

  Privacy settings page for encrypted connected accounts. It lists browser-
  decrypted safe account summaries only: labels, app/provider type,
  capabilities, and runtime modes. It never decrypts refresh-token bundles or
  provider account display fields for rendering.
-->
<script lang="ts">
    import { onMount } from 'svelte';
    import { text } from '@repo/ui';
    import SettingsItem from '../../SettingsItem.svelte';
    import { authStore } from '../../../stores/authStore';
    import { userProfile } from '../../../stores/userProfile';
    import {
        listConnectedAccounts,
        summarizeConnectedAccountRows,
        type ConnectedAccountSummary
    } from '../../../services/connectedAccountStorageService';
    import {
        finalizeOAuthHandoffAsConnectedAccount,
        startGoogleCalendarOAuth
    } from '../../../services/connectedAccountOAuthService';
    import {
        SettingsButton,
        SettingsCard,
        SettingsDetailRow,
        SettingsInfoBox,
        SettingsSectionHeading
    } from '../../settings/elements';

    const CALENDAR_UPDATE_ACCOUNT_KEY = 'openmates_calendar_update_account_id';

    let summaries = $state<ConnectedAccountSummary[]>([]);
    let selectedAccountId = $state('');
    let loading = $state(false);
    let action = $state<'idle' | 'updating' | 'finalizing'>('idle');
    let error = $state('');
    let success = $state('');
    let finalizedOAuthHandoffId = $state('');

    let isAuthenticated = $derived($authStore.isAuthenticated);
    let selectedAccount = $derived(
        summaries.find((summary) => summary.id === selectedAccountId) ?? summaries[0] ?? null
    );

    onMount(() => {
        if (!isAuthenticated) return;
        void initializeConnectedAccounts();
    });

    $effect(() => {
        if (!isAuthenticated) return;
        const handoffId = getOAuthHandoffId();
        const userId = $userProfile.user_id;
        if (!handoffId || !userId || finalizedOAuthHandoffId === handoffId || action === 'finalizing') {
            return;
        }
        void initializeConnectedAccounts();
    });

    async function initializeConnectedAccounts() {
        await finalizeOAuthHandoffFromUrl();
        await loadConnectedAccounts(false);
    }

    async function loadConnectedAccounts(clearExistingError = true) {
        loading = true;
        if (clearExistingError) error = '';
        try {
            const rows = await listConnectedAccounts();
            summaries = await summarizeConnectedAccountRows(rows);
            if (!selectedAccountId && summaries.length > 0) {
                selectedAccountId = summaries[0].id;
            }
        } catch (loadError) {
            console.warn('[SettingsConnectedAccounts] Failed to load connected accounts:', loadError);
            error = $text('settings.privacy.connected_accounts.load_error');
        } finally {
            loading = false;
        }
    }

    async function finalizeOAuthHandoffFromUrl() {
        const handoffId = getOAuthHandoffId();
        if (!handoffId || finalizedOAuthHandoffId === handoffId) return;
        const userId = $userProfile.user_id;
        if (!userId) return;
        finalizedOAuthHandoffId = handoffId;
        action = 'finalizing';
        error = '';
        try {
            const pendingUpdateAccountId = sessionStorage.getItem(CALENDAR_UPDATE_ACCOUNT_KEY) || undefined;
            const existingCapabilities = pendingUpdateAccountId
                ? await loadExistingCapabilitiesForUpdate(pendingUpdateAccountId)
                : undefined;
            await finalizeOAuthHandoffAsConnectedAccount({
                userId,
                handoffId,
                connectedAccountId: pendingUpdateAccountId,
                updateExisting: Boolean(pendingUpdateAccountId),
                capabilitiesOverride: existingCapabilities
            });
            sessionStorage.removeItem(CALENDAR_UPDATE_ACCOUNT_KEY);
            success = $text('settings.privacy.connected_accounts.updated_success');
            removeOAuthHandoffQueryParam();
        } catch (finalizeError) {
            console.warn('[SettingsConnectedAccounts] Failed to finalize connected-account OAuth handoff:', finalizeError);
            error = $text('settings.privacy.connected_accounts.finalize_error');
        } finally {
            action = 'idle';
        }
    }

    async function loadExistingCapabilitiesForUpdate(accountId: string): Promise<string[]> {
        const rows = await listConnectedAccounts();
        const existingSummary = (await summarizeConnectedAccountRows(rows)).find((summary) => summary.id === accountId);
        if (!existingSummary) {
            throw new Error(`Connected account update target not found: ${accountId}`);
        }
        return mergeCapabilities(existingSummary.capabilities, ['write']);
    }

    function mergeCapabilities(currentCapabilities: string[], newCapabilities: string[]): string[] {
        return Array.from(new Set([...currentCapabilities, ...newCapabilities]));
    }

    async function addCalendarWriteAccess(account: ConnectedAccountSummary) {
        action = 'updating';
        error = '';
        success = '';
        try {
            sessionStorage.setItem(CALENDAR_UPDATE_ACCOUNT_KEY, account.id);
            const result = await startGoogleCalendarOAuth({
                capabilities: ['write'],
                returnPath: '/#settings/privacy/connected-accounts'
            });
            window.location.assign(result.authorization_url);
        } catch (updateError) {
            sessionStorage.removeItem(CALENDAR_UPDATE_ACCOUNT_KEY);
            console.warn('[SettingsConnectedAccounts] Failed to start Calendar account update:', updateError);
            error = $text('settings.privacy.connected_accounts.update_error');
            action = 'idle';
        }
    }

    function getOAuthHandoffId(): string | null {
        if (typeof window === 'undefined') return null;
        return new URLSearchParams(window.location.search).get('oauth_handoff_id');
    }

    function removeOAuthHandoffQueryParam() {
        if (typeof window === 'undefined') return;
        const url = new URL(window.location.href);
        url.searchParams.delete('oauth_handoff_id');
        window.history.replaceState({}, '', url.toString());
    }

    function providerLabel(providerId: string): string {
        if (providerId === 'google_calendar') return $text('settings.privacy.connected_accounts.provider_google_calendar');
        return providerId;
    }

    function appLabel(appId: string): string {
        if (appId === 'calendar') return $text('apps.calendar');
        return appId;
    }

    function capabilityLabels(capabilities: string[]): string {
        if (capabilities.length === 0) return $text('settings.privacy.connected_accounts.none');
        return capabilities.map((capability) => {
            if (capability === 'read') return $text('settings.app_store.connected_accounts.capability_read');
            if (capability === 'write') return $text('settings.app_store.connected_accounts.capability_write');
            if (capability === 'delete') return $text('settings.app_store.connected_accounts.capability_delete');
            return capability;
        }).join(', ');
    }

    function runtimeModeLabels(runtimeModes: Record<string, string>): string {
        const entries = Object.entries(runtimeModes);
        if (entries.length === 0) return $text('settings.privacy.connected_accounts.none');
        return entries.map(([actionName, mode]) => `${actionName}: ${mode.replace(/_/g, ' ')}`).join(', ');
    }

    function needsCalendarWriteAccess(account: ConnectedAccountSummary): boolean {
        return account.app_id === 'calendar' && !account.capabilities.includes('write');
    }
</script>

<div data-testid="privacy-connected-accounts-page">
    <SettingsSectionHeading title={$text('settings.privacy.connected_accounts.title')} icon="privacy" />

    {#if !isAuthenticated}
        <SettingsInfoBox type="warning">
            <p>{$text('settings.privacy.connected_accounts.sign_in_required')}</p>
        </SettingsInfoBox>
    {:else}
        <SettingsInfoBox type="info">
            <p>{$text('settings.privacy.connected_accounts.description')}</p>
        </SettingsInfoBox>

        {#if loading}
            <SettingsInfoBox type="info">
                <p>{$text('settings.privacy.connected_accounts.loading')}</p>
            </SettingsInfoBox>
        {:else if summaries.length === 0}
            <SettingsInfoBox type="info">
                <p>{$text('settings.privacy.connected_accounts.empty')}</p>
            </SettingsInfoBox>
        {:else}
            <SettingsSectionHeading title={$text('settings.privacy.connected_accounts.accounts')} icon="app" />
            {#each summaries as account (account.id)}
                <div data-testid="privacy-connected-account-row">
                    <SettingsItem
                        type="subsubmenu"
                        icon={account.app_id}
                        subtitleTop={providerLabel(account.provider_id)}
                        title={account.label}
                        subtitleBottom={capabilityLabels(account.capabilities)}
                        onClick={() => { selectedAccountId = account.id; }}
                    />
                </div>
            {/each}

            {#if selectedAccount}
                <SettingsSectionHeading title={$text('settings.privacy.connected_accounts.details')} icon={selectedAccount.app_id} />
                <div data-testid="privacy-connected-account-detail">
                    <SettingsCard>
                        <SettingsDetailRow label={$text('settings.privacy.connected_accounts.account_label')} value={selectedAccount.label} />
                        <SettingsDetailRow label={$text('settings.privacy.connected_accounts.provider')} value={providerLabel(selectedAccount.provider_id)} />
                        <SettingsDetailRow label={$text('settings.privacy.connected_accounts.app')} value={appLabel(selectedAccount.app_id)} />
                        <SettingsDetailRow label={$text('settings.privacy.connected_accounts.capabilities')} value={capabilityLabels(selectedAccount.capabilities)} />
                        <SettingsDetailRow label={$text('settings.privacy.connected_accounts.runtime_modes')} value={runtimeModeLabels(selectedAccount.runtime_modes)} />
                    </SettingsCard>
                </div>

                {#if needsCalendarWriteAccess(selectedAccount)}
                    <SettingsButton
                        dataTestid="privacy-connected-account-add-write-button"
                        loading={action === 'updating'}
                        disabled={action !== 'idle'}
                        onClick={() => addCalendarWriteAccess(selectedAccount as ConnectedAccountSummary)}
                    >
                        {$text('settings.privacy.connected_accounts.add_calendar_write')}
                    </SettingsButton>
                {/if}
            {/if}
        {/if}

        {#if action === 'finalizing'}
            <SettingsInfoBox type="info">
                <p>{$text('settings.privacy.connected_accounts.finalizing')}</p>
            </SettingsInfoBox>
        {/if}

        {#if success}
            <SettingsInfoBox type="success">
                <p>{success}</p>
            </SettingsInfoBox>
        {/if}

        {#if error}
            <SettingsInfoBox type="error">
                <p>{error}</p>
            </SettingsInfoBox>
        {/if}
    {/if}
</div>
