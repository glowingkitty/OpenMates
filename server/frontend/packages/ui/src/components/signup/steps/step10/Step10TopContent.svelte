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
    import { onMount } from 'svelte';
    import AppIconGrid from '../../../../components/AppIconGrid.svelte';
    
    // Accept credits amount as prop
    export let credits_amount: number = 21000;
    
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
        <div class="separated-block">
            <div class="signup-header">
                <div class="icon header_size legal"></div>
                <h2 class="signup-menu-title">{@html $text('signup.limited_refund.text')}</h2>
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
        top: 130px;
        left: 0;
        right: 0;
        bottom: 0;
        padding: 0 24px;
        overflow-y: auto;
    }

    .separated-block {
        width: 80%;
        background-color: var(--color-grey-20);
        border-radius: 16px;
        padding: 16px;
        box-shadow: 0 2px 6px rgba(0, 0, 0, 0.1);
    }
    
</style>