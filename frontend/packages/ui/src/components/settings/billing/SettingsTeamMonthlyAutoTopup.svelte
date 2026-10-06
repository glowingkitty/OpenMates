<script lang="ts">
    import { onMount, tick } from 'svelte';
    import { text } from '@repo/ui';
    import { loadStripe } from '@stripe/stripe-js';
    import { pricingTiers } from '../../../config/pricing';
    import { apiEndpoints, getApiEndpoint } from '../../../config/api';
    import { getEmailEncryptionKeyForApi } from '../../../services/cryptoService';
    import { billingPath, loadBillingAddress, type BillingContext } from '../../../services/billingContext';
    import {
        SettingsButton, SettingsButtonGroup, SettingsConfirmBlock, SettingsDetailRow,
        SettingsDropdown, SettingsInfoBox, SettingsPageContainer, SettingsPageHeader,
        SettingsSectionHeading, SettingsCard,
    } from '../elements';

    let { teamId, preview = false }: { teamId: string; preview?: boolean } = $props();
    let context: BillingContext = $derived({ kind: 'team', teamId });
    let selectedCredits = $state('');
    let selectedCurrency = $state('EUR');
    let billingDay = $state('anniversary');
    let subscription = $state<Record<string, unknown> | null>(null);
    let loading = $state(true);
    let processing = $state(false);
    let error = $state('');
    let loadError = $state(false);
    let pending = $state(false);
    let checkoutActive = $state(false);
    let cancelChecked = $state(false);
    let checkout: { destroy: () => void; unmount: () => void } | null = null;
    let confirmationTimer: ReturnType<typeof setTimeout> | null = null;
    let disposed = false;

    const tiers = pricingTiers.filter(tier => !!tier.monthly_auto_top_up_extra_credits && !tier.bank_transfer_only);
    let tierOptions = $derived(tiers.filter(tier => tier.price[selectedCurrency.toLowerCase() as 'eur' | 'usd'] !== undefined)
        .map(tier => ({ value: String(tier.credits),
            label: `${tier.credits.toLocaleString()} + ${tier.monthly_auto_top_up_extra_credits.toLocaleString()} bonus credits / month` })));
    let dayOptions = $derived([
        { value: 'anniversary', label: $text('settings.billing.team_monthly_anniversary') },
        { value: 'first_of_month', label: $text('settings.billing.team_monthly_first') },
    ]);

    async function loadSubscription(): Promise<void> {
        if (preview) { loading = false; return; }
        loading = true;
        error = '';
        loadError = false;
        try {
            const response = await fetch(monthlyPath(), { credentials: 'include' });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const data = await response.json();
            if (disposed) return;
            subscription = data.has_subscription ? data.subscription ?? null : null;
            if (subscription) pending = false;
            billingDay = String(subscription?.billing_day_preference ?? 'anniversary');
        } catch {
            if (!disposed) { error = $text('settings.billing.team_monthly_error'); loadError = true; }
        } finally {
            if (!disposed) loading = false;
        }
    }

    async function waitForSubscription(attempt = 0): Promise<void> {
        await loadSubscription();
        if (disposed || subscription) return;
        if (attempt >= 11) { pending = false; error = $text('settings.billing.team_monthly_error'); return; }
        confirmationTimer = setTimeout(() => { void waitForSubscription(attempt + 1); }, 5000);
    }

    function monthlyPath(): string {
        return billingPath(context, 'monthly');
    }

    function changeCurrency(value: string): void {
        selectedCurrency = value;
        if (!tierOptions.some(tier => tier.value === selectedCredits)) selectedCredits = tierOptions[0]?.value ?? '';
    }

    async function createSubscription(): Promise<void> {
        if (!selectedCredits || processing || checkoutActive || !teamId) return;
        error = '';
        processing = true;
        try {
            const buyerAddress = await loadBillingAddress(context);
            if (disposed) return;
            const emailKey = getEmailEncryptionKeyForApi();
            if (!emailKey) throw new Error('Account email encryption key unavailable');
            const returnUrl = new URL(window.location.href).toString();
            const response = await fetch(monthlyPath(), {
                method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ credits_amount: Number(selectedCredits), currency: selectedCurrency.toLowerCase(),
                    billing_day_preference: billingDay, return_url: returnUrl,
                    email_encryption_key: emailKey,
                    ...(buyerAddress ? { buyer_address: buyerAddress } : {}) }),
            });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const data = await response.json();
            if (disposed || !data.client_secret) throw new Error('Monthly checkout unavailable');
            const configResponse = await fetch(getApiEndpoint(apiEndpoints.payments.config), { credentials: 'include' });
            if (!configResponse.ok) throw new Error('Payment configuration unavailable');
            const config = await configResponse.json();
            const stripe = await loadStripe(config.public_key);
            if (disposed || !stripe) throw new Error('Payment form unavailable');
            await tick();
            checkout?.destroy();
            checkout = await stripe.initEmbeddedCheckout({
                fetchClientSecret: async () => data.client_secret,
                onComplete: () => {
                    if (disposed) return;
                    checkout?.unmount();
                    checkout = null;
                    checkoutActive = false;
                    pending = true;
                    void waitForSubscription();
                },
            });
            if (disposed) { checkout.destroy(); checkout = null; return; }
            checkout.mount('#team-monthly-checkout');
            checkoutActive = true;
        } catch {
            if (!disposed) error = $text('settings.billing.team_monthly_error');
        } finally {
            if (!disposed) processing = false;
        }
    }

    async function updateBillingDay(value: string): Promise<void> {
        if (preview) { billingDay = value; return; }
        error = '';
        const response = await fetch(`${monthlyPath()}/billing-day`, {
            method: 'PATCH', credentials: 'include', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ billing_day_preference: value }),
        }).catch(() => null);
        if (!response?.ok) error = $text('settings.billing.team_monthly_error');
        else billingDay = value;
    }

    async function cancelSubscription(): Promise<void> {
        if (!cancelChecked || processing) return;
        if (preview) { subscription = null; cancelChecked = false; return; }
        processing = true;
        error = '';
        try {
            const response = await fetch(`${monthlyPath()}/cancel`, { method: 'POST', credentials: 'include' });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            await loadSubscription();
            cancelChecked = false;
        } catch {
            error = $text('settings.billing.team_monthly_error');
        } finally { processing = false; }
    }

    onMount(() => {
        selectedCredits = tierOptions[0]?.value ?? '';
        const sessionId = new URLSearchParams(window.location.search).get('session_id');
        if (!preview && sessionId?.startsWith('cs_')) {
            const cleanUrl = new URL(window.location.href);
            cleanUrl.searchParams.delete('session_id');
            window.history.replaceState({}, '', cleanUrl.toString());
            pending = true;
            void waitForSubscription();
        } else void loadSubscription();
        return () => { disposed = true; checkout?.destroy(); if (confirmationTimer) clearTimeout(confirmationTimer); };
    });
</script>

<SettingsPageContainer>
    <div data-testid="team-monthly-auto-topup">
        <SettingsPageHeader title={$text('settings.billing.team_monthly_auto_topup')} />
        {#if loading}
            <SettingsInfoBox type="info"><p>{$text('common.loading')}</p></SettingsInfoBox>
        {:else if pending}
            <SettingsInfoBox type="info"><p>{$text('settings.billing.invoices_generating')}</p></SettingsInfoBox>
        {:else if loadError}
            <SettingsInfoBox type="warning"><p role="alert">{$text('settings.billing.team_monthly_error')}</p></SettingsInfoBox>
            <SettingsButton variant="secondary" dataTestid="team-monthly-retry" onClick={() => void loadSubscription()}>{$text('common.retry')}</SettingsButton>
        {:else if subscription}
            <SettingsCard>
                <SettingsDetailRow label={$text('settings.billing.team_monthly_status')} value={String(subscription.status ?? 'unknown')} />
                <SettingsDetailRow label={$text('settings.billing.amount')} value={`${Number(subscription.credits_amount ?? 0).toLocaleString()} credits / month`} />
                <SettingsDetailRow label={$text('settings.billing.next_charge')} value={String(subscription.next_billing_date ?? '—')} />
            </SettingsCard>
            <SettingsSectionHeading title={$text('settings.billing.team_monthly_billing_day')} icon="calendar" />
            <SettingsDropdown value={billingDay} options={dayOptions} dataTestid="team-monthly-billing-day"
                onChange={(value) => void updateBillingDay(value)} />
            <SettingsConfirmBlock warningText={$text('settings.billing.team_monthly_cancel')}
                confirmLabel={$text('settings.billing.team_monthly_cancel')} bind:checked={cancelChecked} />
            <SettingsButton variant="danger" disabled={!cancelChecked} loading={processing}
                dataTestid="team-monthly-cancel" onClick={() => void cancelSubscription()}>
                {$text('settings.billing.team_monthly_cancel')}
            </SettingsButton>
        {:else}
            <SettingsDropdown bind:value={selectedCredits} options={tierOptions}
                placeholder={$text('settings.billing.team_monthly_tier')}
                ariaLabel={$text('settings.billing.team_monthly_tier')} dataTestid="team-monthly-tier" />
            <SettingsDropdown bind:value={selectedCurrency}
                options={[{ value: 'EUR', label: 'EUR (€)' }, { value: 'USD', label: 'USD ($)' }]}
                onChange={changeCurrency}
                ariaLabel={$text('settings.billing.currency')} dataTestid="team-monthly-currency" />
            <SettingsDropdown bind:value={billingDay} options={dayOptions}
                ariaLabel={$text('settings.billing.team_monthly_billing_day')} dataTestid="team-monthly-day" />
            <SettingsButtonGroup align="left"><SettingsButton loading={processing} disabled={!selectedCredits || checkoutActive}
                dataTestid="team-monthly-create" onClick={() => void createSubscription()}>
                {$text('settings.billing.team_monthly_create')}
            </SettingsButton></SettingsButtonGroup>
            <div id="team-monthly-checkout" data-testid="team-monthly-checkout"></div>
        {/if}
        {#if error}<SettingsInfoBox type="warning"><p role="alert">{error}</p></SettingsInfoBox>{/if}
    </div>
</SettingsPageContainer>
