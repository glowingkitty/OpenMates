<!--
  ConnectedAccountDetail.svelte

  Sub-page of the central Connected accounts page for one provider account: header with
  email, per-app permission toggles, last used / connected on, Reconnect, Disconnect with
  inline confirm, and the CLI export block. Presentation plus callbacks: the parent owns
  storage, OAuth and revoke calls.
-->
<script lang="ts">
    import { untrack } from "svelte";
    import { text } from '@repo/ui';
    import {
        SettingsButton,
        SettingsCard,
        SettingsConsentToggle,
        SettingsDetailRow,
        SettingsInfoBox,
        SettingsInput,
        SettingsSectionHeading,
        SettingsTextarea
    } from '../elements';
    import {
        APP_PERMISSION_TOGGLES,
        formatRelativeTime,
        formatShortDate,
        isLocalConnectorEntry,
        localCapabilityLabels,
        localConnectorStatusLabel,
        localProviderLabel,
        type ConnectedAccountEntry, appIconClass, providerLogoUrl } from './connectedAccountEntries';

    interface Props {
        entry: ConnectedAccountEntry;
        locale: string;
        busy: boolean;
        exporting: boolean;
        cliImportCommand: string;
        cliExportPasscode: string;
        onBack: () => void;
        onToggle: (appId: string, actions: string[], enabled: boolean) => void;
        onAddApp: (appId: 'calendar' | 'mail') => void;
        onReconnect: () => void;
        onDisconnect: () => void;
        onExport: () => void;
        onPasscodeChange: (value: string) => void;
    }

    let {
        entry, locale, busy, exporting, cliImportCommand, cliExportPasscode,
        onBack, onToggle, onAddApp, onReconnect, onDisconnect, onExport, onPasscodeChange
    }: Props = $props();

    let confirmingDisconnect = $state(false);
    let passcode = $state(untrack(() => cliExportPasscode));

    const central = 'settings.app_store.connected_accounts.central';
    let appIds = $derived(Object.keys(entry.apps).sort());
    let headerIcon = $derived(appIconClass(entry.summary.app_id));
    // The account belongs to a provider, so its logo heads the page (the app icon only when none is bundled).
    let headerLogo = $derived(providerLogoUrl(entry.summary.provider_id));
    let title = $derived(
        entry.email ?? $text('settings.app_store.connected_accounts.card.google_account')
    );

    function appLabel(appId: string): string {
        if (appId === 'calendar') return $text('apps.calendar');
        if (appId === 'mail') return $text('apps.mail');
        if (appId === 'design') return $text('settings.privacy.connected_accounts.app_design');
        return appId;
    }

    function isEnabled(appId: string, actions: string[]): boolean {
        return actions.every((action) => entry.apps[appId]?.includes(action));
    }
</script>

<div data-testid="connected-account-detail" data-account-id={entry.id}>
    <SettingsButton variant="ghost" dataTestid="connected-account-detail-back" onClick={onBack}>
        {$text(`${central}.back_to_list`)}
    </SettingsButton>
    <SettingsSectionHeading title={title} icon={headerIcon} iconSrc={headerLogo} iconAlt={$text('settings.app_store.connected_accounts.card.google_account')} />

    <div data-testid="privacy-connected-account-detail">
        <SettingsCard>
            <SettingsDetailRow
                label={$text('settings.privacy.connected_accounts.account_label')}
                value={entry.email ?? $text(`${central}.email_not_saved`, { values: { date: entry.createdAt ? formatShortDate(entry.createdAt, locale) : '-' } })}
            />
            <div data-testid="connected-account-detail-last-used">
                <SettingsDetailRow
                    label={$text(`${central}.last_used_label`)}
                    value={entry.lastUsedAt ? formatRelativeTime(entry.lastUsedAt, locale) : $text(`${central}.never_used`)}
                />
            </div>
            <div data-testid="connected-account-detail-connected-on">
                <SettingsDetailRow
                    label={$text(`${central}.connected_on_label`)}
                    value={entry.createdAt ? formatShortDate(entry.createdAt, locale) : '-'}
                />
            </div>
            {#if isLocalConnectorEntry(entry)}
                <SettingsDetailRow
                    label={$text('settings.privacy.connected_accounts.provider')}
                    value={localProviderLabel(entry.summary.provider_id, $text)}
                />
                <SettingsDetailRow
                    label={$text('settings.privacy.connected_accounts.status')}
                    value={localConnectorStatusLabel(entry, $text)}
                />
                <SettingsDetailRow
                    label={$text('settings.privacy.connected_accounts.capabilities')}
                    value={localCapabilityLabels(entry.summary.capabilities, $text)}
                />
            {/if}
            {#if entry.reconnectRequired}
                <SettingsDetailRow
                    label={$text('settings.privacy.connected_accounts.status')}
                    value={$text(`${central}.needs_reconnect`)}
                />
            {/if}
        </SettingsCard>
    </div>

    {#each appIds as appId (appId)}
        <div data-testid={`connected-account-app-permissions-${appId}`}>
            <SettingsSectionHeading
                title={$text(`${central}.permissions_for_app`, { values: { app: appLabel(appId) } })}
                icon={appIconClass(appId)}
            />
            {#each APP_PERMISSION_TOGGLES[appId] ?? [] as toggle (toggle.id)}
                <SettingsConsentToggle
                    checked={isEnabled(appId, toggle.actions)}
                    consentText={$text(toggle.labelKey)}
                    highlightedParts={[]}
                    ariaLabel={`${appLabel(appId)}: ${$text(toggle.labelKey)}`}
                    disabled={busy}
                    dataTestid={`connected-account-permission-${appId}-${toggle.id}`}
                    onChange={(enabled) => onToggle(appId, toggle.actions, enabled)}
                />
            {/each}
        </div>
    {/each}

    {#if entry.summary.provider_id === 'google_calendar'}
        {#each ['calendar', 'mail'] as const as missingApp (missingApp)}
            {#if !entry.apps[missingApp]}
                <SettingsButton variant="secondary" fullWidth={true} dataTestid={`connected-account-add-app-${missingApp}`} disabled={busy} onClick={() => onAddApp(missingApp)}>
                    {$text(`${central}.${missingApp === 'mail' ? 'add_gmail_access' : 'add_calendar_access'}`)}
                </SettingsButton>
            {/if}
        {/each}
    {/if}

    {#if confirmingDisconnect}
        <div data-testid="connected-account-disconnect-confirm">
            <SettingsInfoBox type="warning">
                <p>{$text('settings.app_store.connected_accounts.card.disconnect_confirm', { values: { provider: title } })}</p>
            </SettingsInfoBox>
            <SettingsButton variant="danger" fullWidth={true} dataTestid="connected-account-disconnect-confirm-button" disabled={busy} onClick={() => { confirmingDisconnect = false; onDisconnect(); }}>
                {$text('settings.app_store.connected_accounts.card.disconnect_confirm_button')}
            </SettingsButton>
            <SettingsButton variant="ghost" fullWidth={true} dataTestid="connected-account-disconnect-cancel" onClick={() => (confirmingDisconnect = false)}>
                {$text('settings.app_store.connected_accounts.card.cancel')}
            </SettingsButton>
        </div>
    {:else}
        <SettingsButton variant="secondary" fullWidth={true} dataTestid="connected-account-reconnect" disabled={busy} onClick={onReconnect}>
            {$text('settings.app_store.connected_accounts.card.reconnect')}
        </SettingsButton>
        <SettingsButton variant="danger" fullWidth={true} dataTestid="connected-account-disconnect" disabled={busy} onClick={() => (confirmingDisconnect = true)}>
            {$text('settings.app_store.connected_accounts.card.disconnect')}
        </SettingsButton>
    {/if}

    <SettingsSectionHeading title={$text('settings.privacy.connected_accounts.cli_export_title')} icon="app" />
    <SettingsInfoBox type="warning">
        <p>{$text('settings.privacy.connected_accounts.cli_export_warning')}</p>
    </SettingsInfoBox>
    <SettingsInput
        bind:value={passcode}
        type="password"
        placeholder={$text('settings.privacy.connected_accounts.cli_export_passcode_placeholder')}
        dataTestid="privacy-connected-account-cli-export-passcode"
        disabled={busy}
        onInput={onPasscodeChange}
    />
    <SettingsButton dataTestid="privacy-connected-account-cli-export-button" variant="secondary" loading={exporting} disabled={busy} onClick={onExport}>
        {$text('settings.privacy.connected_accounts.cli_export_button')}
    </SettingsButton>
    {#if cliImportCommand}
        <SettingsTextarea
            value={cliImportCommand}
            rows={4}
            dataTestid="privacy-connected-account-cli-import-command"
            ariaLabel={$text('settings.privacy.connected_accounts.cli_export_command_label')}
        />
    {/if}
</div>
