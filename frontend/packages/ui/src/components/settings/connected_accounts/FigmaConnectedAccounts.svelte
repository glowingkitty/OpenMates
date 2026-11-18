<!--
  FigmaConnectedAccounts.svelte

  Connected-accounts section of the Design app settings: starts the Figma
  OAuth flow (read-only, optional Variables capability for Figma Enterprise),
  finalizes the OAuth handoff on return, and lists/disconnects Figma accounts.
  Mirrors the Calendar section in AppDetails.svelte. Spec:
  specifications/features/app-skills/design-figma/specification.yml
  (design-figma.connection.oauth, design-figma.connection.minimal-scopes).
-->
<script lang="ts">
    import { onMount } from 'svelte';
    import { text } from '@repo/ui';
    import { userProfile } from '../../../stores/userProfile';
    import { computeSHA256 } from '../../../message_parsing/utils';
    import {
        listConnectedAccounts,
        summarizeConnectedAccountRows,
        updateConnectedAccount,
        type ConnectedAccountSummary
    } from '../../../services/connectedAccountStorageService';
    import {
        finalizeOAuthHandoffAsConnectedAccount,
        startFigmaOAuth
    } from '../../../services/connectedAccountOAuthService';
    import { SettingsButton, SettingsCard, SettingsConsentToggle, SettingsInfoBox, SettingsSectionHeading } from '../elements';

    interface Props {
        /** Preview/test injection: render these accounts instead of loading them. */
        previewAccounts?: ConnectedAccountSummary[];
        /** Preview/test injection: render the not-configured state. */
        previewNotConfigured?: boolean;
    }

    let { previewAccounts, previewNotConfigured = false }: Props = $props();

    const FIGMA_PROVIDER = 'figma';
    const RETURN_PATH = '/#settings/apps/design';

    let accounts = $state<ConnectedAccountSummary[]>([]);
    let loading = $state(false);
    let variablesEnabled = $state(false);
    let action = $state<'idle' | 'connecting' | 'finalizing' | 'disconnecting'>('idle');
    let notConfigured = $state(false);
    let error = $state('');
    let success = $state('');
    let finalizedHandoffId = '';

    let capabilities = $derived(variablesEnabled ? ['read', 'variables'] : ['read']);
    let shownAccounts = $derived(previewAccounts ?? accounts);
    let showNotConfigured = $derived(notConfigured || previewNotConfigured);

    onMount(() => {
        if (previewAccounts) return;
        void initialize();
    });

    $effect(() => {
        if (previewAccounts) return;
        const handoffId = getHandoffId();
        if (!handoffId || !$userProfile.user_id || finalizedHandoffId === handoffId || action === 'finalizing') return;
        void initialize();
    });

    async function initialize() {
        await finalizeHandoffFromUrl();
        await loadAccounts();
    }

    async function loadAccounts() {
        loading = true;
        try {
            const providerHash = await computeSHA256(FIGMA_PROVIDER);
            const rows = (await listConnectedAccounts()).filter(
                (row) => row.provider_type_hash === providerHash && row.connector_status !== 'revoked'
            );
            accounts = await summarizeConnectedAccountRows(rows);
        } catch (loadError) {
            console.warn('[FigmaConnectedAccounts] Failed to load Figma accounts:', loadError);
            error = $text('settings.app_store.connected_accounts.load_error');
        } finally {
            loading = false;
        }
    }

    function getHandoffId(): string | null {
        if (typeof window === 'undefined') return null;
        return new URLSearchParams(window.location.search).get('oauth_handoff_id');
    }

    function removeHandoffQueryParam() {
        const url = new URL(window.location.href);
        url.searchParams.delete('oauth_handoff_id');
        window.history.replaceState({}, '', url.toString());
    }

    async function finalizeHandoffFromUrl() {
        const handoffId = getHandoffId();
        const userId = $userProfile.user_id;
        if (!handoffId || !userId || finalizedHandoffId === handoffId) return;
        finalizedHandoffId = handoffId;
        action = 'finalizing';
        error = '';
        try {
            await finalizeOAuthHandoffAsConnectedAccount({ userId, handoffId });
            success = $text('settings.app_store.connected_accounts.connected_success');
            removeHandoffQueryParam();
        } catch (finalizeError) {
            console.warn('[FigmaConnectedAccounts] Failed to finalize Figma OAuth handoff:', finalizeError);
            error = $text('settings.app_store.connected_accounts.finalize_error');
        } finally {
            action = 'idle';
        }
    }

    async function connect() {
        action = 'connecting';
        error = '';
        success = '';
        notConfigured = false;
        try {
            const result = await startFigmaOAuth({ capabilities, returnPath: RETURN_PATH });
            window.location.assign(result.authorization_url);
        } catch (startError) {
            console.warn('[FigmaConnectedAccounts] Failed to start Figma OAuth:', startError);
            action = 'idle';
            if (startError instanceof Error && startError.message.includes('HTTP 503')) {
                notConfigured = true;
            } else {
                error = $text('settings.app_store.connected_accounts.figma.start_error');
            }
        }
    }

    async function disconnect(account: ConnectedAccountSummary) {
        action = 'disconnecting';
        error = '';
        success = '';
        try {
            await updateConnectedAccount({
                accountId: account.id,
                patch: { connector_status: 'revoked', server_access_enabled: false }
            });
            success = $text('settings.app_store.connected_accounts.figma.disconnected_success');
            await loadAccounts();
        } catch (disconnectError) {
            console.warn('[FigmaConnectedAccounts] Failed to disconnect Figma account:', disconnectError);
            error = $text('settings.app_store.connected_accounts.figma.disconnect_error');
        } finally {
            action = 'idle';
        }
    }
</script>

<div class="section" data-testid="figma-connected-accounts-section">
    <SettingsSectionHeading title={$text('settings.app_store.connected_accounts.figma.title')} icon="design" />
    <p class="section-description">{$text('settings.app_store.connected_accounts.figma.description')}</p>

    <SettingsCard>
        <SettingsConsentToggle
            checked={variablesEnabled}
            consentText={$text('settings.app_store.connected_accounts.figma.variables_label')}
            ariaLabel={$text('settings.app_store.connected_accounts.figma.variables_label')}
            dataTestid="figma-variables-toggle"
            onChange={(checked) => (variablesEnabled = checked)}
        />
        <SettingsButton
            dataTestid="figma-connect-button"
            fullWidth={true}
            loading={action === 'connecting'}
            disabled={action !== 'idle' || showNotConfigured}
            onClick={connect}
        >
            {$text('settings.app_store.connected_accounts.figma.connect_button')}
        </SettingsButton>
    </SettingsCard>

    {#if showNotConfigured}
        <div data-testid="figma-not-configured">
            <SettingsInfoBox type="warning">
                <p>{$text('settings.app_store.connected_accounts.figma.not_configured')}</p>
            </SettingsInfoBox>
        </div>
    {/if}

    {#if shownAccounts.length > 0}
        <SettingsSectionHeading title={$text('settings.app_store.connected_accounts.figma.accounts_heading')} icon="design" />
        {#each shownAccounts as account (account.id)}
            <div data-testid="figma-account-row">
                <SettingsCard>
                    <p class="account-label">{account.label}</p>
                    <SettingsButton
                        variant="secondary"
                        fullWidth={true}
                        dataTestid="figma-reconnect-button"
                        disabled={action !== 'idle'}
                        onClick={connect}
                    >
                        {$text('settings.app_store.connected_accounts.figma.reconnect_button')}
                    </SettingsButton>
                    <SettingsButton
                        variant="danger"
                        fullWidth={true}
                        dataTestid="figma-disconnect-button"
                        loading={action === 'disconnecting'}
                        disabled={action !== 'idle'}
                        onClick={() => disconnect(account)}
                    >
                        {$text('settings.app_store.connected_accounts.figma.disconnect_button')}
                    </SettingsButton>
                    <SettingsInfoBox type="info">
                        <p>{$text('settings.app_store.connected_accounts.figma.revoke_note')}</p>
                    </SettingsInfoBox>
                </SettingsCard>
            </div>
        {/each}
    {/if}

    {#if loading}
        <SettingsInfoBox type="info"><p>{$text('settings.app_store.connected_accounts.loading')}</p></SettingsInfoBox>
    {/if}
    {#if action === 'finalizing'}
        <SettingsInfoBox type="info"><p>{$text('settings.app_store.connected_accounts.finalizing')}</p></SettingsInfoBox>
    {/if}
    {#if success}
        <SettingsInfoBox type="success"><p>{success}</p></SettingsInfoBox>
    {/if}
    {#if error}
        <SettingsInfoBox type="warning"><p>{error}</p></SettingsInfoBox>
    {/if}
</div>

<style>
    .section-description,
    .account-label {
        margin: 0 0 var(--spacing-4, 12px);
        color: var(--color-font-secondary);
    }
</style>
