<script lang="ts">
    import { text } from '@repo/ui';
    import { onMount } from 'svelte';
    import {
        SettingsButton, SettingsButtonGroup, SettingsInfoBox, SettingsInput,
        SettingsPageContainer, SettingsPageHeader, SettingsSectionHeading,
    } from '../elements';
    import {
        loadBillingAddress, saveBillingAddress, type BillingAddress,
        type BillingContext,
    } from '../../../services/billingContext';

    let { teamId = null, preview = false, initialAddress = null }: {
        teamId?: string | null;
        preview?: boolean;
        initialAddress?: BillingAddress | null;
    } = $props();
    let context: BillingContext = $derived(teamId ? { kind: 'team', teamId } : { kind: 'personal' });
    let name = $state('');
    let streetLine1 = $state('');
    let streetLine2 = $state('');
    let postalCode = $state('');
    let city = $state('');
    let region = $state('');
    let country = $state('');
    let vatId = $state('');
    let expanded = $state(false);
    let loading = $state(true);
    let saving = $state(false);
    let error = $state('');
    let saved = $state(false);
    let requestVersion = 0;

    function populate(address: BillingAddress | null): void {
        name = address?.name ?? '';
        streetLine1 = address?.street_line_1 ?? '';
        streetLine2 = address?.street_line_2 ?? '';
        postalCode = address?.postal_code ?? '';
        city = address?.city ?? '';
        region = address?.region ?? '';
        country = address?.country ?? '';
        vatId = address?.vat_id ?? '';
        expanded = !!teamId || !!address;
    }

    onMount(() => {
        const version = ++requestVersion;
        if (preview) { populate(initialAddress); loading = false; return; }
        void loadBillingAddress(context).then(address => {
            if (version === requestVersion) populate(address);
        }).catch(() => {
            if (version === requestVersion) error = $text('settings.billing.address_load_error');
        }).finally(() => { if (version === requestVersion) loading = false; });
        return () => { requestVersion++; };
    });

    async function save(): Promise<void> {
        if (saving) return;
        error = '';
        saved = false;
        const values = [name, streetLine1, streetLine2, postalCode, city, region, country, vatId].map(v => v.trim());
        const hasAny = values.some(Boolean);
        if (hasAny && (!name.trim() || !streetLine1.trim() || !postalCode.trim() || !city.trim() || !/^[A-Za-z]{2}$/.test(country.trim()))) {
            error = $text('settings.billing.address_validation');
            return;
        }
        const address: BillingAddress | null = hasAny ? {
            name: name.trim(), street_line_1: streetLine1.trim(),
            street_line_2: streetLine2.trim() || null, postal_code: postalCode.trim(),
            city: city.trim(), region: region.trim() || null,
            country: country.trim().toUpperCase(), vat_id: vatId.trim() || null,
        } : null;
        if (preview) { saved = true; return; }
        const version = ++requestVersion;
        saving = true;
        try {
            const result = await saveBillingAddress(context, address);
            if (version !== requestVersion) return;
            populate(result);
            saved = true;
        } catch {
            if (version === requestVersion) error = $text('settings.billing.address_save_error');
        } finally {
            if (version === requestVersion) saving = false;
        }
    }
</script>

<SettingsPageContainer>
    <div data-testid="billing-address-page">
        <SettingsPageHeader title={$text('settings.billing.billing_address')} description={$text('settings.billing.address_optional_explainer')} />
        {#if loading}
            <SettingsInfoBox type="info"><p>{$text('common.loading')}</p></SettingsInfoBox>
        {:else}
            {#if !expanded}
                <SettingsButton variant="secondary" dataTestid="billing-address-add" onClick={() => expanded = true}>
                    {$text('settings.billing.add_billing_address')}
                </SettingsButton>
            {:else}
                <div data-testid="billing-address-form">
                    <SettingsSectionHeading title={$text('settings.billing.billing_address')} icon="location" />
                    <SettingsInput bind:value={name} ariaLabel={$text('settings.billing.address_name')} placeholder={$text('settings.billing.address_name')} dataTestid="billing-address-name" />
                    <SettingsInput bind:value={streetLine1} ariaLabel={$text('settings.billing.address_street_line_1')} placeholder={$text('settings.billing.address_street_line_1')} dataTestid="billing-address-street" />
                    <SettingsInput bind:value={streetLine2} ariaLabel={$text('settings.billing.address_street_line_2')} placeholder={$text('settings.billing.address_street_line_2')} dataTestid="billing-address-street-2" />
                    <SettingsInput bind:value={postalCode} ariaLabel={$text('settings.billing.address_postal_code')} placeholder={$text('settings.billing.address_postal_code')} dataTestid="billing-address-postal-code" />
                    <SettingsInput bind:value={city} ariaLabel={$text('settings.billing.address_city')} placeholder={$text('settings.billing.address_city')} dataTestid="billing-address-city" />
                    <SettingsInput bind:value={region} ariaLabel={$text('settings.billing.address_region')} placeholder={$text('settings.billing.address_region')} dataTestid="billing-address-region" />
                    <SettingsInput bind:value={country} ariaLabel={$text('settings.billing.address_country')} placeholder={$text('settings.billing.address_country')} maxlength={2} dataTestid="billing-address-country" />
                    <SettingsInput bind:value={vatId} ariaLabel={$text('settings.billing.address_vat_id')} placeholder={$text('settings.billing.address_vat_id')} dataTestid="billing-address-vat-id" />
                    <SettingsButtonGroup align="left">
                        <SettingsButton loading={saving} dataTestid="billing-address-save" onClick={() => void save()}>{$text('common.save')}</SettingsButton>
                    </SettingsButtonGroup>
                </div>
            {/if}
            {#if error}<SettingsInfoBox type="warning"><p>{error}</p></SettingsInfoBox>{/if}
            {#if saved}<SettingsInfoBox type="success"><p data-testid="billing-address-saved">{$text('settings.billing.address_saved')}</p></SettingsInfoBox>{/if}
        {/if}
    </div>
</SettingsPageContainer>
