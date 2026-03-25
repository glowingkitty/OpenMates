<!--
Hide Personal Data Settings - Sub-page for managing PII detection and custom personal data entries.

Users can:
- Toggle the master PII detection on/off
- Manage contacts (names, addresses, birthdays) in a unified section
  - Clicking a contact entry verifies identity (passkey / 2FA), then opens it in edit mode
  - Identity verification is remembered for 2 minutes so consecutive edits don't re-prompt
- Toggle individual auto-detection categories (email, phone, credit card, etc.)
- Add custom entries for any text they want to hide
  - Clicking a custom entry verifies identity then opens it in edit mode

All user-defined entries (names, addresses, birthdays, custom values) are
client-side encrypted — the server never sees the actual data.

Architecture context: docs/architecture/pii-protection.md, docs/architecture/security.md
Based on Figma design: settings/privacy/hide_personal_data (node 4660:42313)
-->

<script lang="ts">
    import { createEventDispatcher, onMount } from 'svelte';
    import { text } from '@repo/ui';
    import { getApiEndpoint, apiEndpoints } from '../../../config/api';
    import SettingsItem from '../../SettingsItem.svelte';
    import SecurityAuth from '../security/SecurityAuth.svelte';
    import { personalDataStore, type PersonalDataEntry } from '../../../stores/personalDataStore';
    import { isSensitiveAuthValid, recordSensitiveAuthSuccess } from '../../../stores/sensitiveAuthStore';

    const dispatch = createEventDispatcher();

    // ─── Load from encrypted storage on mount ────────────────────────────────

    onMount(() => {
        personalDataStore.loadFromStorage();
        fetchAuthMethods();
    });

    // ─── Auth Methods (for SecurityAuth component) ───────────────────────────

    let hasPasskey = $state(false);
    let hasPassword = $state(false);
    let has2FA = $state(false);

    async function fetchAuthMethods() {
        try {
            const response = await fetch(getApiEndpoint(apiEndpoints.payments.getUserAuthMethods), {
                method: 'GET',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include'
            });
            if (response.ok) {
                const data = await response.json();
                hasPasskey = data.has_passkey || false;
                hasPassword = data.has_password || false;
                has2FA = data.has_2fa || false;
            }
        } catch (error) {
            console.error('[SettingsHidePersonalData] Failed to fetch auth methods:', error);
        }
    }

    // ─── Auth Modal State ────────────────────────────────────────────────────

    /** Whether the SecurityAuth modal is visible */
    let showAuthModal = $state(false);

    /** Entry pending navigation after successful auth */
    let pendingEditEntry = $state<PersonalDataEntry | null>(null);

    function handleAuthSuccess() {
        recordSensitiveAuthSuccess();
        showAuthModal = false;

        if (pendingEditEntry) {
            navigateToEditEntry(pendingEditEntry);
            pendingEditEntry = null;
        }
    }

    function handleAuthFailed(message: string) {
        console.error('[SettingsHidePersonalData] Auth failed:', message);
        showAuthModal = false;
        pendingEditEntry = null;
    }

    function handleAuthCancel() {
        showAuthModal = false;
        pendingEditEntry = null;
    }

    // ─── Store Subscriptions ─────────────────────────────────────────────────

    let piiSettings = $state({ masterEnabled: true, categories: {} as Record<string, boolean> });
    personalDataStore.settings.subscribe((s) => { piiSettings = s; });

    let allEntries: PersonalDataEntry[] = $state([]);
    personalDataStore.subscribe((entries) => { allEntries = entries; });

    // ─── Derived Entry Lists ─────────────────────────────────────────────────
    // All contact-type entries (names, addresses, birthdays) in a unified "Contacts" section
    let contactEntries = $derived(allEntries.filter(e => e.type === 'name' || e.type === 'address' || e.type === 'birthday'));
    let customEntries = $derived(allEntries.filter(e => e.type === 'custom'));

    // ─── Master Toggle ───────────────────────────────────────────────────────

    let masterEnabled = $derived(piiSettings.masterEnabled);

    function handleMasterToggle() {
        personalDataStore.toggleMaster();
    }

    // ─── Category Toggles ────────────────────────────────────────────────────

    function isCategoryOn(category: string): boolean {
        return piiSettings.categories[category] ?? true;
    }

    function handleCategoryToggle(category: string) {
        personalDataStore.toggleCategory(category);
    }

    // ─── Icon Helpers ─────────────────────────────────────────────────────────

    /** Get the appropriate icon for a contact entry based on its type */
    function getContactEntryIcon(entry: PersonalDataEntry): string {
        switch (entry.type) {
            case 'name': return 'user';
            case 'address': return 'maps';
            case 'birthday': return 'gift';
            default: return 'contact';
        }
    }

    function getEditSegmentForEntry(entry: PersonalDataEntry): string {
        switch (entry.type) {
            case 'name': return 'edit-name';
            case 'address': return 'edit-address';
            case 'birthday': return 'edit-birthday';
            case 'custom': return 'edit-custom';
            default: return 'edit-name';
        }
    }

    // ─── Entry Click → Auth Gate → Edit ─────────────────────────────────────

    /**
     * Clicking a contact or custom entry opens it in edit mode.
     * If the user verified their identity within the last 2 minutes, skip auth.
     * Otherwise, show SecurityAuth — on success, navigate to the edit page.
     */
    function handleEntryClick(entry: PersonalDataEntry) {
        if (isSensitiveAuthValid()) {
            // Grace period still valid — navigate directly without re-auth
            navigateToEditEntry(entry);
        } else {
            // Need fresh verification
            pendingEditEntry = entry;
            showAuthModal = true;
        }
    }

    function navigateToEditEntry(entry: PersonalDataEntry) {
        const editSegment = getEditSegmentForEntry(entry);
        dispatch('openSettings', {
            settingsPath: `privacy/hide-personal-data/${editSegment}/${entry.id}`,
            direction: 'forward',
            icon: getContactEntryIcon(entry),
            title: entry.title
        });
    }

    // ─── Navigation ──────────────────────────────────────────────────────────

    function navigateToAddName() {
        dispatch('openSettings', {
            settingsPath: 'privacy/hide-personal-data/add-name',
            direction: 'forward',
            icon: 'user',
            title: $text('settings.privacy.add_name')
        });
    }

    function navigateToAddAddress() {
        dispatch('openSettings', {
            settingsPath: 'privacy/hide-personal-data/add-address',
            direction: 'forward',
            icon: 'maps',
            title: $text('settings.privacy.add_address')
        });
    }

    function navigateToAddBirthday() {
        dispatch('openSettings', {
            settingsPath: 'privacy/hide-personal-data/add-birthday',
            direction: 'forward',
            icon: 'gift',
            title: $text('settings.privacy.add_birthday')
        });
    }

    function navigateToAddCustomEntry() {
        dispatch('openSettings', {
            settingsPath: 'privacy/hide-personal-data/add-custom',
            direction: 'forward',
            icon: 'create',
            title: $text('settings.privacy.add_custom_entry')
        });
    }
</script>

<!-- SecurityAuth modal — shown when user clicks a contact/custom entry without recent verification -->
{#if showAuthModal}
    <SecurityAuth
        {hasPasskey}
        {hasPassword}
        {has2FA}
        autoStart={hasPasskey}
        onSuccess={handleAuthSuccess}
        onFailed={handleAuthFailed}
        onCancel={handleAuthCancel}
        title={$text('settings.privacy.auth.title')}
        description={$text('settings.privacy.auth.description')}
    />
{/if}

<!-- Master Toggle: Hide personal data on/off -->
<div class="master-toggle-row">
    <SettingsItem
        type="heading"
        icon="anonym"
        title={$text('settings.privacy.hide_personal_data')}
        hasToggle={true}
        checked={masterEnabled}
        onClick={handleMasterToggle}
    />
</div>

<!-- Description -->
<div class="description-section">
    <p class="description-text">
        {$text('settings.privacy.hide_personal_data.description')}
    </p>
</div>

<!-- ─── Contacts Section (unified Names, Addresses, Birthdays) ─────────────── -->
<SettingsItem
    type="heading"
    icon="contact"
    title={$text('settings.privacy.contacts')}
/>

{#each contactEntries as entry (entry.id)}
    <SettingsItem
        type="subsubmenu"
        icon={getContactEntryIcon(entry)}
        title={entry.title}
        hasToggle={true}
        checked={entry.enabled}
        onClick={() => handleEntryClick(entry)}
    />
{/each}

<!-- Add name -->
<div class="add-entry-row" role="button" tabindex="0" onclick={navigateToAddName} onkeydown={(e) => e.key === 'Enter' && navigateToAddName()}>
    <SettingsItem
        type="subsubmenu"
        icon="create"
        title={$text('settings.privacy.add_name')}
        onClick={navigateToAddName}
    />
</div>

<!-- Add address -->
<div class="add-entry-row" role="button" tabindex="0" onclick={navigateToAddAddress} onkeydown={(e) => e.key === 'Enter' && navigateToAddAddress()}>
    <SettingsItem
        type="subsubmenu"
        icon="create"
        title={$text('settings.privacy.add_address')}
        onClick={navigateToAddAddress}
    />
</div>

<!-- Add birthday -->
<div class="add-entry-row" role="button" tabindex="0" onclick={navigateToAddBirthday} onkeydown={(e) => e.key === 'Enter' && navigateToAddBirthday()}>
    <SettingsItem
        type="subsubmenu"
        icon="create"
        title={$text('settings.privacy.add_birthday')}
        onClick={navigateToAddBirthday}
    />
</div>

<!-- ─── For Everyone Section (Auto-detected patterns) ─────────────────────── -->
<SettingsItem
    type="heading"
    icon="user"
    title={$text('settings.privacy.for_everyone')}
/>

<SettingsItem
    type="subsubmenu"
    icon="mail"
    title={$text('settings.privacy.email_addresses')}
    hasToggle={true}
    checked={isCategoryOn('email_addresses')}
    onClick={() => handleCategoryToggle('email_addresses')}
/>

<SettingsItem
    type="subsubmenu"
    icon="phone"
    title={$text('settings.privacy.phone_numbers')}
    hasToggle={true}
    checked={isCategoryOn('phone_numbers')}
    onClick={() => handleCategoryToggle('phone_numbers')}
/>

<SettingsItem
    type="subsubmenu"
    icon="billing"
    title={$text('settings.privacy.credit_card_numbers')}
    hasToggle={true}
    checked={isCategoryOn('credit_card_numbers')}
    onClick={() => handleCategoryToggle('credit_card_numbers')}
/>

<SettingsItem
    type="subsubmenu"
    icon="money"
    title={$text('settings.privacy.iban_bank_account')}
    hasToggle={true}
    checked={isCategoryOn('iban_bank_account')}
    onClick={() => handleCategoryToggle('iban_bank_account')}
/>

<SettingsItem
    type="subsubmenu"
    icon="billing"
    title={$text('settings.privacy.tax_id_vat')}
    hasToggle={true}
    checked={isCategoryOn('tax_id_vat')}
    onClick={() => handleCategoryToggle('tax_id_vat')}
/>

<SettingsItem
    type="subsubmenu"
    icon="coins"
    title={$text('settings.privacy.crypto_wallets')}
    hasToggle={true}
    checked={isCategoryOn('crypto_wallets')}
    onClick={() => handleCategoryToggle('crypto_wallets')}
/>

<SettingsItem
    type="subsubmenu"
    icon="lock"
    title={$text('settings.privacy.social_security_numbers')}
    hasToggle={true}
    checked={isCategoryOn('social_security_numbers')}
    onClick={() => handleCategoryToggle('social_security_numbers')}
/>

<SettingsItem
    type="subsubmenu"
    icon="lock"
    title={$text('settings.privacy.passport_numbers')}
    hasToggle={true}
    checked={isCategoryOn('passport_numbers')}
    onClick={() => handleCategoryToggle('passport_numbers')}
/>

<!-- ─── For Developers Section ────────────────────────────────────────────── -->
<SettingsItem
    type="heading"
    icon="coding"
    title={$text('settings.privacy.for_developers')}
/>

<SettingsItem
    type="subsubmenu"
    icon="secret"
    title={$text('settings.privacy.api_keys')}
    hasToggle={true}
    checked={isCategoryOn('api_keys')}
    onClick={() => handleCategoryToggle('api_keys')}
/>

<SettingsItem
    type="subsubmenu"
    icon="secret"
    title={$text('settings.privacy.jwt_tokens')}
    hasToggle={true}
    checked={isCategoryOn('jwt_tokens')}
    onClick={() => handleCategoryToggle('jwt_tokens')}
/>

<SettingsItem
    type="subsubmenu"
    icon="lock"
    title={$text('settings.privacy.private_keys')}
    hasToggle={true}
    checked={isCategoryOn('private_keys')}
    onClick={() => handleCategoryToggle('private_keys')}
/>

<SettingsItem
    type="subsubmenu"
    icon="secret"
    title={$text('settings.privacy.generic_secrets')}
    hasToggle={true}
    checked={isCategoryOn('generic_secrets')}
    onClick={() => handleCategoryToggle('generic_secrets')}
/>

<SettingsItem
    type="subsubmenu"
    icon="server"
    title={$text('settings.privacy.ip_addresses')}
    hasToggle={true}
    checked={isCategoryOn('ip_addresses')}
    onClick={() => handleCategoryToggle('ip_addresses')}
/>

<SettingsItem
    type="subsubmenu"
    icon="server"
    title={$text('settings.privacy.mac_addresses')}
    hasToggle={true}
    checked={isCategoryOn('mac_addresses')}
    onClick={() => handleCategoryToggle('mac_addresses')}
/>

<SettingsItem
    type="subsubmenu"
    icon="laptop"
    title={$text('settings.privacy.user_at_hostname')}
    hasToggle={true}
    checked={isCategoryOn('user_at_hostname')}
    onClick={() => handleCategoryToggle('user_at_hostname')}
/>

<SettingsItem
    type="subsubmenu"
    icon="home"
    title={$text('settings.privacy.home_folder')}
    hasToggle={true}
    checked={isCategoryOn('home_folder')}
    onClick={() => handleCategoryToggle('home_folder')}
/>

<!-- ─── Custom Section ────────────────────────────────────────────────────── -->
<SettingsItem
    type="heading"
    icon="create"
    title={$text('common.custom')}
/>

{#each customEntries as entry (entry.id)}
    <SettingsItem
        type="subsubmenu"
        icon="create"
        title={entry.title}
        hasToggle={true}
        checked={entry.enabled}
        onClick={() => handleEntryClick(entry)}
    />
{/each}

<div class="add-entry-row" role="button" tabindex="0" onclick={navigateToAddCustomEntry} onkeydown={(e) => e.key === 'Enter' && navigateToAddCustomEntry()}>
    <SettingsItem
        type="subsubmenu"
        icon="create"
        title={$text('settings.privacy.add_custom_entry')}
        onClick={navigateToAddCustomEntry}
    />
</div>

<!-- Encryption note -->
<div class="encryption-note">
    <p>{$text('settings.privacy.encryption_note')}</p>
</div>

<style>
    .master-toggle-row {
        margin-bottom: 4px;
    }

    .description-section {
        padding: 4px 16px 12px;
    }

    .description-text {
        font-size: 16px;
        color: var(--color-grey-100);
        line-height: 1.5;
        margin: 0;
    }

    .add-entry-row :global(.menu-title) {
        background: var(--gradient-primary);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        font-weight: 700;
    }

    .encryption-note {
        padding: 10px 16px;
    }

    .encryption-note p {
        font-size: 14px;
        font-weight: 500;
        color: var(--color-grey-60);
        line-height: 1.5;
        margin: 0;
    }
</style>
