<script lang="ts">
    import { text } from '@repo/ui';
    import { fade } from 'svelte/transition';
    import { getWebsiteUrl, routes } from '../../config/links';
    import { createEventDispatcher } from 'svelte';
    
    const dispatch = createEventDispatcher();
    
    // Props using Svelte 5 runes
    let { 
        state = 'processing',
        isGift = false,
        isGiftCard = false,
        showDelayedMessage = false
    }: {
        state?: 'processing' | 'success';
        isGift?: boolean;
        isGiftCard?: boolean;
        showDelayedMessage?: boolean;
    } = $props();
    
    function handleSecurePaymentInfoClick() {
        window.open(getWebsiteUrl(routes.docs.userGuide_signup_10_2), '_blank');
    }
</script>

{#if state === 'processing'}
    <div class="payment-processing" in:fade={{ duration: 300 }}>
        <div class="center-container">
            <span class="clickable-icon icon_billing large-icon"></span>
            {#if showDelayedMessage}
                <p class="processing-text color-grey-60">{@html $text('signup.payment_processing_delayed')}</p>
            {:else}
                <p class="processing-text color-grey-60">{@html $text('signup.processing_payment')}</p>
            {/if}
        </div>
        
        <div class="bottom-container">
            <button type="button" class="text-button" onclick={handleSecurePaymentInfoClick}>
                <span class="clickable-icon icon_lock inline-lock-icon"></span>
                {@html $text('signup.secured_and_powered_by').replace('{provider}', 'Revolut')}
            </button>
        </div>
    </div>
{:else}
    <div class="payment-success" in:fade={{ duration: 300 }}>
        <div class="center-container">
            <span class="check-icon"></span>
            <!-- Conditional success text -->
            <p class="success-text color-grey-60">
                {@html $text(isGift ? 'signup.enjoy_your_gift' : 'signup.purchase_successful')}
            </p>
            <!-- Only show confirmation email text for actual purchases -->
            {#if !isGift}
                <p class="confirmation-text color-grey-60">{@html $text('signup.you_will_receive_confirmation_soon')}</p>
            {/if}
        </div>
        
        {#if !isGift && !isGiftCard}
            <div class="bottom-container">
                <p class="loading-text color-grey-60">{@html $text('login.loading')}</p>
            </div>
        {/if}
    </div>
{/if}

<style>
    .payment-processing,
    .payment-success {
        width: 100%;
        height: calc(100% - 15px);
        position: relative;
        display: flex;
        flex-direction: column;
    }
    
    /* Center container for icons and main text */
    .center-container {
        position: absolute;
        top: 50%;
        left: 50%;
        transform: translate(-50%, -50%);
        display: flex;
        flex-direction: column;
        align-items: center;
        text-align: center;
        width: 100%;
    }
    
    
    /* Large billing icon for processing state */
    .large-icon {
        width: 73px !important;
        height: 73px !important;
        position: static !important;
        transform: none !important;
        margin-bottom: 20px;
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
        margin-bottom: 20px;
    }
    
    /* Text spacing */
    .processing-text {
        margin-bottom: 10px;
    }
    
    .success-text {
        margin-bottom: 10px;
    }
    
    .confirmation-text {
        margin-bottom: 40px;
    }
    
    .loading-text {
        text-align: center;
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
        z-index: 1;
    }
    
    .inline-lock-icon {
        position: unset;
        transform: none;
        display: inline-block;
        vertical-align: middle;
        margin-right: 5px;
    }
</style>