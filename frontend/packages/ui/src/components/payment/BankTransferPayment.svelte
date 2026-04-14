<!--
  BankTransferPayment.svelte

  Displays company bank details (IBAN, BIC) and a structured reference
  for the user to include in their SEPA bank transfer. Polls for transfer
  status and listens for WebSocket payment_completed events.

  Used in both the settings billing flow and signup flow.
-->
<script lang="ts">
    import { text } from '@repo/ui';
    import { fade } from 'svelte/transition';
    import { onMount, onDestroy, createEventDispatcher } from 'svelte';
    import { copyToClipboard } from '../../utils/clipboardUtils';
    import { apiEndpoints, getApiEndpoint } from '../../config/api';
    import { webSocketService } from '../../services/websocketService';

    const dispatch = createEventDispatcher();

    let {
        credits_amount,
        price,
        currency = 'EUR',
        isSupportContribution = false,
        supportEmail = '',
        emailEncryptionKey = '',
        allowContinueWithoutPayment = false, // signup flow: show "Continue to app" button
        isSignup = false,                    // signup flow: include is_signup in order request
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

    // Component state
    let state: 'loading' | 'awaiting_transfer' | 'completed' | 'error' = $state('loading');
    let errorMessage: string = $state('');

    // Order data from the backend
    let orderId: string = $state('');
    let reference: string = $state('');
    let iban: string = $state('');
    let bic: string = $state('');
    let bankName: string = $state('');
    let accountHolderName: string = $state('');
    let amountEur: string = $state('');
    let expiresAt: string = $state('');

    // Copy feedback state
    let copiedField: string = $state('');
    let copyTimeout: ReturnType<typeof setTimeout> | null = null;

    // Polling interval
    let pollInterval: ReturnType<typeof setInterval> | null = null;

    onMount(async () => {
        await createOrder();
    });

    onDestroy(() => {
        if (pollInterval) clearInterval(pollInterval);
        if (copyTimeout) clearTimeout(copyTimeout);
        // Unregister WebSocket handler
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

            // Start polling for status updates every 30 seconds
            pollInterval = setInterval(pollStatus, 30_000);

            // Listen for WebSocket payment_completed event for instant notification
            webSocketService.on('payment_completed', handlePaymentCompleted);

            // Dispatch event so parent knows the order was created
            dispatch('orderCreated', { orderId, reference });

        } catch (err: unknown) {
            state = 'error';
            errorMessage = err instanceof Error ? err.message : 'Failed to create bank transfer order.';
        }
    }

    async function pollStatus() {
        if (!orderId || state !== 'awaiting_transfer') return;

        try {
            const response = await fetch(
                `${getApiEndpoint(apiEndpoints.payments.bankTransferStatus)}/${orderId}`,
                { credentials: 'include' }
            );
            if (!response.ok) return;

            const data = await response.json();
            if (data.status === 'completed') {
                handleCompleted();
            }
        } catch {
            // Silently ignore poll errors — next poll will retry
        }
    }

    function handlePaymentCompleted(payload: { order_id?: string }) {
        if (payload?.order_id === orderId) {
            handleCompleted();
        }
    }

    function handleCompleted() {
        state = 'completed';
        if (pollInterval) clearInterval(pollInterval);
        dispatch('paymentStateChange', {
            state: 'success',
            provider: 'bank_transfer',
            payment_intent_id: orderId,
        });
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
            const date = new Date(iso);
            return date.toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric' });
        } catch {
            return iso;
        }
    }
</script>

{#if state === 'loading'}
    <div class="bank-transfer-loading" in:fade={{ duration: 200 }}>
        <p>{$text('common.loading')}</p>
    </div>

{:else if state === 'error'}
    <div class="bank-transfer-error" in:fade={{ duration: 200 }}>
        <p class="error-text">{errorMessage}</p>
        <button class="retry-btn" onclick={createOrder}>
            {$text('common.try_again')}
        </button>
    </div>

{:else if state === 'completed'}
    <div class="bank-transfer-success" in:fade={{ duration: 300 }}>
        <span class="check-icon"></span>
        <p class="success-text">{$text('settings.billing.bank_transfer_received')}</p>
        <p class="confirmation-text color-grey-60">
            {$text('signup.you_will_receive_confirmation_soon')}
        </p>
    </div>

{:else}
    <div class="bank-transfer-details" in:fade={{ duration: 200 }} data-testid="bank-transfer-details">
        <h3 class="details-heading">{$text('settings.billing.bank_transfer_details')}</h3>

        {#if accountHolderName}
            <div class="detail-row" data-testid="bank-transfer-account-holder">
                <span class="detail-label">{$text('settings.billing.bank_transfer_account_holder')}</span>
                <div class="detail-value-row">
                    <span class="detail-value">{accountHolderName}</span>
                    <button
                        class="copy-btn"
                        onclick={() => handleCopy('holder', accountHolderName)}
                        data-testid="copy-account-holder-btn"
                    >
                        {copiedField === 'holder' ? $text('settings.billing.copied') : $text('settings.billing.copy')}
                    </button>
                </div>
            </div>
        {/if}

        <div class="detail-row" data-testid="bank-transfer-iban">
            <span class="detail-label">{$text('settings.billing.bank_transfer_iban')}</span>
            <div class="detail-value-row">
                <span class="detail-value monospace">{iban}</span>
                <button
                    class="copy-btn"
                    onclick={() => handleCopy('iban', iban)}
                    data-testid="copy-iban-btn"
                >
                    {copiedField === 'iban' ? $text('settings.billing.copied') : $text('settings.billing.copy')}
                </button>
            </div>
        </div>

        <div class="detail-row" data-testid="bank-transfer-bic">
            <span class="detail-label">{$text('settings.billing.bank_transfer_bic')}</span>
            <div class="detail-value-row">
                <span class="detail-value monospace">{bic}</span>
                <button
                    class="copy-btn"
                    onclick={() => handleCopy('bic', bic)}
                    data-testid="copy-bic-btn"
                >
                    {copiedField === 'bic' ? $text('settings.billing.copied') : $text('settings.billing.copy')}
                </button>
            </div>
        </div>

        <div class="detail-row" data-testid="bank-transfer-amount">
            <span class="detail-label">{$text('settings.billing.bank_transfer_amount')}</span>
            <div class="detail-value-row">
                <span class="detail-value monospace">{amountEur} EUR</span>
                <button
                    class="copy-btn"
                    onclick={() => handleCopy('amount', amountEur)}
                    data-testid="copy-amount-btn"
                >
                    {copiedField === 'amount' ? $text('settings.billing.copied') : $text('settings.billing.copy')}
                </button>
            </div>
        </div>

        <div class="detail-row reference-row" data-testid="bank-transfer-reference">
            <span class="detail-label">{$text('settings.billing.bank_transfer_reference')}</span>
            <div class="detail-value-row">
                <span class="detail-value monospace reference-value">{reference}</span>
                <button
                    class="copy-btn"
                    onclick={() => handleCopy('reference', reference)}
                    data-testid="copy-reference-btn"
                >
                    {copiedField === 'reference' ? $text('settings.billing.copied') : $text('settings.billing.copy_reference')}
                </button>
            </div>
        </div>

        <p class="reference-warning" data-testid="reference-warning">
            {$text('settings.billing.bank_transfer_reference_warning')}
        </p>

        {#if bankName}
            <div class="detail-row">
                <span class="detail-label">{$text('settings.billing.bank_transfer_bank_name')}</span>
                <span class="detail-value">{bankName}</span>
            </div>
        {/if}

        <div class="detail-row">
            <span class="detail-label">{$text('settings.billing.bank_transfer_deadline')}</span>
            <span class="detail-value">{formatExpiryDate(expiresAt)}</span>
        </div>

        {#if !isSupportContribution && credits_amount > 0}
            <p class="credits-info color-grey-40">
                {$text('settings.billing.bank_transfer_credits_info', { credits: credits_amount.toLocaleString('de-DE') })}
            </p>
        {/if}

        <div class="awaiting-status" data-testid="bank-transfer-awaiting">
            <div class="pulse-dot"></div>
            <span class="awaiting-text">{$text('settings.billing.bank_transfer_awaiting')}</span>
        </div>

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
    .bank-transfer-loading,
    .bank-transfer-error,
    .bank-transfer-success {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        padding: 40px 20px;
        gap: 16px;
        text-align: center;
    }

    .bank-transfer-details {
        display: flex;
        flex-direction: column;
        gap: 12px;
        padding: 16px 0;
    }

    .details-heading {
        font-size: var(--ds-font-size-m);
        font-weight: 600;
        color: var(--ds-color-text-primary);
        margin: 0 0 8px 0;
    }

    .detail-row {
        display: flex;
        flex-direction: column;
        gap: 4px;
    }

    .detail-label {
        font-size: var(--ds-font-size-xs);
        color: var(--ds-color-text-secondary);
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }

    .detail-value-row {
        display: flex;
        align-items: center;
        gap: 8px;
    }

    .detail-value {
        font-size: var(--ds-font-size-s);
        color: var(--ds-color-text-primary);
    }

    .detail-value.monospace {
        font-family: var(--ds-font-mono, monospace);
        letter-spacing: 0.5px;
    }

    .reference-value {
        font-weight: 600;
        color: var(--ds-color-text-accent);
    }

    .reference-warning {
        font-size: var(--ds-font-size-xs);
        color: var(--ds-color-text-warning);
        background: var(--ds-color-bg-warning);
        padding: 8px 12px;
        border-radius: var(--ds-radius-s);
        margin: 4px 0;
    }

    .copy-btn {
        font-size: var(--ds-font-size-xs);
        color: var(--ds-color-text-accent);
        background: none;
        border: 1px solid var(--ds-color-border-accent);
        border-radius: var(--ds-radius-s);
        padding: 2px 8px;
        cursor: pointer;
        white-space: nowrap;
        transition: background-color 0.15s ease;
    }

    .copy-btn:hover {
        background: var(--ds-color-bg-hover);
    }

    .credits-info {
        font-size: var(--ds-font-size-xs);
        margin: 4px 0;
    }

    .awaiting-status {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 12px 16px;
        background: var(--ds-color-bg-secondary);
        border-radius: var(--ds-radius-m);
        margin-top: 8px;
    }

    .pulse-dot {
        width: 8px;
        height: 8px;
        border-radius: 50%;
        background: var(--ds-color-text-accent);
        animation: pulse 2s ease-in-out infinite;
    }

    @keyframes pulse {
        0%, 100% { opacity: 1; }
        50% { opacity: 0.3; }
    }

    .awaiting-text {
        font-size: var(--ds-font-size-s);
        color: var(--ds-color-text-secondary);
    }

    .continue-section {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 8px;
        margin-top: 8px;
        padding-top: 16px;
        border-top: 1px solid var(--ds-color-border-subtle);
    }

    .continue-btn {
        width: 100%;
        padding: 12px 20px;
        background: var(--ds-color-bg-accent);
        color: var(--ds-color-text-on-accent);
        border: none;
        border-radius: var(--ds-radius-m);
        font-size: var(--ds-font-size-m);
        font-weight: 600;
        cursor: pointer;
        transition: opacity 0.15s ease;
    }

    .continue-btn:hover {
        opacity: 0.9;
    }

    .continue-hint {
        font-size: var(--ds-font-size-xs);
        text-align: center;
        margin: 0;
        line-height: 1.4;
    }

    .error-text {
        color: var(--ds-color-text-error);
    }

    .retry-btn {
        padding: 8px 16px;
        background: var(--ds-color-bg-accent);
        color: var(--ds-color-text-on-accent);
        border: none;
        border-radius: var(--ds-radius-m);
        cursor: pointer;
    }

    .check-icon {
        display: inline-block;
        width: 48px;
        height: 48px;
        border-radius: 50%;
        background: var(--ds-color-bg-success);
    }

    .success-text {
        font-size: var(--ds-font-size-m);
        font-weight: 600;
        color: var(--ds-color-text-primary);
    }

    .confirmation-text {
        font-size: var(--ds-font-size-s);
    }
</style>
