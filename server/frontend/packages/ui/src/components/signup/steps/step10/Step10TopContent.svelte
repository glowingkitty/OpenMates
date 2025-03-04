<!--
# YAML file explains structure of the UI.
The yaml structure is used as a base for auto generating & auto updating the documentations
and to help LLMs to answer questions regarding how the UI is used.
Instruction to AI: Only update the yaml structure if the UI structure is updated enough to justify
changes to the documentation (to keep the documentation up to date).
-->
<!-- yaml

-->

<script lang="ts">
    import { text } from '@repo/ui';
    import { settingsMenuVisible } from '../../../Settings.svelte';
    import { settingsDeepLink } from '../../../../stores/settingsDeepLinkStore';
    import { isMobileView } from '../../../Settings.svelte';
    
    // Accept credits amount as prop
    export let credits_amount: number = 21000;
    
    // Format number with thousand separators
    function formatNumber(num: number): string {
        return num.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ".");
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
    
</style>