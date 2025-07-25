<script lang="ts">
    import { createEventDispatcher, tick } from 'svelte';
    import { getWebsiteUrl, routes } from '../../config/links';
    import { _ } from 'svelte-i18n';
    import { tooltip } from '../../actions/tooltip';
    import Basics from './steps/basics/Basics.svelte';
    import SignupNav from './SignupNav.svelte';
    import { fade, fly } from 'svelte/transition';
    import { cubicInOut } from 'svelte/easing';
    import ExpandableHeader from './ExpandableHeader.svelte';
    import { MOBILE_BREAKPOINT } from '../../styles/constants';
    import { isMenuOpen } from '../../stores/menuState';
    import { signupStore, clearSignupData } from '../../stores/signupStore';
    
    // Import signup state stores
    import { isSignupSettingsStep, isInSignupProcess, isSettingsStep, currentSignupStep, showSignupFooter } from '../../stores/signupState';
    
    // Step name constants
    const STEP_ALPHA_DISCLAIMER = 'alpha_disclaimer';
    const STEP_BASICS = 'basics';
    const STEP_CONFIRM_EMAIL = 'confirm_email';
    const STEP_SECURE_ACCOUNT = 'secure_account';
    const STEP_PASSWORD = 'password';
    const STEP_PROFILE_PICTURE = 'profile_picture';
    const STEP_ONE_TIME_CODES = 'one_time_codes';
    const STEP_BACKUP_CODES = 'backup_codes';
    const STEP_RECOVERY_KEY = 'recovery_key';
    const STEP_TFA_APP_REMINDER = 'tfa_app_reminder';
    const STEP_SETTINGS = 'settings';
    const STEP_MATE_SETTINGS = 'mate_settings';
    const STEP_CREDITS = 'credits';
    const STEP_PAYMENT = 'payment';
    const STEP_COMPLETION = 'completion';
    import { authStore, isCheckingAuth } from '../../stores/authStore';
    import { isLoggingOut } from '../../stores/signupState';
    import { updateProfile } from '../../stores/userProfile';
    import { panelState } from '../../stores/panelStateStore'; // Added panelState import

    // Dynamic imports for step contents
    import ConfirmEmailTopContent from './steps/confirmemail/ConfirmEmailTopContent.svelte';
    import SecureAccountTopContent from './steps/secureaccount/SecureAccountTopContent.svelte';
    import PasswordTopContent from './steps/password/PasswordTopContent.svelte';
    import ProfilePictureTopContent from './steps/profilepicture/ProfilePictureTopContent.svelte';
    import OneTimeCodesTopContent from './steps/onetimecodes/OneTimeCodesTopContent.svelte';
    import BackupCodesTopContent from './steps/backupcodes/BackupCodesTopContent.svelte';
    import TfaAppReminderTopContent from './steps/tfaappreminder/TfaAppReminderTopContent.svelte';
    import SettingsTopContent from './steps/settings/SettingsTopContent.svelte';
    import MateSettingsTopContent from './steps/matesettings/MateSettingsTopContent.svelte';
    import CreditsTopContent from './steps/credits/CreditsTopContent.svelte';
    import PaymentTopContent from './steps/payment/PaymentTopContent.svelte';
    import AlphaDisclaimerContent from './steps/alpha_disclaimer/AlphaDisclaimerContent.svelte';
    import ConfirmEmailBottomContent from './steps/confirmemail/ConfirmEmailBottomContent.svelte';
    import PasswordBottomContent from './steps/password/PasswordBottomContent.svelte';
    import ProfilePictureBottomContent from './steps/profilepicture/ProfilePictureBottomContent.svelte';
    import OneTimeCodesBottomContent from './steps/onetimecodes/OneTimeCodesBottomContent.svelte';
    import BackupCodesBottomContent from './steps/backupcodes/BackupCodesBottomContent.svelte';
    import TfaAppReminderBottomContent from './steps/tfaappreminder/TfaAppReminderBottomContent.svelte';
    import SettingsBottomContent from './steps/settings/SettingsBottomContent.svelte';
    import MateSettingsBottomContent from './steps/matesettings/MateSettingsBottomContent.svelte';
    import CreditsBottomContent from './steps/credits/CreditsBottomContent.svelte';
    import PaymentBottomContent from './steps/payment/PaymentBottomContent.svelte';
    import RecoveryKeyTopContent from './steps/recoverykey/RecoveryKeyTopContent.svelte';
    import RecoveryKeyBottomContent from './steps/recoverykey/RecoveryKeyBottomContent.svelte';

    import SignupStatusbar from './SignupStatusbar.svelte';

    const dispatch = createEventDispatcher();

    // Initialize step from store
    let currentStep = STEP_ALPHA_DISCLAIMER;
    let direction: 'forward' | 'backward' = 'forward';
    let isInviteCodeValidated = false;
    let is_admin = false; // Add this to track admin status
    // let previousStep = 1; // Removed, will pass previous value directly

    // Lift form state up
    let selectedAppName: string | null = null;
    let selectedCreditsAmount: number = 21000; // Default credits amount
    let selectedPrice: number = 20; // Default price
    let selectedCurrency: string = 'EUR'; // Default currency
    let isGiftFlow: boolean = false; // Track if it's a gift flow
    let limitedRefundConsent = false;

    // Animation parameters
    const flyParams = {
        duration: 400,
        x: 100,
        easing: cubicInOut
    };

    const stepSequence = [
        STEP_ALPHA_DISCLAIMER, STEP_BASICS, STEP_CONFIRM_EMAIL, STEP_SECURE_ACCOUNT, STEP_PASSWORD, 
        STEP_ONE_TIME_CODES, STEP_TFA_APP_REMINDER, STEP_BACKUP_CODES, STEP_RECOVERY_KEY, STEP_PROFILE_PICTURE,
        STEP_CREDITS, STEP_PAYMENT, STEP_COMPLETION
    ];

    let isImageProcessing = false;
    let isImageUploading = false;

    // State to track if payment form is showing (after consent is given)
    let paymentFormVisible = false;
    let refundConsentGiven = false;

    // Track both consent and the current visible screen
    let paymentConsentGiven = false;      // Has consent been given?
    let showingPaymentForm = false;       // Is payment form currently visible?

    // New state to track payment processing status
    let paymentState = 'idle';

    // Reference for OneTimeCodesBottomContent instance
    let oneTimeCodesBottomContentRef: OneTimeCodesBottomContent | null = null;
    
    // Password form state
    let passwordFormData = {
        password: '',
        passwordRepeat: '',
        isValid: false
    };
    
    // Create derived state for showing/hiding nav and status bar
    $: showUIControls = paymentState !== 'processing' && paymentState !== 'success';
    
    // Fade transition parameters - make them slower for better visibility
    const fadeParams = {
        duration: 600
    };

    // Update stores when component is mounted and destroyed
    import { onMount, onDestroy } from 'svelte';
    
    onMount(() => {
        isInSignupProcess.set(true);
        
        // Check if we're starting a fresh signup from the login screen
        // If we are, make sure we're at the alpha disclaimer step
        if (!$authStore.isAuthenticated) {
            currentSignupStep.set(STEP_ALPHA_DISCLAIMER);
            currentStep = STEP_ALPHA_DISCLAIMER;
        } else {
            // Otherwise, get step from store if set (for authenticated users continuing signup)
            currentStep = $currentSignupStep || STEP_ALPHA_DISCLAIMER;
        }
        
        updateSettingsStep(''); // Provide empty string as initial prevStepValue
        
        // Update footer visibility based on step
        const settingsSteps = [STEP_SETTINGS, STEP_MATE_SETTINGS, STEP_CREDITS, STEP_PAYMENT, STEP_COMPLETION];
        showSignupFooter.set(!settingsSteps.includes(currentStep));
    });
    
    onDestroy(() => {
        isInSignupProcess.set(false);
        isSignupSettingsStep.set(false);
        showSignupFooter.set(true); // Reset footer state on destroy
    });

    // Function to update settings step state and close panel if necessary
    function updateSettingsStep(prevStepValue: string) {
        // Check if current step should show settings
        const settingsSteps = [STEP_SETTINGS, STEP_MATE_SETTINGS, STEP_CREDITS, STEP_PAYMENT];
        const shouldShowSettings = settingsSteps.includes(currentStep);
        isSignupSettingsStep.set(shouldShowSettings);

        // Check if the previous step was a settings step
        const wasShowingSettings = settingsSteps.includes(prevStepValue);

        // If leaving settings steps, close the menu using panelState
        if (wasShowingSettings && !shouldShowSettings) {
            panelState.closeSettings();
        }
        // No need to handle opening or preserving state here,
        // as panelStateStore manages the global state.
    }

    // Removed reactive block for previousStep handling

    function handleSwitchToLogin() {
        // Clear the signup store data when switching to login
        clearSignupData();
        dispatch('switchToLogin');
    }

    function handleSkip() {
        if (currentStep === STEP_PROFILE_PICTURE) {
            goToStep(STEP_ONE_TIME_CODES);
        } else if (currentStep === STEP_TFA_APP_REMINDER) {
            // Skip settings and mate settings - go directly to credits
            goToStep(STEP_CREDITS);
        }
    }

    async function handleStep(event: CustomEvent<{step: string, credits_amount?: number, price?: number, currency?: string, isGift?: boolean}>) { // Add isGift to type
        const newStep = event.detail.step;
        const oldStep = currentStep; // Capture old step value
        
        const oldIndex = stepSequence.indexOf(oldStep);
        const newIndex = stepSequence.indexOf(newStep);
        direction = newIndex > oldIndex ? 'forward' : 'backward';

        // Reset selectedAppName when navigating away from TFA app reminder step
        if (oldStep === STEP_TFA_APP_REMINDER && newStep !== STEP_TFA_APP_REMINDER) {
            selectedAppName = null;
        }

        if (direction === 'backward' && newStep === STEP_BASICS) {
            signupStore.update(s => ({ ...s, password: '' }));
        }

        isGiftFlow = event.detail.isGift ?? false; // Capture isGift status, default to false
        currentStep = newStep; // Update local step
        currentSignupStep.set(newStep); // Update the global store
        
        await tick(); // Wait for Svelte to process state changes before proceeding
        updateSettingsStep(oldStep); // Call update function with old step value
        
        // Update footer visibility based on step
        const settingsSteps = [STEP_SETTINGS, STEP_MATE_SETTINGS, STEP_CREDITS, STEP_PAYMENT, STEP_COMPLETION];
        showSignupFooter.set(!settingsSteps.includes(newStep));

        // If credits amount is provided (from step 9 to 10), store it
        if (event.detail.credits_amount !== undefined) {
            selectedCreditsAmount = event.detail.credits_amount;
        }

        // Store price and currency if provided
        if (event.detail.price !== undefined) {
            selectedPrice = event.detail.price;
        }

        if (event.detail.currency !== undefined) {
            selectedCurrency = event.detail.currency;
        }
        
        // updateSettingsStep() is called via the reactive statement
    }

    function handleSelectedApp(event: CustomEvent<{ appName: string }>) {
        selectedAppName = event.detail.appName;
    }

    async function goToStep(step: string) {
        const oldStep = currentStep; // Capture old step value
        
        const oldIndex = stepSequence.indexOf(oldStep);
        const newIndex = stepSequence.indexOf(step);
        direction = newIndex > oldIndex ? 'forward' : 'backward';

        // Reset selectedAppName when navigating away from TFA app reminder step
        if (oldStep === STEP_TFA_APP_REMINDER && step !== STEP_TFA_APP_REMINDER) {
            selectedAppName = null;
        }

        if (direction === 'backward' && step === STEP_BASICS) {
            signupStore.update(s => ({ ...s, password: '' }));
        }

        currentStep = step;
        currentSignupStep.set(step); // Also update the store here
        await tick(); // Add tick here too for consistency
        updateSettingsStep(oldStep); // Call update function with old step value
        
        // Update footer visibility based on step
        const settingsSteps = [STEP_SETTINGS, STEP_MATE_SETTINGS, STEP_CREDITS, STEP_PAYMENT, STEP_COMPLETION];
        showSignupFooter.set(!settingsSteps.includes(step));
    }

    async function handleLogout() {
        try {
            isLoggingOut.set(true);
            isInSignupProcess.set(false);
            
            // Reset signup step to alpha disclaimer when logging out
            currentSignupStep.set(STEP_ALPHA_DISCLAIMER);

            await authStore.logout({
                beforeLocalLogout: () => {
                    isCheckingAuth.set(false);
                },

                afterServerCleanup: async () => {
                    // Longer delay to ensure UI transitions complete correctly
                    await new Promise(resolve => setTimeout(resolve, 500));
                }
            });
            
            // Keep the logging out state for a moment longer to prevent UI flash
            setTimeout(() => {
                isLoggingOut.set(false);
            }, 300);
            
            // Switch to login view after logout is complete
            showSignupFooter.set(true); // Ensure footer is shown after logout
            dispatch('switchToLogin');
        } catch (error) {
            console.error('Error during logout:', error);
            showSignupFooter.set(true); // Ensure footer is shown even on error
            // Even on error, ensure we exit signup mode properly
            isInSignupProcess.set(false);
            
            // Reset signup step to alpha disclaimer when logging out
            currentSignupStep.set(STEP_ALPHA_DISCLAIMER);
            
            authStore.logout();
            
            // Reset logging out state
            setTimeout(() => {
                isLoggingOut.set(false);
            }, 300);
            
            dispatch('switchToLogin');
        }
    }

    function handleImageUploading(event: CustomEvent<{isProcessing: boolean, isUploading: boolean}>) {
        isImageProcessing = event.detail.isProcessing;
        isImageUploading = event.detail.isUploading;
    }

    // Handle limited refund consent from Step10TopContent
    function handleRefundConsent(event: CustomEvent<{consented: boolean}>) {
        limitedRefundConsent = event.detail.consented;
        paymentConsentGiven = event.detail.consented;
    }
    
    // Track when payment form becomes visible or hidden
    function handlePaymentFormVisibilityChange(event: CustomEvent<{visible: boolean}>) {
        showingPaymentForm = event.detail.visible;
    }
    
    // Handle open refund info request
    function handleOpenRefundInfo() {
        window.open(getWebsiteUrl(routes.docs.userGuide_signup_10_1), '_blank');
    }
    
    // Handle payment submission
    function handlePaymentSubmission(event: CustomEvent<{
        nameOnCard: string,
        cardNumber: string,
        expireDate: string,
        cvv: string,
        amount: number
    }>) {
        console.debug('Processing payment...', event.detail);
        // Implement payment submission logic here
        
        // For demo, simulate success and move to completion step
        goToStep(STEP_COMPLETION);
    }

    // Handle payment state changes
    function handlePaymentStateChange(event) {
        paymentState = event.detail.state;
        
        // If payment failed, reset to idle state after a short delay
        if (paymentState === 'failure') {
            setTimeout(() => {
                paymentState = 'idle';
            }, 500);
        } else if (paymentState === 'success') { // Add success handling
            console.debug("Payment successful, transitioning to chat in 2 seconds...");
            // Introduce a 2-second delay before transitioning
            setTimeout(() => {
                // Update last_opened to signal completion of signup flow
                updateProfile({ last_opened: '/chat/new' });
                // Signal completion of signup process
                isInSignupProcess.set(false);
                if (window.innerWidth >= MOBILE_BREAKPOINT) {
                    isMenuOpen.set(true);
                }
                // The reactive statements in +page.svelte and ActiveChat.svelte
                // should handle the transition to the chat view when isInSignupProcess is false
                console.debug("Transitioning to chat now.");
            }, 2000); // 2000 milliseconds = 2 seconds
        }
    }

    // Handler for action clicks in Step4TopContent
    function handleActionClicked() {
        if (oneTimeCodesBottomContentRef) {
            oneTimeCodesBottomContentRef.focusInput();
        }
    }
    
    // Handle password change from PasswordTopContent
    function handlePasswordChange(event: CustomEvent<{password: string, passwordRepeat: string, isValid: boolean}>) {
        passwordFormData = event.detail;
    }

    // Get the appropriate help documentation link based on current step and validation state
    $: helpLink = getWebsiteUrl(
        currentStep === STEP_BASICS
            ? (!isInviteCodeValidated ? routes.docs.userGuide_signup_1a : routes.docs.userGuide_signup_1b)
            : currentStep === STEP_PAYMENT
                ? (showingPaymentForm ? routes.docs.userGuide_signup_10_2 : routes.docs.userGuide_signup_10_1)
                : routes.docs[`userGuide_signup_${getStepNumber(currentStep)}`] // Temporarily use numbers for docs
    );
    
    // Helper function to get step number for documentation links (temporary)
    function getStepNumber(stepName) {
        const stepMap = {
            [STEP_ALPHA_DISCLAIMER]: 0,
            [STEP_BASICS]: 1,
            [STEP_CONFIRM_EMAIL]: 2,
            [STEP_PROFILE_PICTURE]: 3,
            [STEP_ONE_TIME_CODES]: 4,
            [STEP_BACKUP_CODES]: 5,
            [STEP_TFA_APP_REMINDER]: 6,
            [STEP_SETTINGS]: 7,
            [STEP_MATE_SETTINGS]: 8,
            [STEP_CREDITS]: 9,
            [STEP_PAYMENT]: 10,
            [STEP_COMPLETION]: 11
        };
        return stepMap[stepName] || 0;
    }

    // Update showSkip logic to show for specific steps
    $: showSkip = currentStep === STEP_PROFILE_PICTURE || 
                  currentStep === STEP_TFA_APP_REMINDER || 
                  currentStep === STEP_CREDITS;

    // Show expanded header on credits and payment steps
    $: showExpandedHeader = currentStep === STEP_CREDITS || currentStep === STEP_PAYMENT;

    // For payment step and backup codes step, use expanded height for the top content wrapper
    $: isExpandedTopContent = currentStep === STEP_PAYMENT || currentStep === STEP_SECURE_ACCOUNT || currentStep === STEP_RECOVERY_KEY;
</script>

<div class="signup-content visible" in:fade={{ duration: 400 }}>
    {#if showUIControls}
        <div transition:fade={fadeParams}>
            <SignupNav 
                on:back={handleSwitchToLogin}
                on:step={handleStep}
                on:skip={handleSkip}
                on:logout={handleLogout}
                {showSkip}
                {currentStep}
                {selectedAppName}
                showAdminButton={is_admin && currentStep === STEP_BASICS && isInviteCodeValidated}
            />
        </div>
    {/if}

    <div>
        {#if currentStep === STEP_ALPHA_DISCLAIMER}
            <AlphaDisclaimerContent on:continue={() => goToStep(STEP_BASICS)} />
        {:else if currentStep === STEP_BASICS}
            <Basics 
                on:switchToLogin={handleSwitchToLogin}
                bind:isValidated={isInviteCodeValidated}
                bind:is_admin={is_admin}
                on:next={() => goToStep(STEP_CONFIRM_EMAIL)}
                on:requestSwitchToLogin={handleSwitchToLogin}
            />
        {:else}
            <div class="step-layout">
                <!-- Top content wrapper -->
                <div class="top-content-wrapper" class:expanded={isExpandedTopContent}>
                    <div class="top-content">
                        <ExpandableHeader 
                            visible={showExpandedHeader} 
                            credits_amount={currentStep === STEP_PAYMENT ? selectedCreditsAmount : undefined}
                        />
                        <div class="content-slider">
                            {#key currentStep}
                                <div 
                                    class="slide"
                                    in:fly={{...flyParams, x: direction === 'forward' ? 100 : -100}}
                                    out:fly={{...flyParams, x: direction === 'forward' ? -100 : 100}}
                                >
                                    {#if currentStep === STEP_CONFIRM_EMAIL}
                                        <ConfirmEmailTopContent />
                                    {:else if currentStep === STEP_SECURE_ACCOUNT}
                                        <SecureAccountTopContent on:step={handleStep} />
                                    {:else if currentStep === STEP_PASSWORD}
                                        <PasswordTopContent on:passwordChange={handlePasswordChange} />
                                    {:else if currentStep === STEP_PROFILE_PICTURE}
                                        <ProfilePictureTopContent
                                            isProcessing={isImageProcessing}
                                            isUploading={isImageUploading}
                                        />
                                    {:else if currentStep === STEP_ONE_TIME_CODES}
                                        <OneTimeCodesTopContent on:actionClicked={handleActionClicked} />
                                    {:else if currentStep === STEP_BACKUP_CODES}
                                        <BackupCodesTopContent {selectedAppName} />
                                    {:else if currentStep === STEP_RECOVERY_KEY}
                                        <RecoveryKeyTopContent />
                                    {:else if currentStep === STEP_TFA_APP_REMINDER}
                                        <TfaAppReminderTopContent {selectedAppName} />
                                    {:else if currentStep === STEP_SETTINGS}
                                        <SettingsTopContent />
                                    {:else if currentStep === STEP_MATE_SETTINGS}
                                        <MateSettingsTopContent />
                                    {:else if currentStep === STEP_CREDITS}
                                        <CreditsTopContent />
                                    {:else if currentStep === STEP_PAYMENT}
                                        <PaymentTopContent
                                            credits_amount={selectedCreditsAmount}
                                            price={selectedPrice}
                                            currency={selectedCurrency}
                                            isGift={isGiftFlow}
                                            on:consentGiven={handleRefundConsent}
                                            on:paymentFormVisibility={handlePaymentFormVisibilityChange}
                                            on:openRefundInfo={handleOpenRefundInfo}
                                            on:payment={handlePaymentSubmission}
                                            on:paymentStateChange={handlePaymentStateChange}
                                        />
                                    {/if}
                                </div>
                            {/key}
                        </div>
                    </div>
                </div>

                <!-- Bottom content wrapper -->
                <div class="bottom-content-wrapper" class:reduced={isExpandedTopContent}>
                    <div class="content-slider">
                        {#key currentStep}
                            <div 
                                class="slide"
                                in:fly={{...flyParams, x: direction === 'forward' ? 100 : -100}}
                                out:fly={{...flyParams, x: direction === 'forward' ? -100 : 100}}
                            >
                                {#if currentStep === STEP_ONE_TIME_CODES}
                                    <OneTimeCodesBottomContent
                                        bind:this={oneTimeCodesBottomContentRef}
                                        on:step={handleStep}
                                    />
                                {:else}
                                    {#if currentStep === STEP_PASSWORD}
                                        <PasswordBottomContent
                                            on:step={handleStep}
                                            password={passwordFormData.password}
                                            passwordRepeat={passwordFormData.passwordRepeat}
                                            isFormValid={passwordFormData.isValid}
                                        />
                                    {:else}
                                        <svelte:component
                                            this={
                                                    currentStep === STEP_CONFIRM_EMAIL ? ConfirmEmailBottomContent :
                                                    currentStep === STEP_PROFILE_PICTURE ? ProfilePictureBottomContent :
                                                    // OneTimeCodes handled above
                                                    currentStep === STEP_BACKUP_CODES ? BackupCodesBottomContent :
                                                    currentStep === STEP_RECOVERY_KEY ? RecoveryKeyBottomContent :
                                                    currentStep === STEP_TFA_APP_REMINDER ? TfaAppReminderBottomContent :
                                                    currentStep === STEP_SETTINGS ? SettingsBottomContent :
                                                    currentStep === STEP_MATE_SETTINGS ? MateSettingsBottomContent :
                                                    currentStep === STEP_CREDITS ? CreditsBottomContent :
                                                    currentStep === STEP_PAYMENT ? PaymentBottomContent :
                                                   null}
                                            on:step={handleStep}
                                            on:uploading={handleImageUploading}
                                            on:selectedApp={handleSelectedApp}
                                        />
                                    {/if}
                                {/if}
                            </div>
                        {/key}
                    </div>
                </div>
            </div>
        {/if}
    </div>

    {#if showUIControls}
        <div class="status-wrapper" class:hidden={currentStep === STEP_BASICS || currentStep === STEP_ALPHA_DISCLAIMER} transition:fade={fadeParams}>
            <SignupStatusbar currentStepName={currentStep} />
        </div>
    {/if}

    {#if showUIControls}
        <!-- NOTE: temporary hidden both because of response design issues regardings its position and also because docs don't exist yet. -->
        <!-- <div class="help-wrapper" transition:fade={fadeParams}>
            <a href={helpLink} 
               target="_blank" 
               use:tooltip 
               rel="noopener noreferrer" 
               class="help-button-container" 
               aria-label={$_('documentation.open_documentation.text')}
            >
                <div class="help-button"></div>
            </a>
        </div> -->
    {:else}
        <div class="help-wrapper hidden"></div>
    {/if}
</div>

<style>
    /* Add these styles to your existing CSS */
    .top-content-wrapper {
        transition: height 0.6s cubic-bezier(0.22, 1, 0.36, 1);
    }
    
    .top-content-wrapper.expanded {
        height: 640px;
        max-height: calc(100vh - 265px);
    }

    @media (max-height: 680px) {
        .top-content-wrapper.expanded {
            max-height: 88vh;
        }
    }
    
    /* Add a class for hiding elements with transition */
    .hidden {
        opacity: 0;
        visibility: hidden;
        transition: opacity 0.6s ease, visibility 0.6s ease;
    }
</style>
