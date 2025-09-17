<script lang="ts">
    import { text } from '@repo/ui';
    import AppIconGrid from './AppIconGrid.svelte';
    import { createEventDispatcher } from 'svelte';
    import { getApiEndpoint, apiEndpoints } from '../config/api'; // Import API config, use getApiEndpoint
    import { updateProfile } from '../stores/userProfile'; // Import updateProfile

    const dispatch = createEventDispatcher();
    
    // Props using Svelte 5 runes
    let { 
        credits_amount = 0,
        recommended = false,
        price = 0,
        currency = 'EUR',
        isGift = false,
        giftAmount = 0
    }: {
        credits_amount?: number;
        recommended?: boolean;
        price?: number;
        currency?: string;
        isGift?: boolean;
        giftAmount?: number;
    } = $props();

    // State for accepting gift
    let isAcceptingGift = $state(false);
    let acceptError: string | null = $state(null);

    // Determine the amount to display using Svelte 5 runes
    let displayAmount = $derived(isGift ? giftAmount : credits_amount);
    
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
    
    // Handle button click (either buy or accept gift)
    async function handleButtonClick() {
        if (isGift) {
            // Accept Gift Flow
            isAcceptingGift = true;
            acceptError = null;
            try {
                const response = await fetch(getApiEndpoint(apiEndpoints.auth.acceptGift), { // Use getApiEndpoint
                    method: 'POST',
                    headers: {
                        'Accept': 'application/json',
                        'Origin': window.location.origin
                    },
                    credentials: 'include' // Important for sending auth cookies
                });

                if (response.ok) {
                    const result = await response.json();
                    if (result.success) {
                        console.info("Gift accepted successfully:", result);
                        // Update profile store if backend returns new credit amount
                        if (typeof result.current_credits === 'number') {
                            updateProfile({ credits: result.current_credits });
                        }
                        dispatch('giftAccepted');
                    } else {
                        console.error("Failed to accept gift:", result.message);
                        acceptError = result.message || 'Failed to accept gift.';
                    }
                } else {
                    const errorText = await response.text();
                    console.error("Failed to accept gift API call:", response.status, errorText);
                    acceptError = `Error: ${response.status}. Please try again.`;
                }
            } catch (error) {
                console.error("Error accepting gift:", error);
                acceptError = 'An unexpected error occurred. Please try again.';
            } finally {
                isAcceptingGift = false;
            }
        } else {
            // Standard Buy Flow
            dispatch('buy', { credits_amount, price, currency });
        }
    }
</script>

<div class="credits-package-container">
    {#if isGift}
        <!-- Gift Badge -->
        <div class="recommended-badge gift-badge">
            <div class="gift-icon"></div> <!-- Use gift icon -->
            <span>{@html $text('signup.your_gift.text')}</span> <!-- Use gift text -->
        </div>
    {:else if recommended}
        <!-- Standard Recommended Badge -->
        <div class="recommended-badge">
            <div class="thumbs-up-icon"></div>
            <span>{@html $text('signup.recommended.text')}</span>
        </div>
    {/if}
    
    <div class="credits-package">
        <div class="app-icon-grid-container">
            <AppIconGrid 
                iconGrid={selectIconGrid(displayAmount)}
                size="30px"
                gridGap="2px"
                shifted="columns"
                borderColor={null} 
            />
        </div>
        
        <div class="credits-amount">
            {@html $text('signup.amount_currency.text')
                .replace('{currency}', '<span class="coin-icon-inline"></span>')
                .replace('{amount}', formatNumber(displayAmount))}
        </div>
    </div>
    
    {#if acceptError}
        <div class="error-message">{acceptError}</div>
    {/if}

    <button class="buy-button" onclick={handleButtonClick} disabled={isAcceptingGift}>
        {#if isGift}
            {@html $text(isAcceptingGift ? 'login.loading.text' : 'signup.accept.text')}
        {:else}
            {@html $text('signup.buy_for.text')
                .replace('{currency}', currency)
                .replace('{amount}', price.toString())}
        {/if}
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

    @media (max-width: 600px) {
        .credits-package {
            height: 75px;
        }

        .credits-amount {
            bottom: 30px;
            font-size: 16px;
        }
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
