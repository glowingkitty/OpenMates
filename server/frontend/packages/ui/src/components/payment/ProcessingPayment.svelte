<script lang="ts">
    import { text } from '@repo/ui';
    import { fade } from 'svelte/transition';
    import { getWebsiteUrl, routes } from '../../config/links';
    import { createEventDispatcher } from 'svelte';
    
    const dispatch = createEventDispatcher();
    
    // Processing states
    export let state: 'processing' | 'success' = 'processing';
    
    function handleSecurePaymentInfoClick() {
        window.open(getWebsiteUrl(routes.docs.userGuide_signup_10_2), '_blank');
    }
</script>

{#if state === 'processing'}
    <div class="payment-processing" in:fade={{ duration: 300 }}>
        <div class="center-container">
            <span class="clickable-icon icon_billing large-icon"></span>
            <p class="processing-text color-grey-60">{@html $text('signup.processing_payment.text')}</p>
        </div>
        
        <div class="bottom-container">
            <button type="button" class="text-button" on:click={handleSecurePaymentInfoClick}>
                <span class="clickable-icon icon_lock inline-lock-icon"></span>
                {@html $text('signup.secured_and_powered_by.text').replace('{provider}', 'Revolut')}
            </button>
        </div>
    </div>
{:else}
    <div class="payment-success" in:fade={{ duration: 300 }}>
        <div class="center-container">
            <span class="check-icon"></span>
            <p class="success-text color-grey-60">{@html $text('signup.purchase_successful.text')}</p>
            <p class="confirmation-text color-grey-60">{@html $text('signup.you_will_receive_confirmation_soon.text')}</p>
        </div>
        
        <div class="bottom-container">
            <p class="loading-text color-grey-60">{@html $text('login.loading.text')}</p>
        </div>
    </div>
{/if}

<style>
    .payment-processing,
    .payment-success {
        width: 100%;
        height: 100%;
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
    
    /* Bottom container for footer buttons and text */
    .bottom-container {
        position: absolute;
        bottom: 0;
        left: 0;
        width: 100%;
        display: flex;
        justify-content: center;
        align-items: center;
        min-height: 50px;
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
    .payment-processing .clickable-icon,
    .payment-success .clickable-icon {
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