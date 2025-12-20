<!--
# YAML file explains structure of the UI.
The yaml structure is used as a base for auto generating & auto updating the documentations
and to help LLMs to answer questions regarding how the UI is used.
Instruction to AI: Only update the yaml structure if the UI structure is updated enough to justify
changes to the documentation (to keep the documentation up to date).
-->
<!-- yaml
step_9_top_content_svelte:
    pay_per_use_header:
        type: 'text'
        text:
            - 'Pay credits per use'
            - $text('signup.for_chatting_and_apps.text')
        purpose:
            - 'Explain that credits are needed to chat with the digital team mates and use apps.'
        bigger_context:
            - 'Signup'
        tags:
            - 'signup'
            - 'pay_per_use'
        connected_documentation:
            - '/signup/pay-per-use'
    pay_per_use_explainer:
        type: 'text'
        text:
            - $text('signup.only_pay_what_you_use.text')
            - $text('signup.no_expiration_of_credits.text')
            - $text('signup.no_subscription.text')
            - $text('signup.no_ads.text')
            - $text('signup.no_selling_of_user_data.text')
            - $text('signup.pricing_details_on_page_of_app_skill.text')
        purpose:
            - 'Explain the benefits of the pay per use model.'
        bigger_context:
            - 'Signup'
        tags:
            - 'signup'
            - 'pay_per_use'
        connected_documentation:
            - '/signup/pay-per-use'
    open_app_settings:
        type: 'button'
        text: $text('signup.open_app_settings.text')
        processing:
            - 'User clicks on button'
            - 'Settings menu with App settings is opened.'
        purpose:
            - 'Button to open the app settings.'
        bigger_context:
            - 'Signup'
        tags:
            - 'signup'
            - 'app_settings'
        connected_documentation:
            - '/signup/app-settings'
-->

<script lang="ts">
    import { text } from '@repo/ui';
    import { settingsDeepLink } from '../../../../stores/settingsDeepLinkStore';
    import { panelState } from '../../../../stores/panelStateStore'; // Added panelState import
    import { createEventDispatcher } from 'svelte';
    import GiftCardRedeem from '../../../../components/settings/billing/GiftCardRedeem.svelte';
    
    const dispatch = createEventDispatcher();
    
    // State to track if gift card input is shown
    let showGiftCardInput = $state(false);
    
    /**
     * Open the app store in settings using deep linking.
     * Sets both the store and the URL hash for proper deep linking support.
     */
    function openAppSettings() {
        // Update URL hash for deep linking support (format: #settings/appstore)
        if (typeof window !== 'undefined') {
            window.location.hash = '#settings/appstore';
        }
        
        // Set the deep link path to app_store (not apps)
        settingsDeepLink.set('app_store');
        
        // Then make sure menu is visible using panelState with a slight delay
        setTimeout(() => {
            panelState.openSettings();
        }, 10);
    }
    
    /**
     * Handle gift card redemption success.
     * Go to payment step to show purchase confirmation, then automatically complete signup.
     */
    function handleGiftCardRedeemed(event: CustomEvent<{ credits_added: number, current_credits: number }>) {
        // Credits are already added to the account via the gift card redemption API
        // Go to payment step with showSuccess=true to show purchase confirmation screen
        // The payment step will display success message about gift card redemption, then auto-complete signup
        console.debug('[CreditsTopContent] Gift card redeemed, dispatching step event to payment with isGiftCardRedemption=true');
        dispatch('step', {
            step: 'payment',
            isGiftCardRedemption: true, // Flag to indicate this is a gift card redemption
            showSuccess: true, // Show purchase confirmation screen
            credits_amount: event.detail.credits_added || 0 // Pass redeemed credits amount
        });
    }
    
    /**
     * Cancel gift card input and return to credit selection.
     */
    function cancelGiftCard() {
        showGiftCardInput = false;
    }
</script>

<div class="container">
    <div class="top-container">
        <div class="header-content">
            <div class="primary-text">
                {@html $text('signup.pay_per_use.text').replace('{credits}', '<span class="coin-icon-inline"></span>')}
            </div>
        </div>
    </div>
    
    <div class="bottom-container">
        <div class="main-content">
            {#if showGiftCardInput}
                <!-- Gift Card Redemption Form -->
                <div class="gift-card-container">
                    <GiftCardRedeem
                        hideSuccessMessage={true}
                        on:redeemed={handleGiftCardRedeemed}
                        on:cancel={cancelGiftCard}
                    />
                </div>
            {:else}
                <div>{@html $text('signup.only_pay_what_you_use.text')}</div>

                <div class="benefits-container">
                    <div class="benefit-item">
                        <div class="check-icon"></div>
                        <div>{@html $text('signup.no_subscription.text')}</div>
                    </div>
                    <div class="benefit-item">
                        <div class="check-icon"></div>
                        <div>{@html $text('signup.no_expiration_of_credits.text')}</div>
                    </div>
                    <div class="benefit-item">
                        <div class="check-icon"></div>
                        <div>{@html $text('signup.no_selling_of_user_data.text')}</div>
                    </div>
                    <div class="benefit-item">
                        <div class="check-icon"></div>
                        <div>{@html $text('signup.no_ads.text')}</div>
                    </div>
                </div>
                
                <div class="footer-container">
                    <!-- Gift Card Button -->
                    <button onclick={() => showGiftCardInput = true} class="text-button gift-card-button">
                        {@html $text('settings.billing.gift_card.have_code.text')}
                    </button>
                    
                    <!-- App Store Link -->
                    <button onclick={openAppSettings} class="text-button">
                        {@html $text('signup.prices_on_app_store_soon.text')}
                    </button>
                </div>
            {/if}
        </div>
    </div>
</div>

<style>
    .container {
        position: relative;
        width: 100%;
        height: 100%;
        min-height: 400px; /* Ensure minimum height for credits form visibility */
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
    
    .header-content {
        display: flex;
        flex-direction: column;
        text-align: center;
        padding-bottom: 20px;
    }
    
    .bottom-container {
        position: absolute;
        top: 130px;
        left: 0;
        right: 0;
        bottom: 0;
        padding: 0 24px;
        overflow-y: auto; /* Allow scrolling if content exceeds container */
        overflow-x: hidden;
    }

    @media (max-width: 600px) {
        .top-container {
            height: 60px;
        }
        .bottom-container {
            top: 60px;
        }
    }
    
    .main-content {
        display: flex;
        flex-direction: column;
        justify-content: space-between;
        align-items: center;
        height: 100%; /* Fill available space */
        padding: 25px 0;
        box-sizing: border-box;
    }
    
    
    :global(.coin-icon-inline) {
        display: inline-flex;
        width: 25px;
        height: 25px;
        background-image: url('@openmates/ui/static/icons/coins.svg');
        background-size: contain;
        background-repeat: no-repeat;
        vertical-align: middle;
        filter: invert(1);
        margin: 0 5px;
        position: relative;
        top: -2px;
    }
    
    .primary-text {
        white-space: nowrap;
        display: flex;
        align-items: center;
        justify-content: center;
        color: white;
    }
    
    .benefits-container {
        width: 100%;
        max-width: 270px;
        display: flex;
        flex-direction: column;
        gap: 5px;
    }
    
    .benefit-item {
        display: flex;
        align-items: center;
        gap: 4px;
    }
    
    .check-icon {
        width: 24px;
        height: 24px;
        background-color: #58BC00;
        mask-image: url('@openmates/ui/static/icons/check.svg');
        mask-size: contain;
        mask-repeat: no-repeat;
        mask-position: center;
    }
    
    .footer-container {
        width: 100%;
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 10px;
    }

    .text-button {
        all: unset;
        position: relative;
        display: inline-block;
        color: transparent;
        background: var(--color-primary);
        -webkit-background-clip: text;
        background-clip: text;
        -webkit-text-fill-color: transparent;
        cursor: pointer;
        padding: 4px;
        margin: -4px;
        -webkit-tap-highlight-color: transparent;
        font-size: 14px;
        text-align: center;
    }
    
    .gift-card-button {
        margin-bottom: 8px;
    }
    
    .gift-card-container {
        width: 100%;
        max-width: 400px;
    }

</style>