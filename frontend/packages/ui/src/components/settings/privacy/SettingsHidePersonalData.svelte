<!--
Hide Personal Data Settings - Sub-page for managing PII detection and custom personal data entries.

Users can:
- Toggle the master PII detection on/off
- Manage custom names, addresses, birthdays to detect and replace
- Toggle individual auto-detection categories (email, phone, credit card, etc.)
- Add custom entries for any text they want to hide

All user-defined entries (names, addresses, birthdays, custom values) are
client-side encrypted — the server never sees the actual data.

Based on Figma design: settings/privacy/hide_personal_data (node 4660:42313)
-->

<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import { text } from '@repo/ui';
    import SettingsItem from '../../SettingsItem.svelte';
    import { personalDataStore, type PersonalDataEntry } from '../../../stores/personalDataStore';

    const dispatch = createEventDispatcher();

    // ─── Store Subscriptions ─────────────────────────────────────────────────

    let piiSettings = $state({ masterEnabled: true, categories: {} as Record<string, boolean> });
    personalDataStore.settings.subscribe((s) => { piiSettings = s; });

    let allEntries: PersonalDataEntry[] = $state([]);
    personalDataStore.subscribe((entries) => { allEntries = entries; });

    // ─── Derived Entry Lists ─────────────────────────────────────────────────

    let nameEntries = $derived(allEntries.filter(e => e.type === 'name'));
    let addressEntries = $derived(allEntries.filter(e => e.type === 'address'));
    let birthdayEntries = $derived(allEntries.filter(e => e.type === 'birthday'));
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

    // ─── Entry Toggles ───────────────────────────────────────────────────────

    function handleEntryToggle(id: string) {
        personalDataStore.toggleEntry(id);
    }

    // ─── Navigation ──────────────────────────────────────────────────────────

    function navigateToAddName() {
        dispatch('openSettings', {
            settingsPath: 'privacy/hide-personal-data/add-name',
            direction: 'forward',
            icon: 'user',
            title: $text('settings.privacy.privacy.add_name.text')
        });
    }

    function navigateToAddAddress() {
        dispatch('openSettings', {
            settingsPath: 'privacy/hide-personal-data/add-address',
            direction: 'forward',
            icon: 'user',
            title: $text('settings.privacy.privacy.add_address.text')
        });
    }

    function navigateToAddBirthday() {
        dispatch('openSettings', {
            settingsPath: 'privacy/hide-personal-data/add-birthday',
            direction: 'forward',
            icon: 'user',
            title: $text('settings.privacy.privacy.add_birthday.text')
        });
    }

    function navigateToAddCustomEntry() {
        dispatch('openSettings', {
            settingsPath: 'privacy/hide-personal-data/add-custom',
            direction: 'forward',
            icon: 'user',
            title: $text('settings.privacy.privacy.add_custom_entry.text')
        });
    }
</script>

<!-- Master Toggle: Hide personal data on/off -->
<div class="master-toggle-row">
    <SettingsItem
        type="heading"
        icon="user"
        title={$text('settings.privacy.privacy.hide_personal_data.text')}
        hasToggle={true}
        checked={masterEnabled}
        onClick={handleMasterToggle}
    />
</div>

<!-- Description -->
<div class="description-section">
    <p class="description-text">
        {$text('settings.privacy.privacy.hide_personal_data.description.text')}
    </p>
</div>

<!-- ─── Names Section ─────────────────────────────────────────────────────── -->
<SettingsItem
    type="heading"
    icon="user"
    title={$text('settings.privacy.privacy.names.text')}
/>

{#each nameEntries as entry (entry.id)}
    <SettingsItem
        type="subsubmenu"
        icon="search"
        title={entry.title}
        hasToggle={true}
        checked={entry.enabled}
        onClick={() => handleEntryToggle(entry.id)}
    />
{/each}

<div class="add-entry-row" role="button" tabindex="0" onclick={navigateToAddName} onkeydown={(e) => e.key === 'Enter' && navigateToAddName()}>
    <SettingsItem
        type="subsubmenu"
        icon="search"
        title={$text('settings.privacy.privacy.add_name.text')}
        onClick={navigateToAddName}
    />
</div>

<!-- ─── Addresses Section ─────────────────────────────────────────────────── -->
<SettingsItem
    type="heading"
    icon="user"
    title={$text('settings.privacy.privacy.addresses.text')}
/>

{#each addressEntries as entry (entry.id)}
    <SettingsItem
        type="subsubmenu"
        icon="search"
        title={entry.title}
        hasToggle={true}
        checked={entry.enabled}
        onClick={() => handleEntryToggle(entry.id)}
    />
{/each}

<div class="add-entry-row" role="button" tabindex="0" onclick={navigateToAddAddress} onkeydown={(e) => e.key === 'Enter' && navigateToAddAddress()}>
    <SettingsItem
        type="subsubmenu"
        icon="search"
        title={$text('settings.privacy.privacy.add_address.text')}
        onClick={navigateToAddAddress}
    />
</div>

<!-- ─── Birthday Section ──────────────────────────────────────────────────── -->
<SettingsItem
    type="heading"
    icon="user"
    title={$text('settings.privacy.privacy.birthday.text')}
/>

{#each birthdayEntries as entry (entry.id)}
    <SettingsItem
        type="subsubmenu"
        icon="search"
        title={entry.title}
        hasToggle={true}
        checked={entry.enabled}
        onClick={() => handleEntryToggle(entry.id)}
    />
{/each}

<div class="add-entry-row" role="button" tabindex="0" onclick={navigateToAddBirthday} onkeydown={(e) => e.key === 'Enter' && navigateToAddBirthday()}>
    <SettingsItem
        type="subsubmenu"
        icon="search"
        title={$text('settings.privacy.privacy.add_birthday.text')}
        onClick={navigateToAddBirthday}
    />
</div>

<!-- ─── For Everyone Section (Auto-detected patterns) ─────────────────────── -->
<SettingsItem
    type="heading"
    icon="user"
    title={$text('settings.privacy.privacy.for_everyone.text')}
/>

<SettingsItem
    type="subsubmenu"
    icon="search"
    title={$text('settings.privacy.privacy.email_addresses.text')}
    hasToggle={true}
    checked={isCategoryOn('email_addresses')}
    onClick={() => handleCategoryToggle('email_addresses')}
/>

<SettingsItem
    type="subsubmenu"
    icon="search"
    title={$text('settings.privacy.privacy.phone_numbers.text')}
    hasToggle={true}
    checked={isCategoryOn('phone_numbers')}
    onClick={() => handleCategoryToggle('phone_numbers')}
/>

<SettingsItem
    type="subsubmenu"
    icon="search"
    title={$text('settings.privacy.privacy.credit_card_numbers.text')}
    hasToggle={true}
    checked={isCategoryOn('credit_card_numbers')}
    onClick={() => handleCategoryToggle('credit_card_numbers')}
/>

<SettingsItem
    type="subsubmenu"
    icon="search"
    title={$text('settings.privacy.privacy.iban_bank_account.text')}
    hasToggle={true}
    checked={isCategoryOn('iban_bank_account')}
    onClick={() => handleCategoryToggle('iban_bank_account')}
/>

<SettingsItem
    type="subsubmenu"
    icon="search"
    title={$text('settings.privacy.privacy.tax_id_vat.text')}
    hasToggle={true}
    checked={isCategoryOn('tax_id_vat')}
    onClick={() => handleCategoryToggle('tax_id_vat')}
/>

<SettingsItem
    type="subsubmenu"
    icon="search"
    title={$text('settings.privacy.privacy.crypto_wallets.text')}
    hasToggle={true}
    checked={isCategoryOn('crypto_wallets')}
    onClick={() => handleCategoryToggle('crypto_wallets')}
/>

<SettingsItem
    type="subsubmenu"
    icon="search"
    title={$text('settings.privacy.privacy.social_security_numbers.text')}
    hasToggle={true}
    checked={isCategoryOn('social_security_numbers')}
    onClick={() => handleCategoryToggle('social_security_numbers')}
/>

<SettingsItem
    type="subsubmenu"
    icon="search"
    title={$text('settings.privacy.privacy.passport_numbers.text')}
    hasToggle={true}
    checked={isCategoryOn('passport_numbers')}
    onClick={() => handleCategoryToggle('passport_numbers')}
/>

<!-- ─── For Developers Section ────────────────────────────────────────────── -->
<SettingsItem
    type="heading"
    icon="user"
    title={$text('settings.privacy.privacy.for_developers.text')}
/>

<SettingsItem
    type="subsubmenu"
    icon="search"
    title={$text('settings.privacy.privacy.api_keys.text')}
    hasToggle={true}
    checked={isCategoryOn('api_keys')}
    onClick={() => handleCategoryToggle('api_keys')}
/>

<SettingsItem
    type="subsubmenu"
    icon="search"
    title={$text('settings.privacy.privacy.jwt_tokens.text')}
    hasToggle={true}
    checked={isCategoryOn('jwt_tokens')}
    onClick={() => handleCategoryToggle('jwt_tokens')}
/>

<SettingsItem
    type="subsubmenu"
    icon="search"
    title={$text('settings.privacy.privacy.private_keys.text')}
    hasToggle={true}
    checked={isCategoryOn('private_keys')}
    onClick={() => handleCategoryToggle('private_keys')}
/>

<SettingsItem
    type="subsubmenu"
    icon="search"
    title={$text('settings.privacy.privacy.generic_secrets.text')}
    hasToggle={true}
    checked={isCategoryOn('generic_secrets')}
    onClick={() => handleCategoryToggle('generic_secrets')}
/>

<SettingsItem
    type="subsubmenu"
    icon="search"
    title={$text('settings.privacy.privacy.ip_addresses.text')}
    hasToggle={true}
    checked={isCategoryOn('ip_addresses')}
    onClick={() => handleCategoryToggle('ip_addresses')}
/>

<SettingsItem
    type="subsubmenu"
    icon="search"
    title={$text('settings.privacy.privacy.mac_addresses.text')}
    hasToggle={true}
    checked={isCategoryOn('mac_addresses')}
    onClick={() => handleCategoryToggle('mac_addresses')}
/>

<SettingsItem
    type="subsubmenu"
    icon="search"
    title={$text('settings.privacy.privacy.user_at_hostname.text')}
    hasToggle={true}
    checked={isCategoryOn('user_at_hostname')}
    onClick={() => handleCategoryToggle('user_at_hostname')}
/>

<SettingsItem
    type="subsubmenu"
    icon="search"
    title={$text('settings.privacy.privacy.home_folder.text')}
    hasToggle={true}
    checked={isCategoryOn('home_folder')}
    onClick={() => handleCategoryToggle('home_folder')}
/>

<!-- ─── Custom Section ────────────────────────────────────────────────────── -->
<SettingsItem
    type="heading"
    icon="user"
    title={$text('settings.privacy.privacy.custom.text')}
/>

{#each customEntries as entry (entry.id)}
    <SettingsItem
        type="subsubmenu"
        icon="search"
        title={entry.title}
        hasToggle={true}
        checked={entry.enabled}
        onClick={() => handleEntryToggle(entry.id)}
    />
{/each}

<div class="add-entry-row" role="button" tabindex="0" onclick={navigateToAddCustomEntry} onkeydown={(e) => e.key === 'Enter' && navigateToAddCustomEntry()}>
    <SettingsItem
        type="subsubmenu"
        icon="search"
        title={$text('settings.privacy.privacy.add_custom_entry.text')}
        onClick={navigateToAddCustomEntry}
    />
</div>

<!-- Encryption note -->
<div class="encryption-note">
    <p>{$text('settings.privacy.privacy.encryption_note.text')}</p>
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
