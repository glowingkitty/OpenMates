<script lang="ts">
    import { tick } from 'svelte';
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
    import { notificationStore } from '../../stores/notificationStore'; // Import notification store for payment failure notifications

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

    // Import API utilities
    import { getApiUrl, apiEndpoints } from '../../config/api';

    // Props using Svelte 5 runes mode with callback props
    let {
        onswitchToLogin = () => {},
        // Expose state for SignupNav in parent component
        selectedAppName = $bindable(null),
        is_admin = $bindable(false),
        isInviteCodeValidated = $bindable(false),
        showSkip = $bindable(false),
        // Callbacks from parent - these should be bindable so we can update them to call internal handlers
        // For now, we'll make them bindable and update them in $effect
        onSignupNavBack = $bindable(() => {}),
        onSignupNavStep = $bindable((event: { step: string }) => {}),
        onSignupNavSkip = $bindable(() => {}),
        onSignupNavLogout = $bindable(async () => {})
    }: {
        onswitchToLogin?: () => void,
        selectedAppName?: string | null,
        is_admin?: boolean,
        isInviteCodeValidated?: boolean,
        showSkip?: boolean,
        onSignupNavBack?: () => void,
        onSignupNavStep?: (event: { step: string }) => void,
        onSignupNavSkip?: () => void,
        onSignupNavLogout?: () => void
    } = $props();

    // Initialize step from store using Svelte 5 runes
    let currentStep = $state(STEP_ALPHA_DISCLAIMER);
    let direction = $state<'forward' | 'backward'>('forward');
    // isInviteCodeValidated, is_admin, selectedAppName, and showSkip are now bindable props
    // Reference to signup-content element for scrolling
    let signupContentElement: HTMLDivElement;
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
        
        // Set up the callbacks passed from Login to call internal handlers
        // We'll update the callbacks in Login to call our internal handlers
        // This is done via $effect after functions are defined
        
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
        
        // Listen for credit updates via WebSocket (e.g., after successful payment)
        const handleCreditUpdate = (payload: { credits: number }) => {
            const newCredits = payload.credits;
            if (typeof newCredits === 'number') {
                console.debug(`[Signup] Received credit update via WebSocket: ${newCredits}`);
                updateProfile({ credits: newCredits });
            }
        };
        
        // Listen for payment failure notifications via WebSocket
        // This handles cases where payment fails minutes after the user has moved on
        // Shows notification even if Payment component is unmounted
        const handlePaymentFailed = (payload: { order_id: string, message: string }) => {
            console.debug(`[Signup] Received payment_failed notification via WebSocket:`, payload);
            // Show error notification popup (using Notification.svelte component)
            // This ensures user is notified even if they've moved on from payment step
            notificationStore.error(
                payload.message || 'Payment failed. Please try again or use a different payment method.',
                10000 // Show for 10 seconds since this is important
            );
        };
        
        webSocketService.on('user_credits_updated', handleCreditUpdate);
        webSocketService.on('payment_failed', handlePaymentFailed);
        
        // Return cleanup function
        return () => {
            webSocketService.off('user_credits_updated', handleCreditUpdate);
            webSocketService.off('payment_failed', handlePaymentFailed);
        };
    });
    
    onDestroy(async () => {
        isInSignupProcess.set(false);
        isSignupSettingsStep.set(false);
        showSignupFooter.set(true); // Reset footer state on destroy

        // SECURITY: Clear incomplete signup data from IndexedDB if signup was not completed
        // This ensures username doesn't persist if user leaves signup without completing it
        // Only do this if we're past the alpha disclaimer step (i.e., actual signup data may exist)
        if (currentStep !== STEP_ALPHA_DISCLAIMER) {
            console.log('[Signup] onDestroy: Clearing incomplete signup data from IndexedDB...');
            try {
                await clearIncompleteSignupData();
                console.log('[Signup] onDestroy: Incomplete signup data cleared');
            } catch (error) {
                console.error('[Signup] onDestroy: Error clearing incomplete signup data:', error);
            }
        } else {
            console.log('[Signup] onDestroy: Skipping IndexedDB clear (on alpha disclaimer step, no data entered yet)');
        }
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

    let isSwitchingToLogin = $state(false);

    /**
     * Close the login/signup interface and return to demo web app
     * This is called when user clicks back button during alpha disclaimer or basics step
     */
    // Set up callbacks to call internal handlers when invoked
    // We'll use onMount to set up the callbacks after all functions are defined
    // Store original callbacks to avoid infinite loops
    let originalCallbacksSet = $state(false);
    
    onMount(() => {
        if (!originalCallbacksSet) {
            // Store original callbacks
            const originalBack = onSignupNavBack;
            const originalStep = onSignupNavStep;
            const originalSkip = onSignupNavSkip;
            const originalLogout = onSignupNavLogout;
            
            // Update bindable callbacks to call both original and internal handlers
            onSignupNavBack = () => {
                originalBack();
                handleCloseToDemo();
            };
            onSignupNavStep = (event: { step: string }) => {
                originalStep(event);
                handleStepFromNav(event);
            };
            onSignupNavSkip = () => {
                originalSkip();
                handleSkip();
            };
            onSignupNavLogout = async () => {
                await originalLogout();
                await handleLogout();
            };
            
            originalCallbacksSet = true;
        }
    });

    async function handleCloseToDemo() {
        console.log('[Signup] handleCloseToDemo called - closing interface and returning to demo');

        // CRITICAL: Reset signup process state FIRST to ensure Login component switches to login view
        // This prevents the signup view from remaining visible after closing
        isInSignupProcess.set(false);
        console.log('[Signup] Reset isInSignupProcess to false');

        // Clear the signup store data when closing to demo
        console.log('[Signup] Clearing signup data...');
        clearSignupData();
        console.log('[Signup] Signup data cleared');

        // SECURITY: Clear incomplete signup data from IndexedDB when closing to demo
        // This ensures username doesn't persist if user interrupts signup
        // Only do this if we're past the alpha disclaimer step (i.e., actual signup data may exist)
        if (currentStep !== STEP_ALPHA_DISCLAIMER) {
            console.log('[Signup] Clearing incomplete signup data from IndexedDB...');
            try {
                await clearIncompleteSignupData();
                console.log('[Signup] Incomplete signup data cleared');
            } catch (error) {
                console.error('[Signup] Error clearing incomplete signup data:', error);
            }
        } else {
            console.log('[Signup] Skipping IndexedDB clear (on alpha disclaimer step, no data entered yet)');
        }

        // Reset signup step to alpha disclaimer for next time
        currentSignupStep.set(STEP_ALPHA_DISCLAIMER);

        // Close the login interface and load demo chat
        // This dispatches a global event that ActiveChat.svelte listens to
        window.dispatchEvent(new CustomEvent('closeLoginInterface'));

        // Small delay to ensure the interface closes before loading chat
        setTimeout(() => {
            // Dispatch event to load demo chat (ActiveChat will handle this)
            window.dispatchEvent(new CustomEvent('loadDemoChat'));
        }, 100);
    }

    async function handleSwitchToLogin() {
        // Prevent multiple simultaneous calls
        if (isSwitchingToLogin) {
            console.log('[Signup] Already switching to login, ignoring duplicate call');
            return;
        }

        isSwitchingToLogin = true;
        console.log('[Signup] handleSwitchToLogin called');

        // Clear the signup store data when switching to login
        console.log('[Signup] Clearing signup data...');
        clearSignupData();
        console.log('[Signup] Signup data cleared');

        // SECURITY: Clear incomplete signup data from IndexedDB when switching to login
        // This ensures username doesn't persist if user interrupts signup
        // Only do this if we're past the alpha disclaimer step (i.e., actual signup data may exist)
        if (currentStep !== STEP_ALPHA_DISCLAIMER) {
            console.log('[Signup] Clearing incomplete signup data from IndexedDB...');
            try {
                await clearIncompleteSignupData();
                console.log('[Signup] Incomplete signup data cleared');
            } catch (error) {
                console.error('[Signup] Error clearing incomplete signup data:', error);
            }
        } else {
            console.log('[Signup] Skipping IndexedDB clear (on alpha disclaimer step, no data entered yet)');
        }

        console.log('[Signup] Calling onswitchToLogin callback');
        onswitchToLogin();

        isSwitchingToLogin = false;
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

    // Wrapper function to convert SignupNav event format to CustomEvent format
    function handleStepFromNav(event: { step: string }) {
        // Handle internally
        const customEvent = {
            detail: {
                step: event.step,
                credits_amount: undefined,
                price: undefined,
                currency: undefined,
                isGift: undefined
            }
        } as CustomEvent<{step: string, credits_amount?: number, price?: number, currency?: string, isGift?: boolean}>;
        handleStep(customEvent);
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

    // Track payment method save status
    let paymentMethodSaved = $state(false);
    let paymentMethodSaveError = $state<string | null>(null);

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
            
            // Reset payment method save status
            paymentMethodSaved = false;
            paymentMethodSaveError = null;
            
            // Save payment_intent_id for later subscription creation
            paymentIntentId = event.detail.payment_intent_id;
            
            // Save payment method ID to backend for subscription use
            // CRITICAL: Wait for this to complete successfully before proceeding
            // Subscription creation requires the payment method to be saved
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
                    const result = await response.json();
                    console.debug("Payment method saved successfully:", result);
                    
                    // CRITICAL: Verify payment method is available before marking as saved
                    // Poll the has-payment-method endpoint to ensure cache is updated
                    // Increased attempts and timeout to account for cache propagation delay
                    const isAvailable = await pollPaymentMethodAvailability(15, 5000); // 15 attempts, 5 seconds total
                    if (isAvailable) {
                        paymentMethodSaved = true;
                        console.debug("Payment method confirmed available in backend cache");
                    } else {
                        console.warn("Payment method saved but not yet available in cache - subscription creation may fail");
                        // Still mark as saved, but subscription creation will retry verification
                        paymentMethodSaved = true;
                    }
                } else {
                    const errorText = await response.text();
                    console.error("Failed to save payment method:", errorText);
                    paymentMethodSaveError = errorText || "Failed to save payment method";
                    // Don't continue to auto top-up if payment method save failed
                    // User can still finish signup, but subscription won't be available
                    notificationStore.error(
                        "Payment method could not be saved. You can set up auto top-up later in settings.",
                        10000
                    );
                }
            } catch (error) {
                console.error("Error saving payment method:", error);
                paymentMethodSaveError = error instanceof Error ? error.message : "Unknown error saving payment method";
                // Don't continue to auto top-up if payment method save failed
                notificationStore.error(
                    "Payment method could not be saved. You can set up auto top-up later in settings.",
                    10000
                );
            }
            
            // Credits will be updated via WebSocket 'user_credits_updated' event from backend
            // The listener set up in onMount will handle the update automatically
            // If WebSocket is not connected, ensure it's connected to receive the update
            if (!webSocketService.isConnected()) {
                console.debug("[Signup] WebSocket not connected, attempting to connect to receive credit updates...");
                webSocketService.connect().catch(error => {
                    console.warn("[Signup] Failed to connect WebSocket after payment:", error);
                    // Continue anyway - credits will update when WebSocket connects or on next sync
                });
            }
            
            // After payment success, go to auto top-up step
            // Only proceed if payment method was saved successfully (or if user wants to skip)
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

    /**
     * Poll the has-payment-method endpoint to verify payment method is available in backend cache.
     * Retries with exponential backoff until payment method is confirmed available or max attempts reached.
     * @param maxAttempts Maximum number of polling attempts
     * @param maxTimeoutMs Maximum total time to wait in milliseconds
     * @returns true if payment method is available, false otherwise
     */
    async function pollPaymentMethodAvailability(maxAttempts: number = 10, maxTimeoutMs: number = 5000): Promise<boolean> {
        const startTime = Date.now();
        const delayBetweenAttempts = Math.min(200, maxTimeoutMs / maxAttempts); // Adaptive delay
        
        for (let attempt = 1; attempt <= maxAttempts; attempt++) {
            // Check if we've exceeded max timeout
            if (Date.now() - startTime > maxTimeoutMs) {
                console.warn(`[Signup] Payment method polling timeout after ${maxTimeoutMs}ms`);
                return false;
            }
            
            try {
                const response = await fetch(getApiUrl() + apiEndpoints.payments.hasPaymentMethod, {
                    method: 'GET',
                    credentials: 'include'
                });
                
                if (response.ok) {
                    const data = await response.json();
                    if (data.has_payment_method === true) {
                        console.debug(`[Signup] Payment method confirmed available after ${attempt} attempt(s)`);
                        return true;
                    }
                }
                
                // If not available yet, wait before next attempt (except on last attempt)
                if (attempt < maxAttempts) {
                    await new Promise(resolve => setTimeout(resolve, delayBetweenAttempts));
                }
            } catch (error) {
                console.warn(`[Signup] Error checking payment method availability (attempt ${attempt}/${maxAttempts}):`, error);
                // Wait before retrying (except on last attempt)
                if (attempt < maxAttempts) {
                    await new Promise(resolve => setTimeout(resolve, delayBetweenAttempts));
                }
            }
        }
        
        console.warn(`[Signup] Payment method not available after ${maxAttempts} attempts`);
        return false;
    }

    // Handle subscription activation
    async function handleActivateSubscription(event) {
        const { credits, bonusCredits, price, currency } = event.detail;
        console.debug("Activating subscription:", { credits, bonusCredits, price, currency });

        // Check if payment method was saved successfully
        if (!paymentMethodSaved) {
            console.error("Cannot create subscription: Payment method was not saved successfully");
            notificationStore.error(
                "Cannot activate auto top-up: Payment method was not saved. Please try again or set up auto top-up later in settings.",
                10000
            );
            // Don't complete signup - let user try again or skip
            return;
        }

        try {
            // CRITICAL: Verify payment method is available before attempting subscription creation
            // Poll the endpoint to ensure cache is updated and payment method is accessible
            // Increased attempts and timeout to account for cache propagation delay
            console.debug("[Signup] Verifying payment method availability before creating subscription...");
            const isAvailable = await pollPaymentMethodAvailability(20, 8000); // 20 attempts, 8 seconds total
            
            if (!isAvailable) {
                console.error("[Signup] Payment method not available after polling - subscription creation will likely fail");
                notificationStore.error(
                    "Payment method is not yet available. Please wait a moment and try again, or set up auto top-up later in settings.",
                    10000
                );
                return;
            }
            
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
                // Show success notification
                notificationStore.success(
                    "Auto top-up activated successfully!",
                    5000
                );
            } else {
                const errorText = await response.text();
                console.error("Failed to create subscription:", errorText);
                // Show error notification
                notificationStore.error(
                    `Failed to activate auto top-up: ${errorText || "Unknown error"}. You can set up auto top-up later in settings.`,
                    10000
                );
                // Don't complete signup - let user know what happened
                return;
            }
        } catch (error) {
            console.error("Error creating subscription:", error);
            const errorMessage = error instanceof Error ? error.message : "Unknown error";
            notificationStore.error(
                `Error activating auto top-up: ${errorMessage}. You can set up auto top-up later in settings.`,
                10000
            );
            // Don't complete signup - let user know what happened
            return;
        }

        // Complete signup only if subscription was created successfully
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
    // Update the bindable showSkip prop
    $effect(() => {
        showSkip = currentStep === STEP_TFA_APP_REMINDER || currentStep === STEP_CREDITS;
    });

    // Show expanded header on credits and payment steps using Svelte 5 runes
    let showExpandedHeader = $derived(currentStep === STEP_CREDITS || currentStep === STEP_PAYMENT);

    // For payment step, auto top-up step, secure account step, and backup codes step, use expanded height for the top content wrapper
    // For recovery key step, only expand if the creation UI is not active using Svelte 5 runes
    // Credits step uses regular size for both top and bottom containers
    // One-time codes step uses regular size to allow bottom content to be visible
    let isExpandedTopContent = $derived(currentStep === STEP_PAYMENT ||
                             currentStep === STEP_AUTO_TOP_UP ||
                             currentStep === STEP_SECURE_ACCOUNT ||
                             (currentStep === STEP_RECOVERY_KEY && !$isRecoveryKeyCreationActive));
</script>

<div class="signup-content visible" bind:this={signupContentElement} in:fade={{ duration: 400 }}>

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
                                            paymentMethodSaved={paymentMethodSaved}
                                            paymentMethodSaveError={paymentMethodSaveError}
                                            oncomplete={handleAutoTopUpComplete}
                                            onactivate-subscription={handleActivateSubscription}
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
    
    /* Add a class for hiding elements with transition */
    .hidden {
        opacity: 0;
        visibility: hidden;
        transition: opacity 0.6s ease, visibility 0.6s ease;
    }
</style>
