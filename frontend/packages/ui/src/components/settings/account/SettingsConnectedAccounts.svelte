<!--
  SettingsConnectedAccounts.svelte

  Central page Settings > Account > Connected accounts: an "Add account" button and one
  entry per non-revoked provider account (icon, email, last used). Tapping an entry opens
  its detail view (ConnectedAccountDetail) with per-app permissions, Reconnect and
  Disconnect. Only browser-decrypted safe summaries are rendered; refresh-token bundles
  are never decrypted here.
-->
<script lang="ts">
    import { onMount, untrack } from 'svelte';
    import { locale as i18nLocale } from 'svelte-i18n';
    import { text } from '@repo/ui';
    import { authStore } from '../../../stores/authStore';
    import { userProfile } from '../../../stores/userProfile';
    import {
        buildConnectedAccountPermissionsPatch,
        listConnectedAccounts,
        summarizeConnectedAccountRows,
        updateConnectedAccount
    } from '../../../services/connectedAccountStorageService';
    import { encryptWithMasterKey } from '../../../services/encryption/MetadataEncryptor';
    import { buildConnectedAccountCliImportCommand } from '../../../services/connectedAccountCliTransfer';
    import { copyToClipboard } from '../../../utils/clipboardUtils';
    import {
        CONNECTED_ACCOUNTS_CHANGED_EVENT,
        beginConnectedAccountOAuth,
        type BeginConnectedAccountOAuthParams,
        type ConnectedAccountsChangedDetail
    } from '../../../services/connectedAccountOAuthService';
    import { consumeConnectedAccountOAuthReturn } from '../../../services/connectedAccountOAuthReturn';
    import {
        buildConnectedAccountEntries,
        formatRelativeTime,
        formatShortDate,
        isLocalConnectorEntry,
        localConnectorStatusLabel,
        localProviderLabel,
        providerLogoUrl,
        type ConnectedAccountEntry
    } from '../connected_accounts/connectedAccountEntries';
    import ConnectedAccountDetail from '../connected_accounts/ConnectedAccountDetail.svelte';
    import {
        SettingsButton,
        SettingsConsentToggle,
        SettingsInfoBox,
        SettingsItem,
        SettingsSectionHeading
    } from '../elements';

    interface Props {
        /** Opens this account's detail view first (component previews). */
        initialAccountId?: string;
    }
    let { initialAccountId = '' }: Props = $props();

    const RETURN_PATH = '/#settings/account/connected-accounts';
    const central = 'settings.app_store.connected_accounts.central';

    let entries = $state<ConnectedAccountEntry[]>([]);
    let selectedAccountId = $state(untrack(() => initialAccountId));
    let loading = $state(false);
    function providerLogo(entry: ConnectedAccountEntry): string {
        return providerLogoUrl(entry.summary.provider_id);
    }

    let action = $state<'idle' | 'adding' | 'exporting' | 'saving' | 'revoking'>('idle');
    let error = $state('');
    let success = $state('');
    let outcome = $state<ConnectedAccountsChangedDetail | null>(null);
    let handledReturn = false;
    let cliExportPasscode = $state('');
    let cliImportCommand = $state('');
    let addOpen = $state(false);
    let googleChoosing = $state(false);
    let googleCalendar = $state(true);
    let googleGmail = $state(false);

    let isAuthenticated = $derived($authStore.isAuthenticated);
    let localeCode = $derived($i18nLocale ?? 'en');
    let selectedEntry = $derived(entries.find((entry) => entry.id === selectedAccountId) ?? null);

    onMount(() => {
        window.addEventListener(CONNECTED_ACCOUNTS_CHANGED_EVENT, onChanged);
        return () => window.removeEventListener(CONNECTED_ACCOUNTS_CHANGED_EVENT, onChanged);
    });

    $effect(() => {
        if (!isAuthenticated || !$userProfile.user_id || handledReturn) return;
        handledReturn = true;
        void consumeConnectedAccountOAuthReturn().then((detail) => {
            if (detail) outcome = detail;
            return loadConnectedAccounts(false);
        });
    });

    $effect(() => {
        if (isAuthenticated) void loadConnectedAccounts(false);
    });

    function onChanged(event: Event) {
        outcome = (event as CustomEvent<ConnectedAccountsChangedDetail>).detail;
        void loadConnectedAccounts(false);
    }

    async function loadConnectedAccounts(clearExistingError = true) {
        loading = true;
        if (clearExistingError) error = '';
        try {
            const rows = await listConnectedAccounts();
            const summaries = await summarizeConnectedAccountRows(rows);
            entries = await buildConnectedAccountEntries(rows, summaries);
        } catch (loadError) {
            console.warn('[SettingsConnectedAccounts] Failed to load connected accounts:', loadError);
            error = $text('settings.privacy.connected_accounts.load_error');
        } finally {
            loading = false;
        }
    }

    function startAddGoogle() {
        if (!googleCalendar && !googleGmail) return;
        error = '';
        // Gmail-only starts the mail consent; Calendar (alone or with Gmail) starts the
        // calendar consent and Gmail is added afterwards from the account's own page.
        const appId = googleCalendar ? 'calendar' : 'mail';
        runOAuth({
            provider: 'google',
            appId,
            capabilities: appId === 'calendar' ? ['read'] : ['read', 'draft'],
            returnPath: RETURN_PATH
        });
    }

    function startAddFigma() {
        error = '';
        runOAuth({ provider: 'figma', appId: 'design', capabilities: ['read'], returnPath: RETURN_PATH });
    }

    function reconnect(entry: ConnectedAccountEntry) {
        error = '';
        const isFigma = entry.summary.provider_id === 'figma';
        runOAuth({
            provider: isFigma ? 'figma' : 'google',
            appId: isFigma ? 'design' : entry.summary.app_id === 'mail' ? 'mail' : 'calendar',
            capabilities: entry.summary.capabilities,
            connectedAccountId: entry.id,
            returnPath: RETURN_PATH
        });
    }

    function addAppToAccount(entry: ConnectedAccountEntry, appId: 'calendar' | 'mail') {
        error = '';
        runOAuth({
            provider: 'google',
            appId,
            capabilities: appId === 'mail' ? ['read', 'draft'] : ['read'],
            connectedAccountId: entry.id,
            returnPath: RETURN_PATH
        });
    }

    /** Called synchronously from a click so the popup is allowed; the list updates via the changed event. */
    function runOAuth(params: BeginConnectedAccountOAuthParams) {
        action = 'adding';
        beginConnectedAccountOAuth(params)
            .catch((startError) => {
                console.warn('[SettingsConnectedAccounts] Failed to start OAuth:', startError);
                error = $text(`${central}.add_error`);
            })
            .finally(() => {
                action = 'idle';
            });
    }

    async function toggleAppActions(entry: ConnectedAccountEntry, appId: string, actions: string[], enabled: boolean) {
        action = 'saving';
        error = '';
        success = '';
        try {
            const current = new Set(entry.apps[appId] ?? []);
            for (const grant of actions) {
                if (enabled) current.add(grant);
                else current.delete(grant);
            }
            const patch = await buildConnectedAccountPermissionsPatch(entry.row, appId, [...current], encryptWithMasterKey);
            await updateConnectedAccount({ accountId: entry.id, patch });
            await loadConnectedAccounts(false);
        } catch (saveError) {
            console.warn('[SettingsConnectedAccounts] Failed to save permission change:', saveError);
            error = $text(`${central}.permission_save_error`);
        } finally {
            action = 'idle';
        }
    }

    async function disconnect(entry: ConnectedAccountEntry) {
        action = 'revoking';
        error = '';
        success = '';
        try {
            await updateConnectedAccount({
                accountId: entry.id,
                patch: isLocalConnectorEntry(entry)
                    ? { connector_status: 'revoked' }
                    : { connector_status: 'revoked', server_access_enabled: false }
            });
            selectedAccountId = '';
            success = isLocalConnectorEntry(entry)
                ? $text('settings.privacy.connected_accounts.revoked_success')
                : $text(`${central}.disconnected`);
            await loadConnectedAccounts(false);
        } catch (revokeError) {
            console.warn('[SettingsConnectedAccounts] Failed to disconnect account:', revokeError);
            error = $text('settings.privacy.connected_accounts.revoke_error');
        } finally {
            action = 'idle';
        }
    }

    async function generateCliImportCommand(entry: ConnectedAccountEntry) {
        if (!cliExportPasscode.trim()) {
            error = $text('settings.privacy.connected_accounts.cli_export_passcode_required');
            return;
        }
        action = 'exporting';
        error = '';
        success = '';
        cliImportCommand = '';
        try {
            const command = await buildConnectedAccountCliImportCommand({ row: entry.row, passcode: cliExportPasscode });
            cliImportCommand = command;
            const copied = await copyToClipboard(command);
            success = copied.success
                ? $text('settings.privacy.connected_accounts.cli_export_copied')
                : $text('settings.privacy.connected_accounts.cli_export_generated');
        } catch (exportError) {
            console.warn('[SettingsConnectedAccounts] Failed to generate connected-account CLI import command:', exportError);
            error = $text('settings.privacy.connected_accounts.cli_export_error');
        } finally {
            action = 'idle';
        }
    }

    function openEntry(entry: ConnectedAccountEntry) {
        selectedAccountId = entry.id;
        cliImportCommand = '';
        cliExportPasscode = '';
        success = '';
        error = '';
    }

    function entryTitle(entry: ConnectedAccountEntry): string {
        if (entry.email) return entry.email;
        const date = entry.createdAt ? formatShortDate(entry.createdAt, localeCode) : '-';
        return $text(`${central}.email_not_saved`, { values: { date } });
    }

    function entrySubtitle(entry: ConnectedAccountEntry): string {
        if (isLocalConnectorEntry(entry)) {
            return `${localProviderLabel(entry.summary.provider_id, $text)} - ${localConnectorStatusLabel(entry, $text)}`;
        }
        const used = entry.lastUsedAt
            ? $text(`${central}.last_used`, { values: { time: formatRelativeTime(entry.lastUsedAt, localeCode) } })
            : $text(`${central}.never_used`);
        return entry.reconnectRequired ? `${used} · ${$text(`${central}.needs_reconnect`)}` : used;
    }
</script>

<div data-testid="privacy-connected-accounts-page">
    {#if !isAuthenticated}
        <SettingsInfoBox type="warning">
            <p>{$text('settings.privacy.connected_accounts.sign_in_required')}</p>
        </SettingsInfoBox>
    {:else if selectedEntry}
        <ConnectedAccountDetail
            entry={selectedEntry}
            locale={localeCode}
            busy={action !== 'idle'}
            exporting={action === 'exporting'}
            {cliImportCommand}
            {cliExportPasscode}
            onBack={() => (selectedAccountId = '')}
            onToggle={(appId, actions, enabled) => toggleAppActions(selectedEntry as ConnectedAccountEntry, appId, actions, enabled)}
            onAddApp={(appId) => addAppToAccount(selectedEntry as ConnectedAccountEntry, appId)}
            onReconnect={() => reconnect(selectedEntry as ConnectedAccountEntry)}
            onDisconnect={() => disconnect(selectedEntry as ConnectedAccountEntry)}
            onExport={() => generateCliImportCommand(selectedEntry as ConnectedAccountEntry)}
            onPasscodeChange={(value) => (cliExportPasscode = value)}
        />
    {:else}
        <SettingsSectionHeading title={$text('settings.app_store.connected_accounts.title')} icon="privacy" />
        <SettingsButton
            dataTestid="connected-accounts-add-button"
            fullWidth={true}
            disabled={action !== 'idle'}
            onClick={() => (addOpen = !addOpen)}
        >
            {$text(`${central}.add_account`)}
        </SettingsButton>

        {#if addOpen}
            <div data-testid="connected-accounts-add-providers">
                <SettingsItem
                    type="submenu"
                    icon="calendar"
                    title={$text(`${central}.provider_google`)}
                    data-testid="connected-accounts-add-google"
                    onClick={() => (googleChoosing = !googleChoosing)}
                />
                {#if googleChoosing}
                    <SettingsInfoBox type="info"><p>{$text(`${central}.google_access_hint`)}</p></SettingsInfoBox>
                    <SettingsConsentToggle
                        checked={googleCalendar}
                        consentText={$text(`${central}.access_calendar`)}
                        highlightedParts={[]}
                        ariaLabel={$text(`${central}.access_calendar`)}
                        dataTestid="connected-accounts-add-toggle-calendar"
                        onChange={(checked) => (googleCalendar = checked)}
                    />
                    <SettingsConsentToggle
                        checked={googleGmail}
                        consentText={$text(`${central}.access_gmail`)}
                        highlightedParts={[]}
                        ariaLabel={$text(`${central}.access_gmail`)}
                        dataTestid="connected-accounts-add-toggle-gmail"
                        onChange={(checked) => (googleGmail = checked)}
                    />
                    <SettingsButton
                        dataTestid="connected-accounts-add-google-continue"
                        fullWidth={true}
                        loading={action === 'adding'}
                        disabled={action !== 'idle' || (!googleCalendar && !googleGmail)}
                        onClick={startAddGoogle}
                    >
                        {$text(`${central}.continue_to_provider`, { values: { provider: $text(`${central}.provider_google`) } })}
                    </SettingsButton>
                {/if}
                <SettingsItem
                    type="submenu"
                    icon="design"
                    title={$text(`${central}.provider_figma`)}
                    data-testid="connected-accounts-add-figma"
                    onClick={startAddFigma}
                />
            </div>
        {/if}

        {#if loading}
            <SettingsInfoBox type="info">
                <p>{$text('settings.privacy.connected_accounts.loading')}</p>
            </SettingsInfoBox>
        {:else if entries.length === 0}
            <div data-testid="connected-accounts-empty">
                <SettingsInfoBox type="info">
                    <p>{$text(`${central}.empty`)}</p>
                </SettingsInfoBox>
            </div>
        {:else}
            {#each entries as entry (entry.id)}
                <div data-testid={`connected-account-entry-${entry.id}`} data-provider={entry.summary.provider_id}>
                    <SettingsItem
                        type="subsubmenu"
                        icon={providerLogo(entry) ? '' : 'account'}
                        iconSrc={providerLogo(entry)}
                        iconAlt={entry.summary.provider_id}
                        title={entryTitle(entry)}
                        subtitleTop={entrySubtitle(entry)}
                        data-testid="connected-account-entry"
                        onClick={() => openEntry(entry)}
                    />
                </div>
            {/each}
        {/if}
    {/if}

    {#if outcome?.status === 'success'}
        <div data-testid="connected-account-oauth-success">
            <SettingsInfoBox type="success">
                <p>{$text('settings.app_store.connected_accounts.oauth.connected_success')}</p>
            </SettingsInfoBox>
        </div>
    {:else if outcome?.status === 'error'}
        <div data-testid="connected-account-oauth-error">
            <SettingsInfoBox type="error">
                <p>{outcome.reason === 'finalize_failed'
                    ? $text('settings.app_store.connected_accounts.oauth.error_finalize')
                    : $text('settings.app_store.connected_accounts.oauth.error_provider')}</p>
            </SettingsInfoBox>
        </div>
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
</div>
