<script lang="ts">
    import { text } from '@repo/ui';
    import AppIconGrid from './AppIconGrid.svelte';
    
    // Props
    export let credits_amount: number = 0;
    export let recommended: boolean = false;
    export let price: number = 0;
    export let currency: string = 'EUR';
    
    // Format number with thousand separators
    function formatNumber(num: number): string {
        return num.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ".");
    }
    
    // Generate a small icon grid for decoration
    const IconGrid50000Credits = [
        ['diagrams','sheets','lifecoaching','jobs','fashion','calendar','contacts','hosting','socialmedia'],
        ['slides','docs','audio','code','ai','photos','events','travel','mail'],
        ['weather','notes','videos',null,null,null,'pcbdesign','legal','web'],
        ['calculator','maps','finance',null,null,null,'health','home','design'],
        ['3dmodels','games','news',null,null,null,'movies','whiteboards','projectmanagement']
    ];
    const IconGrid20000Credits = [
        ['diagrams','sheets','lifecoaching','jobs','fashion','calendar','contacts','hosting','socialmedia'],
        ['slides','docs','audio','code','ai','photos','events','travel','mail']
    ];
    const IconGrid10000Credits = [
        ['lifecoaching','jobs','fashion','calendar','contacts'],
        ['audio','code','ai','photos','events']
    ];
    const IconGrid1000Credits = [
        [null,null,null,null,null],
        [null,'code','ai','photos',null]
    ];
    
    // Function to select the appropriate icon grid based on credits amount
    function selectIconGrid(amount: number) {
        if (amount >= 50000) return IconGrid50000Credits;
        if (amount >= 20000) return IconGrid20000Credits;
        if (amount >= 10000) return IconGrid10000Credits;
        if (amount >= 1000) return IconGrid1000Credits;
        return [];
    }
</script>

<div class="credits-package-container">
    {#if recommended}
        <div class="recommended-badge">
            <div class="thumbs-up-icon"></div>
            <span>{@html $text('signup.recommended.text')}</span>
        </div>
    {/if}
    
    <div class="credits-package">
        <div class="app-icon-grid-container">
            <AppIconGrid 
                iconGrid={selectIconGrid(credits_amount)} 
                size="30px" 
                gridGap="2px" 
                shifted="columns"
                borderColor={null}
            />
        </div>
        
        <div class="credits-amount">
            {@html $text('signup.amount_currency.text')
                .replace('{currency}', '<span class="coin-icon-inline"></span>')
                .replace('{amount}', formatNumber(credits_amount))}
        </div>
    </div>
    
    <button class="buy-button">
        {@html $text('signup.buy_for.text')
            .replace('{currency}', currency)
            .replace('{amount}', price.toString())}
    </button>
</div>

<style>
    .credits-package-container {
        position: relative;
        width: 280px;
        display: flex;
        flex-direction: column;
        align-items: center;
    }
    
    .credits-package {
        width: 280px;
        height: 143px;
        background: var(--color-primary);
        border-radius: 13px;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.25);
        overflow: hidden;
        position: relative;
        display: flex;
        flex-direction: column;
        justify-content: space-between;
        align-items: center;
    }
    
    .app-icon-grid-container {
        width: 100%;
        margin-top: -5px; /* To make it appear cut off at the top */
        padding-bottom: 10px;
    }
    
    .credits-amount {
        position: absolute;
        bottom: 40px;
        left: 0;
        right: 0;
        font-size: 18px;
        color: white;
        text-align: center;
        font-weight: 500;
        z-index: 2;
    }
    
    .recommended-badge {
        position: absolute;
        top: 0;
        transform: translateY(-50%);
        background: var(--color-primary);
        border-radius: 19px;
        padding: 6px 12px;
        display: flex;
        align-items: center;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
        z-index: 2;
    }
    
    .thumbs-up-icon {
        width: 13px;
        height: 13px;
        background-image: url('@openmates/ui/static/icons/thumbsup.svg');;
        background-size: contain;
        background-repeat: no-repeat;
        filter: invert(1);
        margin-right: 6px;
    }
    
    .recommended-badge span {
        color: white;
        font-size: 14px;
        font-weight: 500;
    }
    
    .buy-button {
        transform: translateY(-30px);
        padding: 20px;
    }
</style>
