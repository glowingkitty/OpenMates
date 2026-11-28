<!--
  AppConnectedAccountsSection.svelte

  Compact "Connected accounts" block on the Calendar, Mail and Design app pages:
  lists the connected accounts this app may use and links to the central
  Settings > Account > Connected accounts page, where accounts are added,
  reconnected and disconnected. Also finishes a same-tab OAuth return (blocked
  popup) and refreshes when the popup flow announces a change.
-->
<script lang="ts">
    import { appIconClass, providerLogoUrl } from './connectedAccountEntries';
    import { onMount, createEventDispatcher } from 'svelte';
    import { text } from '@repo/ui';
    import { authStore } from '../../../stores/authStore';
    import { userProfile } from '../../../stores/userProfile';
    import {
        listConnectedAccounts,
        summarizeConnectedAccountRows,
        type ConnectedAccountSummary
    } from '../../../services/connectedAccountStorageService';
    import {
        CONNECTED_ACCOUNTS_CHANGED_EVENT,
        type ConnectedAccountsChangedDetail
    } from '../../../services/connectedAccountOAuthService';
    import { consumeConnectedAccountOAuthReturn } from '../../../services/connectedAccountOAuthReturn';
    import { SettingsInfoBox, SettingsItem, SettingsSectionHeading } from '../elements';
    import { isLegacyGoogleLabel } from './googleAccountLabel';

    interface Props {
        appId: 'calendar' | 'mail' | 'design';
    }

    let { appId }: Props = $props();

    const T = 'settings.app_store.connected_accounts';
    const CENTRAL_PATH = 'account/connected-accounts';
    const dispatch = createEventDispatcher();
    const PROVIDER_FOR_APP: Record<Props['appId'], string> = {
        calendar: 'google_calendar',
        mail: 'google_calendar',
        design: 'figma'
    };

    let accounts = $state<ConnectedAccountSummary[]>([]);
    let loadFailed = $state(false);
    let outcome = $state<ConnectedAccountsChangedDetail | null>(null);
    let handledReturn = false;

    let isAuthenticated = $derived($authStore.isAuthenticated);

    function mayUse(account: ConnectedAccountSummary): boolean {
        const appIds = (account as ConnectedAccountSummary & { app_ids?: string[] }).app_ids;
        const usesApp = appIds ? appIds.includes(appId) : account.app_id === appId;
        return account.provider_id === PROVIDER_FOR_APP[appId] && usesApp && account.connector_status !== 'revoked';
    }

    function accountTitle(account: ConnectedAccountSummary): string {
        return isLegacyGoogleLabel(account.label) && account.provider_id === 'google_calendar'
            ? $text(`${T}.app_page.email_not_saved`)
            : account.label;
    }

    function accountStatus(account: ConnectedAccountSummary): string {
        return account.connector_status === 'reconnect_required'
            ? $text(`${T}.app_page.status_reconnect`)
            : $text(`${T}.app_page.status_connected`);
    }

    async function loadAccounts() {
        try {
            const summaries = await summarizeConnectedAccountRows(await listConnectedAccounts());
            accounts = summaries.filter(mayUse);
            loadFailed = false;
        } catch (loadError) {
            console.warn('[AppConnectedAccountsSection] Failed to load connected accounts:', loadError);
            loadFailed = true;
        }
    }

    function onChanged(event: Event) {
        outcome = (event as CustomEvent<ConnectedAccountsChangedDetail>).detail;
        void loadAccounts();
    }

    function openCentralPage() {
        dispatch('openSettings', {
            settingsPath: CENTRAL_PATH,
            direction: 'forward',
            icon: 'privacy',
            title: $text('settings.privacy.connected_accounts.title')
        });
    }

    onMount(() => {
        window.addEventListener(CONNECTED_ACCOUNTS_CHANGED_EVENT, onChanged);
        return () => window.removeEventListener(CONNECTED_ACCOUNTS_CHANGED_EVENT, onChanged);
    });

    $effect(() => {
        if (!isAuthenticated || !$userProfile.user_id || handledReturn) return;
        handledReturn = true;
        void consumeConnectedAccountOAuthReturn().then((detail) => {
            if (detail) outcome = detail;
            return loadAccounts();
        });
    });

    $effect(() => {
        if (isAuthenticated) void loadAccounts();
    });
</script>

<div
    class="section"
    data-testid={appId === 'design' ? 'figma-connected-accounts-section' : `${appId}-connected-accounts-section`}
>
    <SettingsSectionHeading title={$text(`${T}.app_page.title`)} icon={appIconClass(appId)} />

    {#if loadFailed}
        <SettingsInfoBox type="error"><p>{$text(`${T}.load_error`)}</p></SettingsInfoBox>
    {:else if accounts.length === 0}
        <div data-testid="app-connected-accounts-empty">
            <SettingsInfoBox type="info"><p>{$text(`${T}.app_page.none`)}</p></SettingsInfoBox>
        </div>
    {:else}
        {#each accounts as account (account.id)}
            <SettingsItem
                type="subsubmenu"
                icon={providerLogoUrl(account.provider_id) ? '' : appIconClass(appId)}
                iconSrc={providerLogoUrl(account.provider_id)}
                iconAlt={account.provider_id}
                title={accountTitle(account)}
                subtitleTop={accountStatus(account)}
                data-testid="app-connected-account-item"
                onClick={openCentralPage}
            />
        {/each}
    {/if}

    <SettingsItem
        type="submenu"
        icon="privacy"
        title={accounts.length === 0 && !loadFailed ? $text(`${T}.app_page.add_link`) : $text(`${T}.app_page.manage_link`)}
        data-testid="app-connected-accounts-manage-link"
        onClick={openCentralPage}
    />

    {#if outcome?.status === 'success'}
        <SettingsInfoBox type="success"><p data-testid="connected-account-oauth-success">{$text(`${T}.oauth.connected_success`)}</p></SettingsInfoBox>
    {:else if outcome?.status === 'error'}
        <SettingsInfoBox type="error">
            <p data-testid="connected-account-oauth-error">
                {outcome.reason === 'provider_error' ? $text(`${T}.oauth.error_provider`) : $text(`${T}.oauth.error_finalize`)}
            </p>
        </SettingsInfoBox>
    {/if}
</div>
