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
    import CreditsPackage from '../../../../components/CreditsPackage.svelte';
    import { fly } from 'svelte/transition';
    import { createEventDispatcher, onMount } from 'svelte';
    import { getApiUrl, apiEndpoints } from '../../../../config/api'; // Import API config
    import { isLoadingGiftCheck, hasGiftForSignup } from '../../../../stores/signupState'; // Import stores

    const dispatch = createEventDispatcher();

    // Local state to store the actual gift amount if present
    let giftAmount: number | null = $state(null); 

    // Fetch gift status on component mount and update stores
    onMount(async () => {
        $isLoadingGiftCheck = true; // Use store
        try {
            const response = await fetch(getApiUrl() + apiEndpoints.auth.checkGift, {
                method: 'GET',
                headers: {
                    'Accept': 'application/json',
                    'Origin': window.location.origin
                },
                credentials: 'include' // Important for sending auth cookies
            });

            if (response.ok) {
                const giftData = await response.json();
                console.debug("Gift check response:", giftData);
                $hasGiftForSignup = giftData.has_gift; // Update store
                giftAmount = giftData.amount; // Store amount locally
            } else {
                console.error("Failed to check for gifted credits:", response.status, await response.text());
                $hasGiftForSignup = false; // Assume no gift on error
                giftAmount = null;
            }
        } catch (error) {
            console.error("Error checking for gifted credits:", error);
            $hasGiftForSignup = false; // Assume no gift on error
            giftAmount = null;
        } finally {
            $isLoadingGiftCheck = false; // Use store
        }
    });

    // Define the available credit packages
    const creditPackages = [
        { credits_amount: 1000, price: 2, currency: "EUR"},
        { credits_amount: 10000, price: 10, currency: "EUR"},
        { credits_amount: 21000, price: 20, currency: "EUR", recommended: true },
        { credits_amount: 54000, price: 50, currency: "EUR"},
        // { credits_amount: 110000, price: 100, currency: "EUR"}
    ];

    // Current package index using Svelte 5 runes
    let currentPackageIndex = $state(2); // Start with the recommended 21000 credits package

    // Navigate to previous package
    function showLessCredits() {
        if (currentPackageIndex > 0) {
            currentPackageIndex--;
        }
    }

    // Navigate to next package
    function showMoreCredits() {
        if (currentPackageIndex < creditPackages.length - 1) {
            currentPackageIndex++;
        }
    }

    // Handle buy event from CreditsPackage
    function handleBuy(event) {
        const { credits_amount, price, currency } = event.detail;
        // Move to step 10 and pass the credits amount, price and currency
        dispatch('step', {
            step: 'payment',
            credits_amount,
            price,
            currency
        });
    }

    // Handle gift acceptance event from CreditsPackage
    function handleGiftAccepted() {
        // Move to step 10, indicating it's a gift confirmation
        dispatch('step', {
            step: 'payment',
            isGift: true, // Add flag to indicate gift
            credits_amount: giftAmount // Pass locally stored gift amount
            // No price/currency needed for gifts
        });
    }

    // Convert to Svelte 5 runes
    let currentPackage = $derived(creditPackages[currentPackageIndex]);
    // Disable standard navigation if a gift is present or loading
    let canShowLess = $derived(currentPackageIndex > 0 && !$hasGiftForSignup && !$isLoadingGiftCheck); // Use stores
    let canShowMore = $derived(currentPackageIndex < creditPackages.length - 1 && !$hasGiftForSignup && !$isLoadingGiftCheck); // Use stores
</script>

<div class="bottom-content">
    {#if $isLoadingGiftCheck} <!-- Use store -->
        <div></div> <!-- Keep empty div for loading state as per current file -->
    {:else if $hasGiftForSignup && giftAmount !== null} <!-- Use store AND ensure giftAmount is loaded -->
        <!-- Gift Flow: Show only the gifted package -->
        <div class="credits-package-container gift-flow">
             <div class="package-wrapper">
                <CreditsPackage 
                    isGift={true}
                    giftAmount={giftAmount}
                    on:giftAccepted={handleGiftAccepted}
                />
            </div>
        </div>
         <!-- Removed optional text below gift package -->
    {:else}
        <!-- Standard Purchase Flow -->
        <div class="credits-package-container">
            {#if canShowLess} <!-- Reactive variable already uses stores -->
                <button class="nav-button" onclick={showLessCredits}>
                    <div class="clickable-icon icon_back"></div>
                {@html $text('signup.less.text')}
                </button>
            {/if}

            <div class="package-wrapper">
                {#key currentPackage.credits_amount}
                    <div in:fly={{ x: 100, duration: 300 }} out:fly={{ x: -100, duration: 300 }}>
                        <CreditsPackage 
                            credits_amount={currentPackage.credits_amount}
                            recommended={currentPackage.recommended}
                            price={currentPackage.price}
                            currency={currentPackage.currency}
                            on:buy={handleBuy}
                            isGift={false}
                        />
                    </div>
                {/key}
            </div>

            {#if canShowMore}
                <button class="nav-button" onclick={showMoreCredits}>
                    {@html $text('signup.more.text')}
                    <div class="clickable-icon icon_back icon-mirrored"></div>
                </button>
            {/if}
        </div>
        <div class="select_amount_text">{@html $text('signup.select_amount.text')}</div>
    {/if}
</div>

<style>
    .bottom-content {
        padding-top: 10px;
    }
    
    /* Adjust container height/alignment for gift flow if needed */
    .credits-package-container.gift-flow {
        margin-bottom: 0; /* Remove negative margin if nav buttons aren't present */
        /* Add any other specific styles for the gift layout */
    }
    .credits-package-container {
        display: flex;
        justify-content: center;
        align-items: center; /* Keep vertical alignment */
        position: relative;
    }

    .package-wrapper {
        height: 100%;
        display: flex;
        justify-content: center;
    }

    .select_amount_text{
        color: var(--color-grey-60);
        margin-top: -20px;
    }
    
    .nav-button {
        all: unset;
        position: absolute;
        bottom: -10px;
        transform: translateY(-50%);
        font-size: 14px;
        color: var(--color-grey-60);
        background: none;
        border: none;
        cursor: pointer;
        padding: 0;
        display: flex;
        align-items: center;
        gap: 4px;
        z-index: 10;
    }

    .nav-button:hover {
        background: none;
        cursor: pointer;
    }

    .icon-mirrored {
        transform: scaleX(-1);
    }

    .nav-button:nth-child(1) {
        left: 0;
    }

    .credits-package-container > .nav-button:last-child {
        right: 0;
    }
</style>
