<script lang="ts">
    import { text } from '@repo/ui';
    import { fade } from 'svelte/transition';

    
    // Props using Svelte 5 runes
    let { 
        state = 'processing',
        isGift = false,
        isGiftCard = false,
        showDelayedMessage = false,
        // provider: 'stripe' | 'polar' — controls post-purchase confirmation text.
        // Polar uses "Payment Confirmation" (MoR model), Stripe uses "Invoice".
        provider = 'stripe',
        // compact: when true, uses a smaller layout for embedded contexts (e.g., settings panel)
        compact = false
    }: {
        state?: 'processing' | 'success';
        isGift?: boolean;
        isGiftCard?: boolean;
        showDelayedMessage?: boolean;
        provider?: string;
        compact?: boolean;
    } = $props();
</script>

{#if state === 'processing'}
    <div class="payment-processing" class:compact in:fade={{ duration: 300 }}>
        <div class="center-container">
            <span class="clickable-icon icon_billing large-icon"></span>
            {#if showDelayedMessage}
                <!-- eslint-disable-next-line svelte/no-at-html-tags -->
                <p class="processing-text color-grey-60">{@html $text('signup.processing_payment')}</p>
                <!-- eslint-disable-next-line svelte/no-at-html-tags -->
                <p class="processing-subtext color-grey-40">{@html $text('signup.payment_processing_delayed')}</p>
            {:else}
                <!-- eslint-disable-next-line svelte/no-at-html-tags -->
                <p class="processing-text color-grey-60">{@html $text('signup.processing_payment')}</p>
            {/if}
            <!-- Animated shimmer bar indicating progress -->
            <div class="shimmer-bar">
                <div class="shimmer-fill"></div>
            </div>
            <!-- "Powered by" subtitle below shimmer — replaces old bottom-container button -->
            <p class="powered-by-text color-grey-40">
                Powered by {provider === 'polar' ? 'Polar' : 'Stripe'}
            </p>
        </div>
    </div>
{:else}
    <div class="payment-success" in:fade={{ duration: 300 }}>
        <div class="center-container">
            <span class="check-icon"></span>
            <!-- Conditional success text -->
            <p class="success-text color-grey-60">
                <!-- eslint-disable-next-line svelte/no-at-html-tags -->
                {@html $text(isGift ? 'signup.enjoy_your_gift' : 'signup.purchase_successful')}
            </p>
            <!-- Only show confirmation email text for actual purchases.
                 Polar sends a "Payment Confirmation" (not Invoice) per MoR rules. -->
            {#if !isGift}
                <p class="confirmation-text color-grey-60">
                    <!-- eslint-disable-next-line svelte/no-at-html-tags -->
                    {@html $text(provider === 'polar'
                        ? 'signup.you_will_receive_payment_confirmation_soon'
                        : 'signup.you_will_receive_confirmation_soon')}
                </p>
            {/if}
        </div>
        
        {#if !isGift && !isGiftCard}
            <div class="bottom-container">
                <!-- eslint-disable-next-line svelte/no-at-html-tags -->
                <p class="loading-text color-grey-60">{@html $text('common.loading')}</p>
            </div>
        {/if}
    </div>
{/if}

<style>
    .payment-processing,
    .payment-success {
        width: 100%;
        height: calc(100% - 15px);
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
    }
    
    /* Center container for icons and main text — uses flexbox centering (no absolute positioning) */
    .center-container {
        display: flex;
        flex-direction: column;
        align-items: center;
        text-align: center;
        width: 100%;
        max-width: 320px;
        padding: 0 20px;
    }
    
    
    /* Large billing icon for processing state */
    .large-icon {
        width: 73px !important;
        height: 73px !important;
        position: static !important;
        transform: none !important;
        margin-bottom: var(--spacing-10);
    }

    /* Compact mode: smaller icon and tighter spacing for settings panel */
    .compact .large-icon {
        width: 56px !important;
        height: 56px !important;
        margin-bottom: 14px;
    }
    
    /* Success check icon */
    .check-icon {
        width: 70px;
        height: 70px;
        -webkit-mask: url('@openmates/ui/static/icons/check.svg') no-repeat center;
        mask: url('@openmates/ui/static/icons/check.svg') no-repeat center;
        -webkit-mask-size: contain;
        mask-size: contain;
        background-color: #58BC00;
        margin-bottom: var(--spacing-10);
    }
    
    /* Text spacing */
    .processing-text {
        margin-bottom: var(--spacing-3);
        font-size: null;
    }

    .processing-subtext {
        margin-bottom: var(--spacing-5);
        font-size: var(--font-size-xs);
    }
    
    .success-text {
        margin-bottom: var(--spacing-5);
    }
    
    .confirmation-text {
        margin-bottom: var(--spacing-20);
    }
    
    .loading-text {
        text-align: center;
    }

    /* Gradient shimmer bar — left-to-right animated progress indicator */
    .shimmer-bar {
        width: 100%;
        height: 4px;
        background: var(--color-grey-15, #e5e5e5);
        border-radius: 2px;
        overflow: hidden;
        margin-top: var(--spacing-8);
        margin-bottom: var(--spacing-6);
    }

    .compact .shimmer-bar {
        margin-top: var(--spacing-6);
        margin-bottom: var(--spacing-5);
    }

    .shimmer-fill {
        width: 40%;
        height: 100%;
        background: linear-gradient(90deg, transparent, var(--color-primary, #6366f1), transparent);
        border-radius: 2px;
        animation: shimmer-slide 1.5s ease-in-out infinite;
    }

    @keyframes shimmer-slide {
        0% { transform: translateX(-100%); }
        100% { transform: translateX(350%); }
    }

    /* "Powered by" text — replaces the old clickable button in bottom-container */
    .powered-by-text {
        font-size: var(--font-size-xxs);
        margin: 0;
    }
    
    /* Ensure icons in processing state are not clickable */
    .payment-processing .clickable-icon {
        cursor: default; 
    }
    
    .clickable-icon {
        position: absolute;
        left: 15px;
        top: 50%;
        transform: translateY(-50%);
        width: 20px;
        height: 20px;
        background-size: contain;
        background-position: center;
        background-repeat: no-repeat;
        opacity: 0.6;
        z-index: var(--z-index-raised);
    }
    
</style>
