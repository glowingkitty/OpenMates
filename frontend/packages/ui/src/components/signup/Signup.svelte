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
    import { signupStore, clearSignupData, clearIncompleteSignupData } from '../../stores/signupStore';
    // Import crypto service cleanup functions for secure logout
    import { clearKeyFromStorage, clearAllEmailData } from '../../services/cryptoService';
    
    // Import signup state stores
    import { isSignupSettingsStep, isInSignupProcess, isSettingsStep, currentSignupStep, showSignupFooter, getPathFromStep, STEP_ALPHA_DISCLAIMER } from '../../stores/signupState';
    import { isRecoveryKeyCreationActive } from '../../stores/recoveryKeyUIState';
    
    // Step name constants
    const STEP_BASICS = 'basics';
    const STEP_CONFIRM_EMAIL = 'confirm_email';
    const STEP_SECURE_ACCOUNT = 'secure_account';
    const STEP_PASSWORD = 'password';
    const STEP_PASSKEY_PRF_ERROR = 'passkey_prf_error';
    // const STEP_PROFILE_PICTURE = 'profile_picture'; // Moved to settings menu
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
    import { authStore, isCheckingAuth } from '../../stores/authStore';
    import { isLoggingOut } from '../../stores/signupState';
    import { updateProfile } from '../../stores/userProfile';
    import { panelState } from '../../stores/panelStateStore'; // Added panelState import
    import { webSocketService } from '../../services/websocketService'; // Import WebSocket service
    import { chatSyncService } from '../../services/chatSyncService'; // Import chat sync service for updating last_opened

    // Dynamic imports for step contents
    import ConfirmEmailTopContent from './steps/confirmemail/ConfirmEmailTopContent.svelte';
    import SecureAccountTopContent from './steps/secureaccount/SecureAccountTopContent.svelte';
    import PasswordTopContent from './steps/password/PasswordTopContent.svelte';
    import PasskeyRegistrationTopContent from './steps/passkey/PasskeyRegistrationTopContent.svelte';
    import PasskeyPRFError from './steps/passkey/PasskeyPRFError.svelte';
    // import ProfilePictureTopContent from './steps/profilepicture/ProfilePictureTopContent.svelte'; // Moved to settings
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
    import PasskeyRegistrationBottomContent from './steps/passkey/PasskeyRegistrationBottomContent.svelte';
    // import ProfilePictureBottomContent from './steps/profilepicture/ProfilePictureBottomContent.svelte'; // Moved to settings
    import OneTimeCodesBottomContent from './steps/onetimecodes/OneTimeCodesBottomContent.svelte';
    import BackupCodesBottomContent from './steps/backupcodes/BackupCodesBottomContent.svelte';
    import TfaAppReminderBottomContent from './steps/tfaappreminder/TfaAppReminderBottomContent.svelte';
    import SettingsBottomContent from './steps/settings/SettingsBottomContent.svelte';
    import MateSettingsBottomContent from './steps/matesettings/MateSettingsBottomContent.svelte';
    import CreditsBottomContent from './steps/credits/CreditsBottomContent.svelte';
    import PaymentBottomContent from './steps/payment/PaymentBottomContent.svelte';
    import RecoveryKeyTopContent from './steps/recoverykey/RecoveryKeyTopContent.svelte';
    import RecoveryKeyBottomContent from './steps/recoverykey/RecoveryKeyBottomContent.svelte';
    import AutoTopUpTopContent from './steps/autotopup/AutoTopUpTopContent.svelte';
    import AutoTopUpBottomContent from './steps/autotopup/AutoTopUpBottomContent.svelte';

    import SignupStatusbar from './SignupStatusbar.svelte';

    // Import API utilities
    import { getApiUrl, apiEndpoints } from '../../config/api';

    const dispatch = createEventDispatcher();

    // Initialize step from store using Svelte 5 runes
    let currentStep = $state(STEP_ALPHA_DISCLAIMER);
    let direction = $state<'forward' | 'backward'>('forward');
    let isInviteCodeValidated = $state(false);
    let is_admin = $state(false); // Add this to track admin status
    // let previousStep = 1; // Removed, will pass previous value directly
    
    // Reference to signup-content element for scrolling
    let signupContentElement: HTMLDivElement;

    // Lift form state up using Svelte 5 runes
    let selectedAppName = $state<string | null>(null);
    let selectedCreditsAmount = $state(21000); // Default credits amount
    let selectedPrice = $state(20); // Default price
    let selectedCurrency = $state('EUR'); // Default currency
    let isGiftFlow = $state(false); // Track if it's a gift flow
    let limitedRefundConsent = $state(false);

    // Animation parameters
    const flyParams = {
        duration: 400,
        x: 100,
        easing: cubicInOut
    };

    const fullStepSequence = [
        STEP_ALPHA_DISCLAIMER, STEP_BASICS, STEP_CONFIRM_EMAIL, STEP_SECURE_ACCOUNT, STEP_PASSWORD,
        STEP_ONE_TIME_CODES, STEP_TFA_APP_REMINDER, STEP_BACKUP_CODES, STEP_RECOVERY_KEY, // STEP_PROFILE_PICTURE,
        STEP_CREDITS, STEP_PAYMENT, STEP_AUTO_TOP_UP, STEP_COMPLETION
    ];

    const passkeyStepSequence = [
        STEP_ALPHA_DISCLAIMER, STEP_BASICS, STEP_CONFIRM_EMAIL, STEP_SECURE_ACCOUNT, STEP_RECOVERY_KEY,
        STEP_CREDITS, STEP_PAYMENT, STEP_AUTO_TOP_UP, STEP_COMPLETION
    ];

    let stepSequence = $derived(
        $signupStore.loginMethod === 'passkey' ? passkeyStepSequence : fullStepSequence
    );

    let isImageProcessing = $state(false);
    let isImageUploading = $state(false);

    // State to track if payment form is showing (after consent is given) using Svelte 5 runes
    let paymentFormVisible = $state(false);
    let refundConsentGiven = $state(false);

    // Track both consent and the current visible screen
    let paymentConsentGiven = $state(false);      // Has consent been given?
    let showingPaymentForm = $state(false);       // Is payment form currently visible?

    // New state to track payment processing status
    let paymentState = $state('idle');
    let paymentIntentId = $state(null);
    let selectedCredits = $state(0);

    // Reference for OneTimeCodesBottomContent instance using Svelte 5 runes
    let oneTimeCodesBottomContentRef = $state<OneTimeCodesBottomContent | null>(null);
    
    // Password form state using Svelte 5 runes
    let passwordFormData = $state({
        password: '',
        passwordRepeat: '',
        isValid: false
    });
    
    // Create derived state for showing/hiding nav and status bar using Svelte 5 runes
    let showUIControls = $derived(paymentState !== 'processing' && paymentState !== 'success');
    
    // Fade transition parameters - make them slower for better visibility
    const fadeParams = {
        duration: 600
    };

    // Update stores when component is mounted and destroyed
    import { onMount, onDestroy } from 'svelte';
    
    // Update stores when component is mounted and destroyed

    onMount(() => {
        isInSignupProcess.set(true);
        
        // Check if signup step is already set (e.g., from page reload or auth check)
        // If not set, start with alpha disclaimer as the first step
        // This ensures users see the disclaimer before proceeding with signup on new signups,
        // but preserves the step on page reload
        const existingStep = $currentSignupStep;
        if (!existingStep || existingStep === STEP_ALPHA_DISCLAIMER) {
            // Only set to alpha disclaimer if no step is set or it's already at alpha disclaimer
            currentSignupStep.set(STEP_ALPHA_DISCLAIMER);
            currentStep = STEP_ALPHA_DISCLAIMER;
            console.log(`[Signup.svelte] Starting signup flow, showing alpha disclaimer first`);
        } else {
            // Use the existing step (e.g., restored from last_opened on page reload)
            currentStep = existingStep;
            console.log(`[Signup.svelte] Resuming signup flow at step: ${existingStep}`);
        }
        
        updateSettingsStep(''); // Provide empty string as initial prevStepValue
        
        // Update footer visibility based on step
        const settingsSteps = [STEP_SETTINGS, STEP_MATE_SETTINGS, STEP_CREDITS, STEP_PAYMENT, STEP_COMPLETION];
        showSignupFooter.set(true);
    });
    
    onDestroy(async () => {
        isInSignupProcess.set(false);
        isSignupSettingsStep.set(false);
        showSignupFooter.set(true); // Reset footer state on destroy
        
        // SECURITY: Clear incomplete signup data from IndexedDB if signup was not completed
        // This ensures username doesn't persist if user leaves signup without completing it
        await clearIncompleteSignupData();
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

    async function handleSwitchToLogin() {
        // Clear the signup store data when switching to login
        clearSignupData();
        
        // SECURITY: Clear incomplete signup data from IndexedDB when switching to login
        // This ensures username doesn't persist if user interrupts signup
        await clearIncompleteSignupData();
        
        dispatch('switchToLogin');
    }

    /**
     * Scroll to top of signup content when step changes
     * Handles both mobile (container scroll) and desktop (window scroll) scenarios
     */
    async function scrollToTop() {
        // Wait for DOM to update after step change
        await new Promise(resolve => {
            requestAnimationFrame(() => {
                requestAnimationFrame(() => {
                    resolve(undefined);
                });
            });
        });
        
        // Try to find login-container (parent of signup-content)
        const loginContainer = document.querySelector('.login-container') as HTMLElement;
        const isMobile = window.innerWidth <= 730; // Match the CSS breakpoint
        
        if (loginContainer) {
            if (isMobile) {
                // Mobile: scroll the container (it has overflow-y: auto)
                // First set to 0 immediately to ensure we're at the top
                loginContainer.scrollTop = 0;
                // Then use smooth scroll for better UX
                if (typeof loginContainer.scrollTo === 'function') {
                    loginContainer.scrollTo({ top: 0, behavior: 'smooth' });
                }
            } else {
                // Desktop: container has overflow: hidden, so scroll the window
                // First set window scroll to 0 immediately
                window.scrollTo(0, 0);
                // Then use smooth scroll
                window.scrollTo({ top: 0, behavior: 'smooth' });
                // Also scroll the login-container into view at the top of the viewport
                loginContainer.scrollIntoView({ behavior: 'smooth', block: 'start' });
            }
        } else {
            // Fallback: just scroll window
            window.scrollTo(0, 0);
            window.scrollTo({ top: 0, behavior: 'smooth' });
        }
        
        // Additional fallback: scroll signup-content element if reference exists
        if (signupContentElement) {
            signupContentElement.scrollIntoView({ block: 'start' });
            signupContentElement.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
    }

    function handleSkip() {
        // Profile picture step removed - moved to settings
        if (currentStep === STEP_TFA_APP_REMINDER) {
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
        
        // Update last_opened to reflect current signup step (skip alpha_disclaimer as it's not a real step)
        // This ensures the signup flow can be restored on page reload
        if (newStep !== STEP_ALPHA_DISCLAIMER) {
            const signupPath = getPathFromStep(newStep);
            console.debug(`[Signup] Updating last_opened to ${signupPath} for step ${newStep}`);
            
            // Update client-side (IndexedDB) first - this ensures the step is saved even if server update fails
            updateProfile({ last_opened: signupPath });
            
            // Update server-side via WebSocket if authenticated
            // Use set_active_chat message - backend will update last_opened with the provided value
            if ($authStore.isAuthenticated) {
                try {
                    // Ensure WebSocket is connected before sending the update
                    // This is important after account creation when the WebSocket might not be connected yet
                    if (!webSocketService.isConnected()) {
                        console.debug(`[Signup] WebSocket not connected, attempting to connect before updating last_opened...`);
                        try {
                            await webSocketService.connect();
                            console.debug(`[Signup] WebSocket connected successfully`);
                        } catch (wsError) {
                            console.warn(`[Signup] Failed to connect WebSocket:`, wsError);
                            // Continue - client-side update is sufficient, server update will happen when WS connects
                        }
                    }
                    
                    // Send the update via WebSocket
                    await chatSyncService.sendSetActiveChat(signupPath);
                    console.debug(`[Signup] Sent set_active_chat to server with signup path: ${signupPath}`);
                } catch (error) {
                    console.warn(`[Signup] Failed to update last_opened on server:`, error);
                    // Continue even if server update fails - client-side update is sufficient for now
                    // The server update will happen when WebSocket connects or on next sync
                }
            }
        }
        
        await tick(); // Wait for Svelte to process state changes before proceeding
        updateSettingsStep(oldStep); // Call update function with old step value
        
        // Update footer visibility based on step
        const settingsSteps = [STEP_SETTINGS, STEP_MATE_SETTINGS, STEP_CREDITS, STEP_PAYMENT, STEP_COMPLETION];
        showSignupFooter.set(true);

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
        
        // Scroll to top when step changes
        await scrollToTop();
        
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
        
        // Update last_opened to reflect current signup step (skip alpha_disclaimer as it's not a real step)
        // This ensures the signup flow can be restored on page reload
        if (step !== STEP_ALPHA_DISCLAIMER) {
            const signupPath = getPathFromStep(step);
            console.debug(`[Signup] Updating last_opened to ${signupPath} for step ${step}`);
            
            // Update client-side (IndexedDB) first - this ensures the step is saved even if server update fails
            updateProfile({ last_opened: signupPath });
            
            // Update server-side via WebSocket if authenticated
            // Use set_active_chat message - backend will update last_opened with the provided value
            if ($authStore.isAuthenticated) {
                try {
                    // Ensure WebSocket is connected before sending the update
                    // This is important after account creation when the WebSocket might not be connected yet
                    if (!webSocketService.isConnected()) {
                        console.debug(`[Signup] WebSocket not connected, attempting to connect before updating last_opened...`);
                        try {
                            await webSocketService.connect();
                            console.debug(`[Signup] WebSocket connected successfully`);
                        } catch (wsError) {
                            console.warn(`[Signup] Failed to connect WebSocket:`, wsError);
                            // Continue - client-side update is sufficient, server update will happen when WS connects
                        }
                    }
                    
                    // Send the update via WebSocket
                    await chatSyncService.sendSetActiveChat(signupPath);
                    console.debug(`[Signup] Sent set_active_chat to server with signup path: ${signupPath}`);
                } catch (error) {
                    console.warn(`[Signup] Failed to update last_opened on server:`, error);
                    // Continue even if server update fails - client-side update is sufficient for now
                    // The server update will happen when WebSocket connects or on next sync
                }
            }
        }
        
        await tick(); // Add tick here too for consistency
        updateSettingsStep(oldStep); // Call update function with old step value
        
        // Update footer visibility based on step
        const settingsSteps = [STEP_SETTINGS, STEP_MATE_SETTINGS, STEP_CREDITS, STEP_PAYMENT, STEP_COMPLETION];
        showSignupFooter.set(true);
        
        // Scroll to top when step changes
        await scrollToTop();
    }

    async function handleLogout() {
        try {
            isLoggingOut.set(true);
            isInSignupProcess.set(false);
            
            // Reset signup step to alpha disclaimer when logging out
            currentSignupStep.set(STEP_ALPHA_DISCLAIMER);

            // SECURITY: Clear incomplete signup data from IndexedDB before logout
            // This ensures username doesn't persist if user logs out during signup
            await clearIncompleteSignupData();

            await authStore.logout({
                beforeLocalLogout: () => {
                    isCheckingAuth.set(false);
                    // SECURITY: Clear all cryptographic data from storage
                    clearKeyFromStorage(); // Clear master key from both session and local storage
                    clearAllEmailData(); // Clear email encryption key, encrypted email, and salt
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
            
            // After logout from signup, close login interface and load demo chat
            // Instead of switching to login view, we want to close the interface and show demo chats
            showSignupFooter.set(true); // Ensure footer is shown after logout
            
            // Close the login interface and load demo chat
            // This dispatches a global event that ActiveChat.svelte listens to
            window.dispatchEvent(new CustomEvent('closeLoginInterface'));
            
            // Small delay to ensure the interface closes before loading chat
            setTimeout(() => {
                // Dispatch event to load demo chat (ActiveChat will handle this)
                window.dispatchEvent(new CustomEvent('loadDemoChat'));
            }, 100);
        } catch (error) {
            console.error('Error during logout:', error);
            showSignupFooter.set(true); // Ensure footer is shown even on error
            // Even on error, ensure we exit signup mode properly
            isInSignupProcess.set(false);
            
            // Reset signup step to alpha disclaimer when logging out
            currentSignupStep.set(STEP_ALPHA_DISCLAIMER);
            
            // SECURITY: Even on error, clear all cryptographic data from storage
            clearKeyFromStorage(); // Clear master key from both session and local storage
            clearAllEmailData(); // Clear email encryption key, encrypted email, and salt
            
            authStore.logout();
            
            // Reset logging out state
            setTimeout(() => {
                isLoggingOut.set(false);
            }, 300);
            
            // Close the login interface and load demo chat even on error
            window.dispatchEvent(new CustomEvent('closeLoginInterface'));
            setTimeout(() => {
                window.dispatchEvent(new CustomEvent('loadDemoChat'));
            }, 100);
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
    async function handlePaymentStateChange(event) {
        paymentState = event.detail.state;
        
        // If payment failed, reset to idle state after a short delay
        if (paymentState === 'failure') {
            setTimeout(() => {
                paymentState = 'idle';
            }, 500);
        } else if (paymentState === 'success') { // Add success handling
            console.debug("Payment successful, saving payment method...");
            
            // Save payment_intent_id for later subscription creation
            paymentIntentId = event.detail.payment_intent_id;
            
            // Save payment method ID to backend for subscription use
            try {
                const response = await fetch(getApiUrl() + apiEndpoints.payments.savePaymentMethod, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'Origin': window.location.origin
                    },
                    credentials: 'include',
                    body: JSON.stringify({
                        payment_intent_id: paymentIntentId
                    })
                });
                
                if (response.ok) {
                    console.debug("Payment method saved successfully");
                } else {
                    console.warn("Failed to save payment method:", await response.text());
                    // Continue anyway - they can still finish signup
                }
            } catch (error) {
                console.error("Error saving payment method:", error);
                // Continue anyway - they can still finish signup
            }
            
            // After payment success, go to auto top-up step
            setTimeout(() => {
                goToStep(STEP_AUTO_TOP_UP);
            }, 500); // Short delay for smooth transition
        }
    }

    // Handle auto top-up completion (skip or finish)
    async function handleAutoTopUpComplete(event) {
        console.debug("Auto top-up step completed, finishing signup...");
        // Complete signup and load main app
        // Update last_opened to signal completion of signup flow
        updateProfile({ last_opened: '/chat/new' });

        // Ensure authentication state is properly updated
        authStore.update(state => ({ ...state, isAuthenticated: true, isInitialized: true }));

        // IMPORTANT: Ensure WebSocket connection is established immediately after auth state update
        // This prevents race conditions where credit updates are broadcast before WS is connected
        try {
            console.debug("Ensuring WebSocket connection is established after signup completion...");
            await webSocketService.connect();
            console.debug("WebSocket connection confirmed after signup completion");
        } catch (error) {
            console.warn("Failed to establish WebSocket connection after signup:", error);
            // Continue with signup completion even if WebSocket fails
        }

        // Signal completion of signup process AFTER ensuring auth state is updated
        isInSignupProcess.set(false);

        if (window.innerWidth >= MOBILE_BREAKPOINT) {
            isMenuOpen.set(true);
        }

        console.debug("Transitioning to chat now.");
    }

    // Handle subscription activation
    async function handleActivateSubscription(event) {
        const { credits, bonusCredits, price, currency } = event.detail;
        console.debug("Activating subscription:", { credits, bonusCredits, price, currency });

        try {
            // Call backend API to create subscription
            const response = await fetch(getApiUrl() + apiEndpoints.payments.createSubscription, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Origin': window.location.origin
                },
                credentials: 'include',
                body: JSON.stringify({
                    credits_amount: credits,
                    currency: currency.toLowerCase()
                })
            });

            if (response.ok) {
                const subscriptionData = await response.json();
                console.debug("Subscription created successfully:", subscriptionData);
            } else {
                console.error("Failed to create subscription:", await response.text());
                // Continue anyway - they can set up subscription later in settings
            }
        } catch (error) {
            console.error("Error creating subscription:", error);
            // Continue anyway - they can set up subscription later in settings
        }

        // Complete signup
        await handleAutoTopUpComplete({ detail: {} });
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

    // Get the appropriate help documentation link based on current step and validation state using Svelte 5 runes
    let helpLink = $derived(getWebsiteUrl(
        currentStep === STEP_BASICS
            ? (!isInviteCodeValidated ? routes.docs.userGuide_signup_1a : routes.docs.userGuide_signup_1b)
            : currentStep === STEP_PAYMENT
                ? (showingPaymentForm ? routes.docs.userGuide_signup_10_2 : routes.docs.userGuide_signup_10_1)
                : routes.docs[`userGuide_signup_${getStepNumber(currentStep)}`] // Temporarily use numbers for docs
    ));
    
    // Helper function to get step number for documentation links (temporary)
    function getStepNumber(stepName) {
        const fullStepMap = {
            [STEP_ALPHA_DISCLAIMER]: 0,
            [STEP_BASICS]: 1,
            [STEP_CONFIRM_EMAIL]: 2,
            [STEP_SECURE_ACCOUNT]: 3,
            [STEP_PASSWORD]: 4,
            // STEP_PROFILE_PICTURE: 5, // Removed - moved to settings
            [STEP_ONE_TIME_CODES]: 6,
            [STEP_BACKUP_CODES]: 7,
            [STEP_TFA_APP_REMINDER]: 8,
            [STEP_RECOVERY_KEY]: 9,
            [STEP_SETTINGS]: 10,
            [STEP_MATE_SETTINGS]: 11,
            [STEP_CREDITS]: 12,
            [STEP_PAYMENT]: 13,
            [STEP_AUTO_TOP_UP]: 14,
            [STEP_COMPLETION]: 15
        };
        return fullStepMap[stepName] || 0;
    }

    // Update showSkip logic to show for specific steps using Svelte 5 runes
    let showSkip = $derived(currentStep === STEP_TFA_APP_REMINDER ||
                  currentStep === STEP_CREDITS);

    // Show expanded header on credits and payment steps using Svelte 5 runes
    let showExpandedHeader = $derived(currentStep === STEP_CREDITS || currentStep === STEP_PAYMENT);

    // For payment step, secure account step, one-time codes step, and backup codes step, use expanded height for the top content wrapper
    // For recovery key step, only expand if the creation UI is not active using Svelte 5 runes
    let isExpandedTopContent = $derived(currentStep === STEP_PAYMENT ||
                             currentStep === STEP_SECURE_ACCOUNT ||
                             currentStep === STEP_ONE_TIME_CODES ||
                             (currentStep === STEP_RECOVERY_KEY && !$isRecoveryKeyCreationActive));
</script>

<div class="signup-content visible" bind:this={signupContentElement} in:fade={{ duration: 400 }}>
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
                on:validated={(e) => { isInviteCodeValidated = e.detail.isValidated; is_admin = e.detail.is_admin; }}
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
                                    {:else if currentStep === STEP_PASSKEY_PRF_ERROR}
                                        <PasskeyPRFError on:step={handleStep} />
                                    <!-- {:else if currentStep === STEP_PROFILE_PICTURE}
                                        <ProfilePictureTopContent
                                            isProcessing={isImageProcessing}
                                            isUploading={isImageUploading}
                                        /> -->
                                    {:else if currentStep === STEP_ONE_TIME_CODES}
                                        <OneTimeCodesTopContent on:actionClicked={handleActionClicked} />
                                    {:else if currentStep === STEP_BACKUP_CODES}
                                        <BackupCodesTopContent {selectedAppName} />
                                    {:else if currentStep === STEP_RECOVERY_KEY}
                                        <RecoveryKeyTopContent on:step={handleStep} />
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
                                    {:else if currentStep === STEP_AUTO_TOP_UP}
                                        <AutoTopUpTopContent
                                            purchasedCredits={selectedCreditsAmount}
                                            purchasedPrice={selectedPrice}
                                            currency={selectedCurrency}
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
                                        {#if currentStep === STEP_CONFIRM_EMAIL}
                                            <ConfirmEmailBottomContent
                                                on:step={handleStep}
                                                on:uploading={handleImageUploading}
                                                on:selectedApp={handleSelectedApp}
                                            />
                                        <!-- {:else if currentStep === STEP_PROFILE_PICTURE}
                                            <ProfilePictureBottomContent
                                                on:step={handleStep}
                                                on:uploading={handleImageUploading}
                                                on:selectedApp={handleSelectedApp}
                                            /> -->
                                        {:else if currentStep === STEP_BACKUP_CODES}
                                            <BackupCodesBottomContent
                                                on:step={handleStep}
                                                on:uploading={handleImageUploading}
                                                on:selectedApp={handleSelectedApp}
                                            />
                                        {:else if currentStep === STEP_RECOVERY_KEY}
                                            <RecoveryKeyBottomContent
                                                on:step={handleStep}
                                                on:uploading={handleImageUploading}
                                                on:selectedApp={handleSelectedApp}
                                            />
                                        {:else if currentStep === STEP_TFA_APP_REMINDER}
                                            <TfaAppReminderBottomContent
                                                on:step={handleStep}
                                                on:uploading={handleImageUploading}
                                                on:selectedApp={handleSelectedApp}
                                            />
                                        {:else if currentStep === STEP_SETTINGS}
                                            <SettingsBottomContent
                                                on:step={handleStep}
                                                on:uploading={handleImageUploading}
                                                on:selectedApp={handleSelectedApp}
                                            />
                                        {:else if currentStep === STEP_MATE_SETTINGS}
                                            <MateSettingsBottomContent
                                                on:step={handleStep}
                                                on:uploading={handleImageUploading}
                                                on:selectedApp={handleSelectedApp}
                                            />
                                        {:else if currentStep === STEP_CREDITS}
                                            <CreditsBottomContent
                                                on:step={handleStep}
                                                on:uploading={handleImageUploading}
                                                on:selectedApp={handleSelectedApp}
                                            />
                                        {:else if currentStep === STEP_PAYMENT}
                                            <PaymentBottomContent
                                                on:step={handleStep}
                                                on:uploading={handleImageUploading}
                                                on:selectedApp={handleSelectedApp}
                                            />
                                        {:else if currentStep === STEP_AUTO_TOP_UP}
                                            <AutoTopUpBottomContent
                                                purchasedCredits={selectedCreditsAmount}
                                                purchasedPrice={selectedPrice}
                                                currency={selectedCurrency}
                                                oncomplete={handleAutoTopUpComplete}
                                                onactivate-subscription={handleActivateSubscription}
                                            />
                                        {/if}
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
            <SignupStatusbar currentStepName={currentStep} stepSequenceOverride={stepSequence} />
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
