<script lang="ts">
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
    // const STEP_PROFILE_PICTURE = 'profile_picture'; // Moved to settings
    const STEP_ONE_TIME_CODES = 'one_time_codes';
    const STEP_BACKUP_CODES = 'backup_codes';
    const STEP_RECOVERY_KEY = 'recovery_key';
    const STEP_TFA_APP_REMINDER = 'tfa_app_reminder';
    const STEP_SETTINGS = 'settings';
    const STEP_MATE_SETTINGS = 'mate_settings';
    const STEP_CREDITS = 'credits';
    const STEP_PAYMENT = 'payment';
    const STEP_AUTO_TOP_UP = 'auto_top_up';
    const STEP_COMPLETION = 'completion';

    const stepSequence = [
        STEP_ALPHA_DISCLAIMER, STEP_BASICS, STEP_CONFIRM_EMAIL, STEP_SECURE_ACCOUNT, STEP_PASSWORD,
        STEP_ONE_TIME_CODES, STEP_TFA_APP_REMINDER, STEP_BACKUP_CODES, STEP_RECOVERY_KEY, // STEP_PROFILE_PICTURE,
        STEP_CREDITS, STEP_PAYMENT, STEP_AUTO_TOP_UP, STEP_COMPLETION
    ];

    // Props using Svelte 5 runes mode with callback props
    let {
        mode = 'signup', // 'login' | 'signup' - determines which navigation to show
        showSkip = false,
        currentStep = STEP_BASICS,
        selectedAppName = null,
        showAdminButton = false,
        isAppSaved = false,
        onback = () => {},
        onstep = (event: { step: string }) => {},
        onskip = () => {},
        onlogout = () => {},
        onDemoClick = () => {} // Handler for login mode "Demo" button
    }: {
        mode?: 'login' | 'signup',
        showSkip?: boolean,
        currentStep?: string,
        selectedAppName?: string | null,
        showAdminButton?: boolean,
        isAppSaved?: boolean,
        onback?: () => void,
        onstep?: (event: { step: string }) => void,
        onskip?: () => void,
        onlogout?: () => void,
        onDemoClick?: () => void
    } = $props();

    /**
     * Handle back button click - behavior differs based on mode
     * Login mode: calls onDemoClick to return to demo
     * Signup mode: handles step navigation based on current step
     */
    function handleBackClick() {
        // Login mode: always call demo click handler
        if (mode === 'login') {
            console.log('[SignupNav] Login mode - calling onDemoClick');
            onDemoClick();
            return;
        }
        
        // Signup mode: handle step-based navigation
        console.log('[SignupNav] handleBackClick called, currentStep:', currentStep);
        if (currentStep === STEP_BASICS || currentStep === STEP_ALPHA_DISCLAIMER) {
            console.log('[SignupNav] Calling onback()');
            onback();
        } else if (currentStep === STEP_ONE_TIME_CODES) {
            onlogout();
        } else if (currentStep === STEP_SECURE_ACCOUNT) {
            // Special case: Go back from Secure Account to Basics (skipping confirm email)
            onstep({ step: STEP_BASICS });
        } else {
            const currentIndex = stepSequence.indexOf(currentStep);
            if (currentIndex > 0) {
                onstep({ step: stepSequence[currentIndex - 1] });
            }
        }
    }

    function handleSkipClick() {
        // Profile picture step removed
        if (currentStep === STEP_ONE_TIME_CODES && $userProfile.tfa_enabled) {
            onstep({ step: STEP_TFA_APP_REMINDER });
    } else if (currentStep === STEP_TFA_APP_REMINDER) {
         // Always go to backup codes step next, regardless of whether an app is selected
         onstep({ step: STEP_BACKUP_CODES });
        } else if (currentStep === STEP_SETTINGS && $userProfile.consent_privacy_and_apps_default_settings) {
            onstep({ step: STEP_MATE_SETTINGS });
        } else if (currentStep === STEP_MATE_SETTINGS && $userProfile.consent_mates_default_settings) {
            onstep({ step: STEP_CREDITS });
        } else if (currentStep === STEP_CREDITS) {
            console.debug('Skip and show demo first');
            // Custom action for credits step - will be replaced later with real action
        } else {
            // Default skip action
            onskip();
        }
    }

    function openSelfHostedDocs() {
        const docsUrl = getWebsiteUrl(routes.docs.selfhosted);
        window.open(docsUrl, '_blank');
    }

    /**
     * Get navigation text based on mode and step
     * Login mode: always returns "Demo"
     * Signup mode: returns step-specific text
     */
    function getNavText(step: string) {
        // Login mode: always show "Demo"
        if (mode === 'login') {
            return $_('login.demo.text');
        }
        
        // Signup mode: show step-specific text
        // Show "Demo" for first two steps since we now have Login/Signup tabs at the top
        if (step === STEP_ALPHA_DISCLAIMER) return $_('login.demo.text');
        if (step === STEP_BASICS) return $_('login.demo.text');
        if (step === STEP_CONFIRM_EMAIL) return $_('signup.sign_up.text');
        if (step === STEP_SECURE_ACCOUNT) return $_('signup.sign_up.text');
        if (step === STEP_PASSWORD) return $_('signup.secure_your_account.text');
        if (step === STEP_ONE_TIME_CODES) return $_('settings.logout.text');
        if (step === STEP_TFA_APP_REMINDER) return $_('signup.connect_2fa_app.text');
        if (step === STEP_BACKUP_CODES) return $_('signup.2fa_app_reminder.text');
        if (step === STEP_RECOVERY_KEY) return $_('signup.backup_codes.text');
        // if (step === STEP_PROFILE_PICTURE) return $_('settings.logout.text'); // Removed
        if (step === STEP_SETTINGS) return $_('signup.upload_profile_picture.text');
        if (step === STEP_MATE_SETTINGS) return $_('signup.settings.text');
        // Credits step: show previous step text (recovery_key for both passkey and password flows)
        if (step === STEP_CREDITS) return $_('signup.recovery_key.text');
        if (step === STEP_PAYMENT) return $_('signup.select_credits.text');
        return $_('signup.sign_up.text');
    }

// Update the reactive skipButtonText for different steps and states using Svelte 5 runes
let skipButtonText = $derived(
    (currentStep === STEP_ONE_TIME_CODES && $userProfile.tfa_enabled) ? $_('signup.next.text') :
    // Only show "Next" for TFA app reminder if an app has been selected AND saved
    (currentStep === STEP_TFA_APP_REMINDER && selectedAppName && selectedAppName.trim() !== '' && isAppSaved) ? $_('signup.next.text') :
    (currentStep === STEP_SETTINGS && $userProfile.consent_privacy_and_apps_default_settings) ? $_('signup.next.text') :
    (currentStep === STEP_MATE_SETTINGS && $userProfile.consent_mates_default_settings) ? $_('signup.next.text') :
    // (currentStep === STEP_CREDITS) ? $_('signup.skip_and_show_demo_first.text') : // Credits step skip demo # TODO implement this later
    $_('signup.skip.text') // Default skip text
);

    // Determine if the skip/next button should be shown using Svelte 5 runes
    // Login mode: never show skip button
    // Signup mode: Show if:
    // - One Time Codes step AND TFA is already enabled OR
    // - TFA App Reminder step AND (no app selected OR app selected and saved) OR
    // - Settings step AND consent_privacy_and_apps_default_settings is true OR
    // - Mate Settings step AND consent_mates_default_settings is true OR
    // - Credits step AND gift check is done AND NO gift is available OR
    // - showSkip prop is true AND it's not one of the special steps
    let showActualSkipButton = $derived(
        mode === 'login' ? false : (
            (currentStep === STEP_ONE_TIME_CODES && $userProfile.tfa_enabled) ||
            (currentStep === STEP_TFA_APP_REMINDER && (!selectedAppName || selectedAppName.trim() === '' || isAppSaved)) ||
            (currentStep === STEP_SETTINGS && $userProfile.consent_privacy_and_apps_default_settings) ||
            (currentStep === STEP_MATE_SETTINGS && $userProfile.consent_mates_default_settings) ||
            // (currentStep === STEP_CREDITS && !$isLoadingGiftCheck && !$hasGiftForSignup) || // Show skip/demo only if NO gift available # TODO implement this later
            (showSkip && ![STEP_ONE_TIME_CODES, STEP_TFA_APP_REMINDER, STEP_SETTINGS, STEP_MATE_SETTINGS, STEP_CREDITS].includes(currentStep))
        )
    );
</script>

<div class="nav-area">
    <button class="nav-button" onclick={handleBackClick} aria-label={mode === 'login' ? $_('login.demo.text') : getNavText(currentStep)}>
        <div class="clickable-icon icon_back"></div>
        {getNavText(currentStep)}
    </button>
    
    {#if mode === 'signup' && showAdminButton}
        <button class="admin-button" onclick={openSelfHostedDocs}>
            <div class="clickable-icon icon_server admin-icon"></div>
            <span class="admin-text">{$_('signup.server_admin.text')}</span>
            <div class="clickable-icon icon_question question-icon"></div>
        </button>
    {/if}
    
    {#if showActualSkipButton}
        <button class="nav-button" onclick={handleSkipClick}>
            {skipButtonText}
            <div class="clickable-icon icon_back icon-mirrored"></div>
        </button>
    {/if}
</div>

<style>
    .nav-area {
        top: 0;
        left: 0;
        right: 0;
        height: 48px;
        z-index: 1;
        display: flex;
        justify-content: space-between;
    }
    
    /* Ensure consistent positioning on mobile - match global nav-area styles */
    @media (max-width: 600px) {
        .nav-area {
            top: 0;
            left: 0; /* Ensure left alignment is consistent */
            right: 0; /* Ensure right alignment is consistent */
            background-color: transparent;
            z-index: 10;
            padding: 10px;
            margin: -10px -10px 0 -10px; /* Offset padding to maintain full width */
            margin-top: 0; /* Ensure it sticks to the very top */
            width: 100%; /* Ensure full width */
            box-sizing: border-box; /* Include padding in width calculation */
        }
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
