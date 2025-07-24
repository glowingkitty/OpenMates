<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import { _ } from 'svelte-i18n';
    import { userProfile } from '../../stores/userProfile'; // Import userProfile store
    import { getWebsiteUrl, routes } from '../../config/links';
    // Import current step store and gift check stores
    import { currentSignupStep, isLoadingGiftCheck, hasGiftForSignup } from '../../stores/signupState'; 
    
    // Step name constants - must match those in Signup.svelte
    const STEP_ALPHA_DISCLAIMER = 'alpha_disclaimer';
    const STEP_BASICS = 'basics';
    const STEP_CONFIRM_EMAIL = 'confirm_email';
    const STEP_SECURE_ACCOUNT = 'secure_account';
    const STEP_PASSWORD = 'password';
    const STEP_PROFILE_PICTURE = 'profile_picture';
    const STEP_ONE_TIME_CODES = 'one_time_codes';
    const STEP_BACKUP_CODES = 'backup_codes';
    const STEP_TFA_APP_REMINDER = 'tfa_app_reminder';
    const STEP_SETTINGS = 'settings';
    const STEP_MATE_SETTINGS = 'mate_settings';
    const STEP_CREDITS = 'credits';
    const STEP_PAYMENT = 'payment';
    const STEP_COMPLETION = 'completion';

    const stepSequence = [
        STEP_ALPHA_DISCLAIMER, STEP_BASICS, STEP_CONFIRM_EMAIL, STEP_SECURE_ACCOUNT, STEP_PASSWORD, 
        STEP_ONE_TIME_CODES, STEP_TFA_APP_REMINDER, STEP_BACKUP_CODES, STEP_PROFILE_PICTURE,
        STEP_CREDITS, STEP_PAYMENT, STEP_COMPLETION
    ];
    
    const dispatch = createEventDispatcher();

    export let showSkip = false;
    export let currentStep: string = STEP_BASICS;
    export let selectedAppName: string | null = null;
    export let showAdminButton = false;
    export let isAppSaved: boolean = false;

    function handleBackClick() {
        if (currentStep === STEP_BASICS || currentStep === STEP_ALPHA_DISCLAIMER) {
            dispatch('back');
        } else if (currentStep === STEP_ONE_TIME_CODES) {
            dispatch('logout');
        } else if (currentStep === STEP_SECURE_ACCOUNT) {
            // Special case: Go back from Secure Account to Basics (skipping confirm email)
            dispatch('step', { step: STEP_BASICS });
        } else {
            const currentIndex = stepSequence.indexOf(currentStep);
            if (currentIndex > 0) {
                dispatch('step', { step: stepSequence[currentIndex - 1] });
            }
        }
    }

    function handleSkipClick() {
        // Use userProfile.profile_image_url to check if image exists for profile picture step
        if (currentStep === STEP_PROFILE_PICTURE && $userProfile.profile_image_url) {
            dispatch('step', { step: STEP_CREDITS });
        } else if (currentStep === STEP_ONE_TIME_CODES && $userProfile.tfa_enabled) {
            dispatch('step', { step: STEP_TFA_APP_REMINDER });
    } else if (currentStep === STEP_TFA_APP_REMINDER) {
         // Always go to backup codes step next, regardless of whether an app is selected
         dispatch('step', { step: STEP_BACKUP_CODES });
        } else if (currentStep === STEP_SETTINGS && $userProfile.consent_privacy_and_apps_default_settings) {
            dispatch('step', { step: STEP_MATE_SETTINGS });
        } else if (currentStep === STEP_MATE_SETTINGS && $userProfile.consent_mates_default_settings) {
            dispatch('step', { step: STEP_CREDITS });
        } else if (currentStep === STEP_CREDITS) {
            console.debug('Skip and show demo first');
            // Custom action for credits step - will be replaced later with real action
        } else {
            // Default skip action
            dispatch('skip');
        }
    }

    function openSelfHostedDocs() {
        const docsUrl = getWebsiteUrl(routes.docs.selfhosted);
        window.open(docsUrl, '_blank');
    }

    function getNavText(step: string) {
        if (step === STEP_ALPHA_DISCLAIMER) return $_('login.login_button.text');
        if (step === STEP_BASICS) return $_('login.login_button.text');
        if (step === STEP_CONFIRM_EMAIL) return $_('signup.sign_up.text');
        if (step === STEP_SECURE_ACCOUNT) return $_('signup.sign_up.text');
        if (step === STEP_PASSWORD) return $_('signup.secure_your_account.text');
        if (step === STEP_ONE_TIME_CODES) return $_('settings.logout.text');
        if (step === STEP_TFA_APP_REMINDER) return $_('signup.connect_2fa_app.text');
        if (step === STEP_BACKUP_CODES) return $_('signup.2fa_app_reminder.text');
        if (step === STEP_PROFILE_PICTURE) return $_('signup.2fa_backup_codes.text');
        if (step === STEP_SETTINGS) return $_('signup.upload_profile_picture.text');
        if (step === STEP_MATE_SETTINGS) return $_('signup.settings.text');
        if (step === STEP_CREDITS) return $_('signup.upload_profile_picture.text');
        if (step === STEP_PAYMENT) return $_('signup.select_credits.text');
        return $_('signup.sign_up.text');
    }

// Update the reactive skipButtonText for different steps and states
$: skipButtonText = 
    // Use userProfile.profile_image_url for profile picture step logic
    (currentStep === STEP_PROFILE_PICTURE && $userProfile.profile_image_url) ? $_('signup.next.text') :
    (currentStep === STEP_ONE_TIME_CODES && $userProfile.tfa_enabled) ? $_('signup.next.text') :
    // Only show "Next" for TFA app reminder if an app has been selected AND saved
    (currentStep === STEP_TFA_APP_REMINDER && selectedAppName && selectedAppName.trim() !== '' && isAppSaved) ? $_('signup.next.text') :
    (currentStep === STEP_SETTINGS && $userProfile.consent_privacy_and_apps_default_settings) ? $_('signup.next.text') :
    (currentStep === STEP_MATE_SETTINGS && $userProfile.consent_mates_default_settings) ? $_('signup.next.text') :
    // (currentStep === STEP_CREDITS) ? $_('signup.skip_and_show_demo_first.text') : // Credits step skip demo # TODO implement this later
    $_('signup.skip.text'); // Default skip text

    // Determine if the skip/next button should be shown
    // Show if:
    // - One Time Codes step AND TFA is already enabled OR
    // - TFA App Reminder step AND (no app selected OR app selected and saved) OR
    // - Settings step AND consent_privacy_and_apps_default_settings is true OR
    // - Mate Settings step AND consent_mates_default_settings is true OR
    // - Credits step AND gift check is done AND NO gift is available OR
    // - showSkip prop is true AND it's not one of the special steps
    $: showActualSkipButton = 
        (currentStep === STEP_ONE_TIME_CODES && $userProfile.tfa_enabled) ||
        (currentStep === STEP_TFA_APP_REMINDER && (!selectedAppName || selectedAppName.trim() === '' || isAppSaved)) ||
        (currentStep === STEP_SETTINGS && $userProfile.consent_privacy_and_apps_default_settings) ||
        (currentStep === STEP_MATE_SETTINGS && $userProfile.consent_mates_default_settings) ||
        // (currentStep === STEP_CREDITS && !$isLoadingGiftCheck && !$hasGiftForSignup) || // Show skip/demo only if NO gift available # TODO implement this later
        (showSkip && ![STEP_ONE_TIME_CODES, STEP_TFA_APP_REMINDER, STEP_SETTINGS, STEP_MATE_SETTINGS, STEP_CREDITS].includes(currentStep));
</script>

<div class="nav-area">
    <button class="nav-button" on:click={handleBackClick}>
        <div class="clickable-icon icon_back"></div>
        {getNavText(currentStep)}
    </button>
    
    {#if showAdminButton}
        <button class="admin-button" on:click={openSelfHostedDocs}>
            <div class="clickable-icon icon_server admin-icon"></div>
            <span class="admin-text">{$_('signup.server_admin.text')}</span>
            <div class="clickable-icon icon_question question-icon"></div>
        </button>
    {/if}
    
    {#if showActualSkipButton}
        <button class="nav-button" on:click={handleSkipClick}>
            {skipButtonText}
            <div class="clickable-icon icon_back icon-mirrored"></div>
        </button>
    {/if}
</div>

<style>
    .nav-area {
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        height: 48px;
        z-index: 1;
        display: flex;
        justify-content: space-between;
    }

    .nav-button {
        all: unset;
        position: relative;
        font-size: 14px;
        color: var(--color-grey-60);
        background: none;
        border: none;
        cursor: pointer;
        padding: 0;
        display: flex;
        align-items: center;
        gap: 4px;
    }

    .nav-button:hover {
        background: none;
        cursor: pointer;
    }

    .icon-mirrored {
        transform: scaleX(-1);
    }

    .admin-button {
        position: absolute;
        left: 50%;
        top: 0;
        transform: translateX(-50%);
        display: flex;
        align-items: center;
        gap: 8px;
        background: var(--color-primary);
        color: white;
        border: none;
        border-radius: 19px;
        padding: 6px 12px;
        font-size: 16px;
        cursor: pointer;
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
    }
    
    .admin-text {
        white-space: nowrap;
        font-weight: medium;
        color: white;
    }
    
    .admin-icon {
        width: 17px;
        height: 17px;
        background: white;
    }
    
    .question-icon {
        width: 17px;
        height: 17px;
        background: white;
        opacity: 0.5;
    }
</style>
