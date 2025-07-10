<script lang="ts">
    import { fade } from 'svelte/transition';
    
    // Step name constants - must match those in Signup.svelte
    const STEP_BASICS = 'basics';
    const STEP_CONFIRM_EMAIL = 'confirm_email';
    const STEP_PROFILE_PICTURE = 'profile_picture';
    const STEP_ONE_TIME_CODES = 'one_time_codes';
    const STEP_BACKUP_CODES = 'backup_codes';
    const STEP_TFA_APP_REMINDER = 'tfa_app_reminder';
    const STEP_SETTINGS = 'settings';
    const STEP_MATE_SETTINGS = 'mate_settings';
    const STEP_CREDITS = 'credits';
    const STEP_PAYMENT = 'payment';
    const STEP_COMPLETION = 'completion';
    
    // Define the step sequence
    const stepSequence = [
        STEP_BASICS,
        STEP_CONFIRM_EMAIL,
        STEP_PROFILE_PICTURE,
        STEP_ONE_TIME_CODES,
        STEP_BACKUP_CODES,
        STEP_TFA_APP_REMINDER,
        STEP_SETTINGS,
        STEP_MATE_SETTINGS,
        STEP_CREDITS,
        STEP_PAYMENT,
        STEP_COMPLETION
    ];
    
    export let currentStepName: string = STEP_BASICS;
    
    // Calculate the current step index
    $: currentStepIndex = stepSequence.indexOf(currentStepName);
</script>

<div class="status-bar" transition:fade>
    {#each stepSequence as step, index}
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
