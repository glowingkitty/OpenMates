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

    // Define the available credit packages
    const creditPackages = [
        { credits_amount: 1000, price: 1, currency: "EUR"},
        { credits_amount: 10000, price: 10, currency: "EUR"},
        { credits_amount: 21000, price: 20, currency: "EUR", recommended: true },
        { credits_amount: 54000, price: 50, currency: "EUR"},
        { credits_amount: 110000, price: 100, currency: "EUR"}
    ];

    // Current package index
    let currentPackageIndex = 2; // Start with the recommended 21000 credits package

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

    $: currentPackage = creditPackages[currentPackageIndex];
    $: canShowLess = currentPackageIndex > 0;
    $: canShowMore = currentPackageIndex < creditPackages.length - 1;
</script>

<div class="bottom-content">
    <div class="credits-package-container">
        {#if canShowLess}
            <button class="nav-button nav-button-left" on:click={showLessCredits}>
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
                    />
                </div>
            {/key}
        </div>

        {#if canShowMore}
            <button class="nav-button nav-button-right" on:click={showMoreCredits}>
                {@html $text('signup.more.text')}
            </button>
        {/if}
    </div>
    {@html $text('signup.choose_your_credits_package.text')}
</div>

<style>
    .bottom-content {
        padding: 24px;
    }
    
    .credits-package-container {
        display: flex;
        justify-content: center;
        align-items: center;
        position: relative;
    }

    .package-wrapper {
        height: 100%;
        display: flex;
        justify-content: center;
    }
    
    .nav-button {
        position: absolute;
        top: 50%;
        transform: translateY(-50%);
        z-index: 10;
        padding: 8px 12px;
        border-radius: 4px;
        background-color: #f0f0f0;
        border: 1px solid #ddd;
        cursor: pointer;
        font-size: 14px;
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
    }

    .nav-button:hover {
        background-color: #e0e0e0;
    }

    .nav-button-left {
        left: 0;
    }

    .nav-button-right {
        right: 0;
    }
</style>
