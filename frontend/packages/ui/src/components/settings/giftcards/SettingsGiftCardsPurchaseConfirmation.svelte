<!--
Gift Card Purchase Confirmation - Success screen after purchasing a gift card
Shows the gift card code and allows downloading it as a text file
-->

<script lang="ts">
    import { createEventDispatcher, onMount, onDestroy } from 'svelte';
    import { text } from '@repo/ui';
    import { webSocketService } from '../../../services/websocketService';
    import { copyToClipboard as clipboardCopy } from '../../../utils/clipboardUtils';

    const dispatch = createEventDispatcher();

    let giftCardCode: string | null = $state(null);
    let creditsValue: number = $state(0);
    let isDelayedPayment = $state(false);
    let hasAutoDownloaded = $state(false); // Track if auto-download has been triggered

    // Listen for gift card created event (in case we navigated here before receiving it)
    function handleGiftCardCreated(payload: { order_id: string, gift_card_code: string, credits_value: number }) {
        
        giftCardCode = payload.gift_card_code;
        creditsValue = payload.credits_value;
        isDelayedPayment = false; // Clear delayed payment flag when gift card is received
        // Auto-download the gift card code when received
        if (!hasAutoDownloaded) {
            // Use a small delay to ensure the UI has updated
            setTimeout(() => {
                downloadGiftCardCode();
                hasAutoDownloaded = true;
            }, 500);
        }
    }

    // Format credits with dots as thousand separators
    function formatCredits(credits: number): string {
        return credits.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ".");
    }

    // Download gift card code as text file
    function downloadGiftCardCode() {
        if (!giftCardCode) return;

        const content = `OpenMates Gift Card

Gift Card Code: ${giftCardCode}
Credits: ${formatCredits(creditsValue)}

Instructions:
1. Go to Settings > Gift Cards > Redeem
2. Enter the gift card code above
3. The credits will be added to your account

This gift card can only be used once.
`;

        const blob = new Blob([content], { type: 'text/plain' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `gift-card-${giftCardCode}.txt`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    }

    // Copy gift card code to clipboard
    async function copyToClipboard() {
        if (!giftCardCode) return;

        try {
            const result = await clipboardCopy(giftCardCode);
            if (!result.success) throw new Error(result.error || 'Copy failed');
            // Show success feedback
            alert($text('settings.gift_cards.code_copied'));
        } catch (err) {
            console.error('Failed to copy to clipboard:', err);
        }
    }

    // Navigate back to gift cards main
    function goBackToGiftCards() {
        dispatch('openSettings', {
            settingsPath: 'billing/gift-cards',
            direction: 'backward',
            icon: 'coins',
            title: $text('common.gift_cards')
        });
    }

    onMount(() => {
        // Listen for gift card created events (in case payment completed after navigation)
        webSocketService.on('gift_card_created', handleGiftCardCreated);

        // Try to get gift card code from sessionStorage (set by payment component)
        const storedCode = sessionStorage.getItem('gift_card_code');
        const storedCredits = sessionStorage.getItem('gift_card_credits');
        const storedIsDelayed = sessionStorage.getItem('gift_card_delayed');
        
        if (storedCode) {
            giftCardCode = storedCode;
            creditsValue = storedCredits ? parseInt(storedCredits, 10) : 0;
            isDelayedPayment = storedIsDelayed === 'true';
            // Clear sessionStorage after reading
            sessionStorage.removeItem('gift_card_code');
            sessionStorage.removeItem('gift_card_credits');
            sessionStorage.removeItem('gift_card_delayed');
            // Auto-download the gift card code when loaded from sessionStorage
            if (!hasAutoDownloaded) {
                // Use a small delay to ensure the UI has updated
                setTimeout(() => {
                    downloadGiftCardCode();
                    hasAutoDownloaded = true;
                }, 500);
            }
        } else {
            // No gift card code yet - check if this is a delayed payment
            // (navigated here after 20 second timeout)
            const urlParams = new URLSearchParams(window.location.search);
            isDelayedPayment = urlParams.get('delayed') === 'true';
        }
    });

    onDestroy(() => {
        webSocketService.off('gift_card_created', handleGiftCardCreated);
    });
</script>

{#if giftCardCode}
    <!-- Success Icon and Message -->
    <div class="success-section">
        <div class="ds-success-icon-wrapper">
            <div class="success-icon"></div>
        </div>
        <h2 class="ds-success-title">{$text('settings.gift_cards.purchase_successful')}</h2>
        <p class="success-subtitle">{$text('settings.gift_cards.purchase_successful_subtitle')}</p>
    </div>

    <!-- Gift Card Code Display -->
    <div class="gift-card-code-section">
        <div class="code-label">{$text('settings.gift_cards.code')}</div>
        <div class="code-display">
            <span class="code-text">{giftCardCode}</span>
        </div>
        <button class="copy-button" onclick={copyToClipboard} title={$text('settings.gift_cards.copy')} aria-label={$text('settings.gift_cards.copy')}>
            <div class="copy-icon"></div>
        </button>
        <div class="credits-info">
            {formatCredits(creditsValue)} {$text('common.credits')}
        </div>
    </div>

    <!-- Action Buttons -->
    <div class="action-section">
        <button class="download-button" onclick={downloadGiftCardCode}>
            {$text('settings.gift_cards.download')}
        </button>
        <button class="done-button" onclick={goBackToGiftCards} aria-label={$text('common.done')}>
            {$text('common.done')}
        </button>
    </div>
{:else}
    <!-- Loading state while waiting for gift card code -->
    <div class="loading-section">
        {#if isDelayedPayment}
            <div class="delayed-message">
                <p class="delayed-title">{$text('settings.gift_cards.purchase_successful')}</p>
                <p class="delayed-subtitle">{$text('signup.payment_processing_delayed')}</p>
                <p class="delayed-info">{$text('signup.you_will_receive_confirmation_soon')}</p>
            </div>
        {:else}
            <div class="loading-message">{$text('settings.gift_cards.processing')}</div>
        {/if}
    </div>
{/if}

<style>
    /* Success Section */
    .success-section {
        display: flex;
        flex-direction: column;
        align-items: center;
        text-align: center;
        gap: var(--spacing-6);
        padding: 20px 0;
    }

    /* Base styles for .ds-success-icon-wrapper / .ds-success-title are generated
       from frontend/packages/ui/src/tokens/sources/components/status-feedback.yml
       See docs/architecture/frontend/design-tokens.md (Phase E). */

    .success-icon {
        width: 40px;
        height: 40px;
        background-image: url('@openmates/ui/static/icons/check.svg');
        background-size: contain;
        background-repeat: no-repeat;
        background-position: center;
        filter: invert(1);
    }

    .success-subtitle {
        font-size: var(--font-size-small);
        color: var(--color-grey-60);
        margin: 0;
    }

    /* Gift Card Code Section */
    .gift-card-code-section {
        padding: var(--spacing-10);
        background: var(--color-grey-10);
        border-radius: var(--radius-5);
        margin: 20px 0;
        text-align: center;
    }

    .code-label {
        font-size: var(--font-size-small);
        color: var(--color-grey-60);
        margin-bottom: var(--spacing-6);
    }

    .code-display {
        display: flex;
        align-items: center;
        justify-content: center;
        margin-bottom: var(--spacing-6);
    }

    .code-text {
        font-size: var(--font-size-h2-mobile);
        font-weight: 700;
        font-family: 'Courier New', monospace;
        letter-spacing: 2px;
        color: var(--color-grey-100);
    }

    .copy-button {
        background: var(--color-primary);
        border: none;
        border-radius: var(--radius-3);
        width: 40px;
        height: 40px;
        display: flex;
        align-items: center;
        justify-content: center;
        cursor: pointer;
        transition: opacity var(--duration-normal);
        margin: 0 auto 12px auto;
    }

    .copy-button:hover {
        opacity: 0.9;
    }

    .copy-icon {
        width: 20px;
        height: 20px;
        background-image: url('@openmates/ui/static/icons/copy.svg');
        background-size: contain;
        background-repeat: no-repeat;
        filter: invert(1);
    }

    .credits-info {
        font-size: var(--font-size-p);
        color: var(--color-grey-80);
        font-weight: 500;
    }

    /* Action Section */
    .action-section {
        display: flex;
        flex-direction: column;
        gap: var(--spacing-6);
        padding: 20px 0;
    }

    .download-button,
    .done-button {
        width: 100%;
        padding: 14px;
        border: none;
        border-radius: var(--radius-3);
        font-size: var(--font-size-p);
        font-weight: 600;
        cursor: pointer;
        transition: opacity var(--duration-normal);
    }

    .download-button {
        background: var(--color-primary);
        color: white;
    }

    .download-button:hover {
        opacity: 0.9;
    }

    .done-button {
        background: var(--color-grey-20);
        color: var(--color-grey-100);
    }

    .done-button:hover {
        opacity: 0.9;
    }

    /* Loading Section */
    .loading-section {
        padding: var(--spacing-20) var(--spacing-10);
        text-align: center;
    }

    .loading-message {
        color: var(--color-grey-60);
        font-size: var(--font-size-p);
    }

    .delayed-message {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: var(--spacing-6);
        text-align: center;
    }

    .delayed-title {
        font-size: var(--font-size-h3);
        font-weight: 600;
        color: var(--color-grey-100);
        margin: 0;
    }

    .delayed-subtitle {
        font-size: var(--font-size-small);
        color: var(--color-grey-60);
        margin: 0;
    }

    .delayed-info {
        font-size: var(--font-size-small);
        color: var(--color-grey-60);
        margin: 0;
        margin-top: var(--spacing-4);
    }
</style>
