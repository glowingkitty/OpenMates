<!--
# YAML file explains structure of the UI.
The yaml structure is used as a base for auto generating & auto updating the documentations
and to help LLMs to answer questions regarding how the UI is used.
Instruction to AI: Only update the yaml structure if the UI structure is updated enough to justify
changes to the documentation (to keep the documentation up to date).
-->
<!-- yaml
step_10_top_content_svelte:
    credits_amount_header:
        type: 'text'
        text:
            - $text('signup.amount_currency.text') with amount and currency icon
            - $text('signup.for_chatting_and_apps.text')
        purpose:
            - 'Display the amount of credits the user will receive'
        bigger_context:
            - 'Signup'
        tags:
            - 'signup'
            - 'credits'
    payment_component:
        type: 'component'
        component: 'Payment.svelte'
        purpose:
            - 'Display payment form with refund consent'
            - 'Process payment information'
        bigger_context:
            - 'Signup'
        tags:
            - 'signup'
            - 'payment'
            - 'credits'
-->

<script lang="ts">
    import { text } from '@repo/ui';
    import { createEventDispatcher } from 'svelte';
    import Payment from '../../../../components/Payment.svelte';
    
    const dispatch = createEventDispatcher();
    
    // Accept credits amount, price and currency as props
    export let credits_amount: number = 21000;
    export let price: number = 20;
    export let currency: string = 'EUR';
    export let isGift: boolean = false; // New prop to indicate if it's a gift confirmation
    
    // Track if payment form is visible
    let isPaymentFormVisible = false;
    
    // Format number with thousand separators
    function formatNumber(num: number): string {
        return num.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ".");
    }

    function handleConsent(event) {
        // Forward consent event to parent component
        dispatch('consentGiven', event.detail);
        
        // When consent is given, after a short delay, payment form will show
        if (event.detail.consented) {
            setTimeout(() => {
                isPaymentFormVisible = true;
                dispatch('paymentFormVisibility', { visible: true });
            }, 500);
        }
    }
    
    function handleOpenRefundInfo() {
        // Forward the refund info request to parent
        dispatch('openRefundInfo');
    }
    
    function handlePaymentStateChange(event) {
        // Forward payment state changes to parent component
        dispatch('paymentStateChange', event.detail);
    }
</script>

<div class="container">
    <div class="top-container">
        <div class="header-content">
            <div class="primary-text">
                {@html $text('signup.amount_currency.text')
                    .replace('{currency}', '<span class="coin-icon-inline"></span>')
                    .replace('{amount}', formatNumber(credits_amount))}
            </div>
            <div class="secondary-text">
                {@html $text('signup.for_chatting_and_apps.text')}
            </div>
        </div>
    </div>

    <div class="bottom-container">
        <div class="main-content">
            <div class="separated-block">
                <Payment 
                    {credits_amount} 
                    purchasePrice={price} 
                    {currency}
                    initialState={isGift ? 'success' : 'idle'}
                    {isGift}
                    on:consentGiven={handleConsent}
                    on:openRefundInfo={handleOpenRefundInfo}
                    on:paymentStateChange={handlePaymentStateChange}
                />
            </div>
        </div>
    </div>
</div>

<style>
    .container {
        position: relative;
        width: 100%;
        height: 100%;
    }
    
    .top-container {
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        height: 130px;
        padding: 0 24px;
        display: flex;
        align-items: flex-end;
        justify-content: center;
        z-index: 2;
    }

    @media (max-width: 600px) {
        .top-container {
            height: 60px;
        }
    }
    
    .header-content {
        display: flex;
        flex-direction: column;
        text-align: center;
        padding-bottom: 20px;
    }
    
    .secondary-text {
        font-size: 14px;
        color: white;
        opacity: 0.6;
        margin-top: 10px;
    }
    
    
    .primary-text {
        white-space: nowrap;
        display: flex;
        align-items: center;
        justify-content: center;
        color: white;
    }

    .bottom-container {
        position: absolute;
        top: 160px;
        left: 0;
        right: 0;
        bottom: 0;
        padding: 0 24px;
        overflow-y: hidden;
    }
    
    .main-content {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: flex-start;
        width: 100%;
        gap: 24px;
    }

    .separated-block {
        position: relative;
        width: 80%;
        height: 490px;
        max-width: 400px;
        background-color: var(--color-grey-20);
        border-radius: 16px;
        padding: 16px;
        box-shadow: 0 2px 6px rgba(0, 0, 0, 0.1);
        display: flex;
        flex-direction: column;
    }
    
    /* Target the bottom containers of our payment components */
    .separated-block :global(.bottom-container) {
        position: absolute;
        bottom: 20px; /* Position 50px from the bottom as requested */
        left: 0;
        width: 100%;
        padding-bottom: 0;
    }
</style>