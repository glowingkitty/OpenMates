<script lang="ts">
    import { text } from '@repo/ui';
    import { fade } from 'svelte/transition';
    import Toggle from '../Toggle.svelte';
    import { getWebsiteUrl, routes } from '../../config/links';
    import { createEventDispatcher } from 'svelte';
    
    const dispatch = createEventDispatcher();
    
    // Toggle state for consent
    export let hasConsentedToLimitedRefund: boolean = false;
    
    // Function to handle toggle click
    function handleRowClick() {
        hasConsentedToLimitedRefund = !hasConsentedToLimitedRefund;
        dispatch('consentChanged', { consented: hasConsentedToLimitedRefund });
    }
    
    // Function to prevent toggle click from triggering row click
    function handleToggleClick(event: Event) {
        event.stopPropagation();
    }
    
    function openRefundInfo() {
        // Open refund info in new tab
        window.open(getWebsiteUrl(routes.docs.userGuide_signup_10_1), '_blank');
    }
</script>

<div class="consent-view" in:fade={{ duration: 300 }} out:fade={{ duration: 200 }}>
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
        <button on:click={openRefundInfo} class="text-button learn-more-button">
            {@html $text('signup.click_here_learn_more.text')}
        </button>
    </div>
</div>

<style>
    .consent-view {
        width: 100%;
        height: 100%;
        position: relative;
        display: flex;
        flex-direction: column;
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
    
    .confirmation-text {
        color: var(--color-grey-60);
        font-size: 16px;
        text-align: left;
        flex: 1;
    }

    .learn-more-button {
        padding-left: 66px;
        text-align: left;
    }
</style>
