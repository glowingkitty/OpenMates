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
            <button class="nav-button" on:click={showLessCredits}>
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
                    />
                </div>
            {/key}
        </div>

        {#if canShowMore}
            <button class="nav-button" on:click={showMoreCredits}>
                {@html $text('signup.more.text')}
                <div class="clickable-icon icon_back icon-mirrored"></div>
            </button>
        {/if}
    </div>
    <div class="color-grey-60">{@html $text('signup.select_amount.text')}</div>
</div>

<style>
    .bottom-content {
        padding-top: 10px;
    }
    
    .credits-package-container {
        display: flex;
        justify-content: center;
        align-items: center;
        position: relative;
        margin-bottom: -20px;
    }

    .package-wrapper {
        height: 100%;
        display: flex;
        justify-content: center;
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
