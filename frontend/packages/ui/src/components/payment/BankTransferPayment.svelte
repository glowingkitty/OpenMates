<!--
  BankTransferPayment.svelte

  Displays company bank details (IBAN, BIC, account holder name, reference)
  for a SEPA bank transfer, using canonical settings UI elements.

  All value fields are user-selectable text. Copy icons use SettingsCodeBlock pattern.
  Polls for transfer completion and listens for WebSocket payment_completed events.
-->
<script lang="ts">
    import { text } from '@repo/ui';
    import { fade } from 'svelte/transition';
    import { onMount, onDestroy, createEventDispatcher } from 'svelte';
    import { copyToClipboard } from '../../utils/clipboardUtils';
    import { apiEndpoints, getApiEndpoint } from '../../config/api';
    import { webSocketService } from '../../services/websocketService';
    import {
        SettingsCard,
        SettingsInfoBox,
        SettingsPageHeader,
    } from '../settings/elements';

    const dispatch = createEventDispatcher();

    let {
        credits_amount,
        price,
        currency = 'EUR',
        isSupportContribution = false,
        supportEmail = '',
        emailEncryptionKey = '',
        allowContinueWithoutPayment = false,
        isSignup = false,
    }: {
        credits_amount: number;
        price: number;
        currency?: string;
        isSupportContribution?: boolean;
        supportEmail?: string;
        emailEncryptionKey?: string;
        allowContinueWithoutPayment?: boolean;
        isSignup?: boolean;
    } = $props();

    let state: 'loading' | 'awaiting_transfer' | 'completed' | 'error' = $state('loading');
    let errorMessage: string = $state('');

    let orderId: string = $state('');
    let reference: string = $state('');
    let iban: string = $state('');
    let bic: string = $state('');
    let bankName: string = $state('');
    let accountHolderName: string = $state('');
    let amountEur: string = $state('');
    let expiresAt: string = $state('');

    // Per-field copy feedback
    let copiedField: string = $state('');
    let copyTimeout: ReturnType<typeof setTimeout> | null = null;
    let pollInterval: ReturnType<typeof setInterval> | null = null;

    onMount(async () => { await createOrder(); });

    onDestroy(() => {
        if (pollInterval) clearInterval(pollInterval);
        if (copyTimeout) clearTimeout(copyTimeout);
        webSocketService.off('payment_completed', handlePaymentCompleted);
    });

    async function createOrder() {
        state = 'loading';
        try {
            const endpoint = getApiEndpoint(isSupportContribution
                ? apiEndpoints.payments.createSupportBankTransferOrder
                : apiEndpoints.payments.createBankTransferOrder);

            const body = isSupportContribution
                ? { amount: price, currency: currency.toLowerCase(), support_email: supportEmail }
                : { credits_amount, currency: currency.toLowerCase(), email_encryption_key: emailEncryptionKey, is_signup: isSignup };

            const response = await fetch(endpoint, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify(body),
            });

            if (!response.ok) {
                const err = await response.json().catch(() => ({}));
                throw new Error(err.detail || `Server error: ${response.status}`);
            }

            const data = await response.json();
            orderId = data.order_id;
            reference = data.reference;
            iban = data.iban;
            bic = data.bic;
            bankName = data.bank_name;
            accountHolderName = data.account_holder_name || '';
            amountEur = data.amount_eur;
            expiresAt = data.expires_at;

            state = 'awaiting_transfer';
            pollInterval = setInterval(pollStatus, 30_000);
            webSocketService.on('payment_completed', handlePaymentCompleted);
            dispatch('orderCreated', { orderId, reference });

        } catch (err: unknown) {
            state = 'error';
            errorMessage = err instanceof Error ? err.message : 'Failed to create bank transfer order.';
        }
    }

    async function pollStatus() {
        if (!orderId || state !== 'awaiting_transfer') return;
        try {
            const r = await fetch(
                `${getApiEndpoint(apiEndpoints.payments.bankTransferStatus)}/${orderId}`,
                { credentials: 'include' }
            );
            if (!r.ok) return;
            const data = await r.json();
            if (data.status === 'completed') handleCompleted();
        } catch { /* silent */ }
    }

    function handlePaymentCompleted(payload: { order_id?: string }) {
        if (payload?.order_id === orderId) handleCompleted();
    }

    function handleCompleted() {
        state = 'completed';
        if (pollInterval) clearInterval(pollInterval);
        dispatch('paymentStateChange', { state: 'success', provider: 'bank_transfer', payment_intent_id: orderId });
    }

    async function handleCopy(fieldName: string, value: string) {
        const result = await copyToClipboard(value);
        if (result.success) {
            copiedField = fieldName;
            if (copyTimeout) clearTimeout(copyTimeout);
            copyTimeout = setTimeout(() => { copiedField = ''; }, 2000);
        }
    }

    function formatExpiryDate(iso: string): string {
        try {
            return new Date(iso).toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric' });
        } catch { return iso; }
    }
</script>

{#if state === 'loading'}
    <div class="bt-loading" in:fade={{ duration: 200 }}>
        <p class="color-grey-60">{$text('common.loading')}</p>
    </div>

{:else if state === 'error'}
    <div class="bt-error" in:fade={{ duration: 200 }}>
        <SettingsInfoBox type="error">{errorMessage}</SettingsInfoBox>
        <button class="retry-link" onclick={createOrder}>{$text('common.try_again')}</button>
    </div>

{:else if state === 'completed'}
    <div class="bt-completed" in:fade={{ duration: 300 }}>
        <SettingsInfoBox type="success">
            {isSupportContribution ? $text('settings.billing.bank_transfer_received_support') : $text('settings.billing.bank_transfer_received')}
        </SettingsInfoBox>
    </div>

{:else}
    <!-- awaiting_transfer -->
    <div class="bt-details" in:fade={{ duration: 200 }} data-testid="bank-transfer-details">
        <SettingsPageHeader title={$text('settings.billing.bank_transfer_details')} />

        <SettingsCard>
            <!-- Account Holder -->
            {#if accountHolderName}
                <div class="detail-copyable" data-testid="bank-transfer-account-holder">
                    <div class="detail-label">{$text('settings.billing.bank_transfer_account_holder')}</div>
                    <div class="detail-value-row">
                        <span class="detail-value selectable">{accountHolderName}</span>
                        <button
                            class="copy-icon-btn"
                            class:copied={copiedField === 'holder'}
                            onclick={() => handleCopy('holder', accountHolderName)}
                            title={copiedField === 'holder' ? $text('settings.billing.copied') : $text('settings.billing.copy')}
                            aria-label={$text('settings.billing.copy')}
                            data-testid="copy-account-holder-btn"
                        ><span class="copy-icon-inner"></span></button>
                    </div>
                </div>
            {/if}

            <!-- Bank Name -->
            {#if bankName}
                <div class="detail-copyable">
                    <div class="detail-label">{$text('settings.billing.bank_transfer_bank_name')}</div>
                    <div class="detail-value-row">
                        <span class="detail-value selectable">{bankName}</span>
                    </div>
                </div>
            {/if}

            <!-- IBAN -->
            <div class="detail-copyable" data-testid="bank-transfer-iban">
                <div class="detail-label">{$text('settings.billing.bank_transfer_iban')}</div>
                <div class="detail-value-row">
                    <span class="detail-value selectable monospace">{iban}</span>
                    <button
                        class="copy-icon-btn"
                        class:copied={copiedField === 'iban'}
                        onclick={() => handleCopy('iban', iban)}
                        title={copiedField === 'iban' ? $text('settings.billing.copied') : $text('settings.billing.copy')}
                        aria-label={$text('settings.billing.copy')}
                        data-testid="copy-iban-btn"
                    ><span class="copy-icon-inner"></span></button>
                </div>
            </div>

            <!-- BIC -->
            <div class="detail-copyable" data-testid="bank-transfer-bic">
                <div class="detail-label">{$text('settings.billing.bank_transfer_bic')}</div>
                <div class="detail-value-row">
                    <span class="detail-value selectable monospace">{bic}</span>
                    <button
                        class="copy-icon-btn"
                        class:copied={copiedField === 'bic'}
                        onclick={() => handleCopy('bic', bic)}
                        title={copiedField === 'bic' ? $text('settings.billing.copied') : $text('settings.billing.copy')}
                        aria-label={$text('settings.billing.copy')}
                        data-testid="copy-bic-btn"
                    ><span class="copy-icon-inner"></span></button>
                </div>
            </div>

            <!-- Amount -->
            <div class="detail-copyable" data-testid="bank-transfer-amount">
                <div class="detail-label">{$text('settings.billing.bank_transfer_amount')}</div>
                <div class="detail-value-row">
                    <span class="detail-value selectable monospace">{amountEur} EUR</span>
                    <button
                        class="copy-icon-btn"
                        class:copied={copiedField === 'amount'}
                        onclick={() => handleCopy('amount', amountEur)}
                        title={copiedField === 'amount' ? $text('settings.billing.copied') : $text('settings.billing.copy')}
                        aria-label={$text('settings.billing.copy')}
                        data-testid="copy-amount-btn"
                    ><span class="copy-icon-inner"></span></button>
                </div>
            </div>

            <!-- Reference — highlighted; required for credit purchases, optional for support contributions -->
            <div class="detail-copyable reference-row" data-testid="bank-transfer-reference">
                <div class="detail-label">{isSupportContribution ? $text('settings.billing.bank_transfer_reference_support') : $text('settings.billing.bank_transfer_reference')}</div>
                <div class="detail-value-row">
                    <span class="detail-value selectable monospace reference-value">{reference}</span>
                    <button
                        class="copy-icon-btn"
                        class:copied={copiedField === 'reference'}
                        onclick={() => handleCopy('reference', reference)}
                        title={copiedField === 'reference' ? $text('settings.billing.copied') : $text('settings.billing.copy')}
                        aria-label={$text('settings.billing.copy_reference')}
                        data-testid="copy-reference-btn"
                    ><span class="copy-icon-inner"></span></button>
                </div>
            </div>

            <!-- Deadline — only shown for credit purchases (support contributions have no meaningful deadline to surface) -->
            {#if !isSupportContribution}
                <div class="detail-copyable">
                    <div class="detail-label">{$text('settings.billing.bank_transfer_deadline')}</div>
                    <div class="detail-value-row">
                        <span class="detail-value selectable">{formatExpiryDate(expiresAt)}</span>
                    </div>
                </div>
            {/if}
        </SettingsCard>

        <!-- Reference hint — different text for support vs credit purchase -->
        <div class="reference-hint-container" data-testid="reference-warning">
            <SettingsInfoBox type="info">
                {#if isSupportContribution}
                    {$text('settings.billing.bank_transfer_reference_hint_support')}
                {:else}
                    {$text('settings.billing.bank_transfer_reference_warning')}
                {/if}
            </SettingsInfoBox>
        </div>

        <!-- Awaiting status — different text for support contributions (no credits) -->
        <div class="awaiting-row" data-testid="bank-transfer-awaiting">
            <span class="pulse-dot"></span>
            <span class="color-grey-60">{isSupportContribution ? $text('settings.billing.bank_transfer_awaiting_support') : $text('settings.billing.bank_transfer_awaiting')}</span>
        </div>

        <!-- Continue to app button (signup flow only) -->
        {#if allowContinueWithoutPayment}
            <div class="continue-section" data-testid="bank-transfer-continue-section">
                <button
                    class="continue-btn"
                    onclick={() => dispatch('paymentStateChange', { state: 'bank_transfer_pending', provider: 'bank_transfer', order_id: orderId })}
                    data-testid="bank-transfer-continue-btn"
                >
                    {$text('settings.billing.bank_transfer_continue_to_app')}
                </button>
                <p class="continue-hint color-grey-40">
                    {$text('settings.billing.bank_transfer_continue_hint')}
                </p>
            </div>
        {/if}
    </div>
{/if}

<style>
    .bt-loading,
    .bt-error,
    .bt-completed {
        padding: 1rem 0.625rem;
        display: flex;
        flex-direction: column;
        gap: 0.75rem;
    }

    .retry-link {
        background: none;
        border: none;
        color: var(--color-primary-start);
        cursor: pointer;
        font-size: var(--font-size-p, 0.875rem);
        padding: 0;
        text-decoration: underline;
    }

    .bt-details {
        display: flex;
        flex-direction: column;
        gap: 0.5rem;
    }

    /* ── Detail row (inside SettingsCard) ──────────────────────── */
    .detail-copyable {
        display: flex;
        flex-direction: column;
        gap: 0.25rem;
        padding: 0.625rem 0;
        border-bottom: 0.0625rem solid var(--color-grey-20);
    }

    .detail-copyable:last-child {
        border-bottom: none;
    }

    .detail-label {
        font-size: var(--font-size-small, 0.75rem);
        color: var(--color-font-secondary);
        text-transform: uppercase;
        letter-spacing: 0.03em;
    }

    .detail-value-row {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 0.5rem;
    }

    .detail-value {
        font-size: var(--font-size-p, 0.875rem);
        font-weight: 500;
        color: var(--color-font-primary);
    }

    .detail-value.selectable {
        user-select: text;
        -webkit-user-select: text;
    }

    .detail-value.monospace {
        font-family: 'SF Mono', 'Monaco', 'Inconsolata', 'Menlo', monospace;
        font-size: 0.8125rem;
    }

    .reference-row .detail-value {
        color: var(--color-primary-start);
        font-size: 0.9rem;
        font-weight: 600;
    }

    /* ── Copy icon button ─────────────────────────────────────── */
    .copy-icon-btn {
        flex-shrink: 0;
        width: 1.75rem;
        height: 1.75rem;
        display: flex;
        align-items: center;
        justify-content: center;
        background: var(--color-grey-20);
        border: none;
        border-radius: 0.375rem;
        cursor: pointer;
        transition: background var(--duration-normal, 0.15s) ease;
    }

    .copy-icon-btn:hover {
        background: var(--color-grey-30);
    }

    .copy-icon-inner {
        display: block;
        width: 1rem;
        height: 1rem;
        background: var(--color-font-secondary);
        -webkit-mask-image: var(--icon-url-copy, var(--icon-url-duplicate));
        mask-image: var(--icon-url-copy, var(--icon-url-duplicate));
        -webkit-mask-size: contain;
        mask-size: contain;
        -webkit-mask-repeat: no-repeat;
        mask-repeat: no-repeat;
        -webkit-mask-position: center;
        mask-position: center;
        transition: background var(--duration-normal, 0.15s) ease;
    }

    .copy-icon-btn.copied .copy-icon-inner {
        -webkit-mask-image: var(--icon-url-check);
        mask-image: var(--icon-url-check);
        background: var(--color-success);
    }

    /* ── Reference hint ──────────────────────────────────────────── */
    .reference-hint-container {
        margin: 0.25rem 0;
    }

    /* ── Awaiting status ─────────────────────────────────────────── */
    .awaiting-row {
        display: flex;
        align-items: center;
        gap: 0.5rem;
        padding: 0.5rem 0.625rem;
        font-size: var(--font-size-small, 0.75rem);
    }

    .pulse-dot {
        width: 0.5rem;
        height: 0.5rem;
        border-radius: 50%;
        background: var(--color-primary-start);
        animation: pulse 2s ease-in-out infinite;
        flex-shrink: 0;
    }

    @keyframes pulse {
        0%, 100% { opacity: 1; }
        50% { opacity: 0.3; }
    }

    /* ── Continue to app (signup) ────────────────────────────────── */
    .continue-section {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 0.5rem;
        padding: 1rem 0.625rem 0.5rem;
        border-top: 0.0625rem solid var(--color-grey-20);
        margin-top: 0.25rem;
    }

    .continue-btn {
        width: 100%;
        padding: 0.75rem 1rem;
        background: var(--color-primary-start);
        color: #fff;
        border: none;
        border-radius: 0.75rem;
        font-size: var(--font-size-p, 0.875rem);
        font-weight: 600;
        cursor: pointer;
        transition: opacity 0.15s ease;
    }

    .continue-btn:hover { opacity: 0.9; }

    .continue-hint {
        font-size: var(--font-size-small, 0.75rem);
        text-align: center;
        margin: 0;
        line-height: 1.4;
    }
</style>
