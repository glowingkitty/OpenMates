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
    limited_refund_section:
        type: 'section'
        text: $text('signup.limited_refund.text')
        purpose:
            - 'Explain the limited refund policy to the user'
        bigger_context:
            - 'Signup'
        tags:
            - 'signup'
            - 'refund'
            - 'legal'
    limited_refund_consent:
        type: 'toggle'
        text: $text('signup.i_agree_to_limited_refund.text')
        purpose:
            - 'User needs to consent to limited refund and right of withdrawal expiration'
        bigger_context:
            - 'Signup'
        tags:
            - 'signup'
            - 'refund'
            - 'legal'
            - 'consent'
    learn_more_button:
        type: 'button'
        text: $text('signup.click_here_learn_more.text')
        purpose:
            - 'Button to learn more about the limited refund policy'
        bigger_context:
            - 'Signup'
        tags:
            - 'signup'
            - 'refund'
            - 'legal'
-->

<script lang="ts">
    import { text } from '@repo/ui';
    import { settingsMenuVisible } from '../../../Settings.svelte';
    import { settingsDeepLink } from '../../../../stores/settingsDeepLinkStore';
    import { isMobileView } from '../../../Settings.svelte';
    import { onMount, createEventDispatcher } from 'svelte';
    import AppIconGrid from '../../../../components/AppIconGrid.svelte';
    import Toggle from '../../../Toggle.svelte';
    
    const dispatch = createEventDispatcher();
    
    // Accept credits amount as prop
    export let credits_amount: number = 21000;
    
    // Toggle state for consent
    let hasConsentedToLimitedRefund = false;
    
    $: if (hasConsentedToLimitedRefund) {
        dispatch('consentGiven', { consented: true });
    }
    
    // Format number with thousand separators
    function formatNumber(num: number): string {
        return num.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ".");
    }

    // Define icon grids based on the credits amount
    function getIconGridForCredits(amount: number) {
        if (amount >= 50000) {
            return [
                ['diagrams','sheets','lifecoaching','jobs','fashion','calendar','contacts','hosting','socialmedia'],
                ['slides','docs','audio','code','ai','photos','events','travel','mail'],
                ['weather','notes','videos',null,null,null,'pcbdesign','legal','web'],
                ['calculator','maps','finance',null,null,null,'health','home','design'],
                ['3dmodels','games','news',null,null,null,'movies','whiteboards','projectmanagement']
            ];
        }
        if (amount >= 20000) {
            return [
                ['diagrams','sheets','lifecoaching','jobs','fashion','calendar','contacts','hosting','socialmedia'],
                ['slides','docs','audio','code','ai','photos','events','travel','mail']
            ];
        }
        if (amount >= 10000) {
            return [
                ['lifecoaching','jobs','fashion','calendar','contacts'],
                ['audio','code','ai','photos','events']
            ];
        }
        // Default for 1000+ credits
        return [
            [null,null,null,null,null],
            [null,'code','ai','photos',null]
        ];
    }
    
    $: iconGrid = getIconGridForCredits(credits_amount);
    
    // Function to handle toggle click
    function handleRowClick() {
        hasConsentedToLimitedRefund = !hasConsentedToLimitedRefund;
    }
    
    // New function to prevent toggle click from triggering row click
    function handleToggleClick(event: Event) {
        event.stopPropagation();
    }
    
    function openRefundInfo() {
        // This would open documentation or info about the refund policy
        // For now we'll just dispatch an event that can be handled by a parent
        dispatch('openRefundInfo');
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
                <div class="signup-header">
                    <div class="icon header_size legal"></div>
                    <h2 class="signup-menu-title">{@html $text('signup.limited_refund.text')}</h2>
                </div>

                <div class="consent-container">
                    <div class="confirmation-row" 
                         on:click={handleRowClick}
                         on:keydown={(e) => e.key === 'Enter' || e.key === ' ' ? handleRowClick() : null}
                         role="button"
                         tabindex="0">
                        <div on:click={handleToggleClick} on:keydown|stopPropagation role="button" tabindex="0">
                            <Toggle bind:checked={hasConsentedToLimitedRefund} />
                        </div>
                        <span class="confirmation-text">
                            {@html $text('signup.i_agree_to_limited_refund.text')}
                        </span>
                    </div>
                    <button on:click={openRefundInfo} class="text-button">
                        {@html $text('signup.click_here_learn_more.text')}
                    </button>


                </div>
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
        width: 80%;
        height: 490px;
        max-width: 400px;
        background-color: var(--color-grey-20);
        border-radius: 16px;
        padding: 16px;
        box-shadow: 0 2px 6px rgba(0, 0, 0, 0.1);
    }

    .signup-header {
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 16px;
    }
    
    .consent-container {
        width: 100%;
        max-width: 400px;
        display: flex;
        flex-direction: column;
        align-items: flex-start;
        gap: 24px;
        padding-top: 30px;
    }
    
    .confirmation-row {
        display: flex;
        align-items: flex-start;
        gap: 12px;
        cursor: pointer;
        width: 100%;
    }
    
    .confirmation-row :global(.toggle-component) {
        min-width: 55px;
        flex-shrink: 0;
    }

    .confirmation-text {
        color: var(--color-grey-60);
        font-size: 16px;
        text-align: left;
        flex: 1;
    }
    
    .text-button {
        align-self: flex-start;
        text-align: left;
        padding-left: 66px;
    }
</style>