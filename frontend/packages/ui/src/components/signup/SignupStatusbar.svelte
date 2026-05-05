<script lang="ts">
    import { fade } from 'svelte/transition';
    import { signupStore } from '../../stores/signupStore';
    import { STEP_BASICS } from '../../stores/signupState';
    import { getSignupStepSequence } from './signupFlow';
    
    // Props using Svelte 5 runes
    let { 
        currentStepName = STEP_BASICS, 
        stepSequenceOverride,
        paymentEnabled = true,
        isSelfHosted = false
    }: { 
        currentStepName?: string, 
        stepSequenceOverride?: string[],
        paymentEnabled?: boolean,
        isSelfHosted?: boolean
    } = $props();

    // Determine active sequence based on login method
    // Default to passkey sequence (assume passkey by default)
    // Only use full sequence when user explicitly selects password + 2FA OTP
    let activeSequence = $derived(
        stepSequenceOverride ||
        getSignupStepSequence({
            loginMethod: $signupStore.loginMethod,
            isSelfHosted,
            paymentEnabled
        })
    );

</script>

<div class="status-bar" data-testid="preview-status-bar" transition:fade>
    {#each activeSequence as step}
        <div class="status-dot" class:active={step === currentStepName}></div>
    {/each}
</div>

<style>
    .status-bar {
        display: flex;
        gap: 5px;
        justify-content: center;
        padding: 22px 0 0 0;
    }

    .status-dot {
        width: 15px;
        height: 15px;
        border-radius: 50%;
        background-color: var(--color-grey-30);
        transition: background-color var(--duration-slow) var(--easing-default);
    }

    .status-dot.active {
        background-color: var(--color-grey-50);
    }
</style>
