<script lang="ts">
    import { fade } from 'svelte/transition';
    import { signupStore } from '../../stores/signupStore';
    
    // Step name constants - must match those in Signup.svelte
    const STEP_ALPHA_DISCLAIMER = 'alpha_disclaimer';
    const STEP_BASICS = 'basics';
    const STEP_CONFIRM_EMAIL = 'confirm_email';
    const STEP_SECURE_ACCOUNT = 'secure_account';
    const STEP_PASSWORD = 'password';
    // const STEP_PROFILE_PICTURE = 'profile_picture'; // Moved to settings
    const STEP_ONE_TIME_CODES = 'one_time_codes';
    const STEP_BACKUP_CODES = 'backup_codes';
    const STEP_RECOVERY_KEY = 'recovery_key';
    const STEP_TFA_APP_REMINDER = 'tfa_app_reminder';
    const STEP_CREDITS = 'credits';
    const STEP_PAYMENT = 'payment';
    const STEP_AUTO_TOP_UP = 'auto_top_up';
    const STEP_COMPLETION = 'completion';

    // Define the step sequences
    // Note: STEP_COMPLETION is not included as it's not a visible step - users go directly to the app after auto top-up
    const fullStepSequence = [
        STEP_ALPHA_DISCLAIMER, STEP_BASICS, STEP_CONFIRM_EMAIL, STEP_SECURE_ACCOUNT, STEP_PASSWORD,
        STEP_ONE_TIME_CODES, STEP_TFA_APP_REMINDER, STEP_BACKUP_CODES, STEP_RECOVERY_KEY, // STEP_PROFILE_PICTURE,
        STEP_CREDITS, STEP_PAYMENT, STEP_AUTO_TOP_UP
    ];

    const passkeyStepSequence = [
        STEP_ALPHA_DISCLAIMER, STEP_BASICS, STEP_CONFIRM_EMAIL, STEP_SECURE_ACCOUNT, STEP_RECOVERY_KEY,
        STEP_CREDITS, STEP_PAYMENT, STEP_AUTO_TOP_UP
    ];

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

    // Filter out email confirmation step if self-hosted, and payment steps if payment is disabled
    const filteredFullSequence = $derived(
        (() => {
            let sequence = fullStepSequence;
            // Filter out email confirmation for self-hosted
            if (isSelfHosted) {
                sequence = sequence.filter(step => step !== STEP_CONFIRM_EMAIL);
            }
            // Filter out payment steps if payment is disabled
            if (!paymentEnabled) {
                sequence = sequence.filter(step => ![STEP_CREDITS, STEP_PAYMENT, STEP_AUTO_TOP_UP].includes(step));
            }
            return sequence;
        })()
    );

    const filteredPasskeySequence = $derived(
        (() => {
            let sequence = passkeyStepSequence;
            // Filter out email confirmation for self-hosted
            if (isSelfHosted) {
                sequence = sequence.filter(step => step !== STEP_CONFIRM_EMAIL);
            }
            // Filter out payment steps if payment is disabled
            if (!paymentEnabled) {
                sequence = sequence.filter(step => ![STEP_CREDITS, STEP_PAYMENT, STEP_AUTO_TOP_UP].includes(step));
            }
            return sequence;
        })()
    );

    // Filter stepSequenceOverride if provided (apply self-hosted and payment filtering)
    // This ensures filtering is always applied, even if the override was computed before isSelfHosted was set
    const filteredStepSequenceOverride = $derived(
        stepSequenceOverride 
            ? (() => {
                let sequence = [...stepSequenceOverride]; // Create a copy to avoid mutating the original
                // Filter out email confirmation for self-hosted (always apply this filter)
                if (isSelfHosted) {
                    sequence = sequence.filter(step => step !== STEP_CONFIRM_EMAIL);
                }
                // Filter out payment steps if payment is disabled (always apply this filter)
                if (!paymentEnabled) {
                    sequence = sequence.filter(step => ![STEP_CREDITS, STEP_PAYMENT, STEP_AUTO_TOP_UP].includes(step));
                }
                return sequence;
            })()
            : null
    );

    // Determine active sequence based on login method
    // Default to passkey sequence (assume passkey by default)
    // Only use full sequence when user explicitly selects password + 2FA OTP
    let activeSequence = $derived(
        filteredStepSequenceOverride ||
        ($signupStore.loginMethod === 'password' ? filteredFullSequence : filteredPasskeySequence)
    );

</script>

<div class="status-bar" transition:fade>
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
        transition: background-color 0.3s ease;
    }

    .status-dot.active {
        background-color: var(--color-grey-50);
    }
</style>
