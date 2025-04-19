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
    
    function openAppSettings() {
        // First set the deep link path
        settingsDeepLink.set('apps');
        
        // Then make sure menu is visible using panelState with a slight delay
        setTimeout(() => {
            panelState.openSettings();
        }, 10);
    }
</script>

<div class="container">
    <div class="top-container">
        <div class="header-content">
            <div class="primary-text">
                {@html $text('signup.pay_per_use.text').replace('{credits}', '<span class="coin-icon-inline"></span>')}
            </div>
            <div class="secondary-text">
                {@html $text('signup.for_chatting_and_apps.text')}
            </div>
        </div>
    </div>
    
    <div class="bottom-container">
        <div class="main-content">
            <div>{@html $text('signup.only_pay_what_you_use.text')}</div>

            <div class="benefits-container">
                <div class="benefit-item">
                    <div class="check-icon"></div>
                    <div>{@html $text('signup.no_expiration_of_credits.text')}</div>
                </div>
                <div class="benefit-item">
                    <div class="check-icon"></div>
                    <div>{@html $text('signup.no_subscription.text')}</div>
                </div>
                <div class="benefit-item">
                    <div class="check-icon"></div>
                    <div>{@html $text('signup.no_ads.text')}</div>
                </div>
                <div class="benefit-item">
                    <div class="check-icon"></div>
                    <div>{@html $text('signup.no_selling_of_user_data.text')}</div>
                </div>
            </div>
            
            <div class="footer-container">
                <div class="pricing-details-text">
                    {@html $text('signup.pricing_details_on_page_of_app_skill.text')}
                </div>
                <button on:click={openAppSettings} class="text-button">
                    {$text('signup.open_app_settings.text')}
                </button>
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
        overflow-y: auto;
    }
    
    .main-content {
        display: flex;
        flex-direction: column;
        justify-content: space-between;
        align-items: center;
        height: 100%;
        padding: 10px 0;
        box-sizing: border-box;
    }
    
    .secondary-text {
        font-size: 14px;
        color: white;
        opacity: 0.6;
        margin-top: 10px;
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
        margin-top: 20px;
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
        margin-top: 30px;
    }
    
    .pricing-details-text {
        color: var(--color-grey-60);
        font-size: 14px;
        text-align: center;
    }

</style>