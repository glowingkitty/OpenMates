<script lang="ts">
    import { fade, scale } from 'svelte/transition';
    import { text } from '@repo/ui';
    import AppIconGrid from './AppIconGrid.svelte';
    import { createEventDispatcher } from 'svelte';
    import { authStore, isCheckingAuth, needsDeviceVerification, login, checkAuth } from '../stores/authStore'; // Import login and checkAuth functions
    import { currentSignupStep, isInSignupProcess, STEP_ALPHA_DISCLAIMER, STEP_BASICS, getStepFromPath, STEP_ONE_TIME_CODES, isSignupPath, STEP_PAYMENT } from '../stores/signupState';
    import { clearIncompleteSignupData, clearSignupData } from '../stores/signupStore';
    import { requireInviteCode } from '../stores/signupRequirements';
    import { get } from 'svelte/store';
    import { onMount, onDestroy } from 'svelte';
    import { MOBILE_BREAKPOINT } from '../styles/constants';
    import { tick } from 'svelte';
    import Signup from './signup/Signup.svelte';
    import SignupNav from './signup/SignupNav.svelte';
    import VerifyDevice2FA from './VerifyDevice2FA.svelte'; // Import VerifyDevice2FA component
    import { userProfile } from '../stores/userProfile';
    // Import new login method components
    import EmailLookup from './EmailLookup.svelte';
    import PasswordAndTfaOtp from './PasswordAndTfaOtp.svelte';
    import EnterBackupCode from './EnterBackupCode.svelte';
    import EnterRecoveryKey from './EnterRecoveryKey.svelte';
    // Import crypto service to clear email encryption data
    import * as cryptoService from '../services/cryptoService';
    // Import sessionStorage draft service to clear drafts when returning to demo
    import { clearAllSessionStorageDrafts } from '../services/drafts/sessionStorageDraftService';
    // Import for report issue button functionality
    import { panelState } from '../stores/panelStateStore';
    import { settingsDeepLink } from '../stores/settingsDeepLinkStore';
    import { settingsMenuVisible } from '../components/Settings.svelte';
    import { tooltip } from '../actions/tooltip';
    // Import chunk error handler for graceful handling of stale cache errors
    import { 
        isChunkLoadError, 
        logChunkLoadError, 
        CHUNK_ERROR_MESSAGE, 
        CHUNK_ERROR_NOTIFICATION_DURATION 
    } from '../utils/chunkErrorHandler';
    import { notificationStore } from '../stores/notificationStore';
    
    const dispatch = createEventDispatcher();

    // Form data using $state (Svelte 5 runes mode)
    let email = $state('');
    let password = $state('');
    let isLoading = $state(false);
    let showTfaView = $state(false); // State to control 2FA view visibility
    let tfaErrorMessage = $state<string | null>(null); // State for 2FA error messages
    let verifyDeviceErrorMessage = $state<string | null>(null); // State for device verification errors
    let stayLoggedIn = $state(false); // New state for "Stay logged in" checkbox
    
    // New state variables for multi-step login flow using $state (Svelte 5 runes mode)
    type LoginStep = 'email' | 'password' | 'passkey' | 'security_key' | 'recovery_key' | 'backup_code';
    let currentLoginStep = $state<LoginStep>('email'); // Start with email-only step
    let availableLoginMethods = $state<string[]>([]); // Will be populated from server response
    let preferredLoginMethod = $state('password'); // Default to password
    let tfaAppName = $state<string | null>(null); // Will be populated from lookup response
    let tfaEnabled = $state(true); // Default to true for security (prevents user enumeration)
    let isPasskeyLoading = $state(false); // Track if passkey login is in progress
    let passkeyLoginAbortController: AbortController | null = null; // For cancelling passkey login
    
    // Conditional UI (passkey autofill) state
    let conditionalUIAbortController: AbortController | null = null; // For cancelling conditional UI passkey request
    let isConditionalUISupported = $state(false); // Track if browser supports conditional UI
    
    // Helper function to safely cast string to LoginStep
    function setLoginStep(step: string): void {
        // This ensures the step is a valid LoginStep value
        if (step === 'email' || step === 'password' || step === 'passkey' ||
            step === 'security_key' || step === 'recovery_key' || step === 'backup_code') {
            currentLoginStep = step as LoginStep;
        } else {
            // Default to email if invalid step
            currentLoginStep = 'email';
            console.warn(`Invalid login step: ${step}, defaulting to 'email'`);
        }
    }

    // Add state for mobile view using $state (Svelte 5 runes mode)
    let isMobile = $state(false);
    let screenWidth = $state(0);
    let emailInput: HTMLInputElement | undefined; // Reference to the email input element
    let loginContainer = $state<HTMLDivElement | undefined>(undefined); // Reference to the login-container element (using $state for Svelte 5 bind:this)

    // Add state for minimum loading time control using $state (Svelte 5 runes mode)
    let showLoadingUntil = $state(0);

    // Add state to control form visibility using $state (Svelte 5 runes mode)
    let showForm = $state(false);
    
    // Add state for server connection timeout using $state (Svelte 5 runes mode)
    const SERVER_TIMEOUT_MS = 3000; // 3 seconds timeout
    let serverConnectionError = $state(false);
    let connectionTimeoutId: ReturnType<typeof setTimeout> | null = null;
    
    // Add state to control grid visibility - show grids immediately since they don't depend on async operations
    let gridsReady = $state(true);

    // currentView is now declared using $derived below

    // Add touch detection using $state (Svelte 5 runes mode)
    let isTouchDevice = $state(false);

    // Add email validation state using $state (Svelte 5 runes mode)
    let emailError = $state('');
    let showEmailWarning = $state(false);
    let isEmailValidationPending = $state(false);
    let loginFailedWarning = $state(false);
    let loginErrorMessage = $state<string | null>(null);

    // Add rate limiting state using $state (Svelte 5 runes mode)
    const RATE_LIMIT_DURATION = 120000; // 120 seconds in milliseconds
    let isRateLimited = $state(false);
    let rateLimitTimer: ReturnType<typeof setTimeout>;

    let isPolicyViolationLockout = $state(false);
    let isAccountDeleted = $state(false);

    // Add state for tracking account deletion during the current session using $state (Svelte 5 runes mode)
    let accountJustDeleted = $state(false);
    
    // Add state for tracking account recovery mode (from PasswordAndTfaOtp component)
    // When true, the inactivity timer should NOT reset the login interface
    let isInAccountRecoveryMode = $state(false);

    // Derive device verification view state using $derived (Svelte 5 runes mode)
    let showVerifyDeviceView = $derived($needsDeviceVerification);

    /**
     * Clear pending draft from sessionStorage for privacy reasons
     * Called when user leaves the login/signup flow before completing it
     */
    function clearPendingDraft() {
        try {
            const pendingDraft = sessionStorage.getItem('pendingDraftAfterSignup');
            if (pendingDraft) {
                sessionStorage.removeItem('pendingDraftAfterSignup');
                console.debug('[Login] Cleared pendingDraftAfterSignup from sessionStorage for privacy');
            }
        } catch (error) {
            console.warn('[Login] Error clearing pendingDraftAfterSignup:', error);
        }
    }

    /**
     * Handler for the report issue button click.
     * Opens the settings menu and navigates to the report issue page.
     * This allows users to easily report login and signup issues.
     */
    async function handleReportIssue() {
        console.debug("[Login] Report issue button clicked, opening report issue settings");
        
        // Set settingsMenuVisible to true first
        // Settings.svelte watches settingsMenuVisible store and will sync isMenuVisible
        settingsMenuVisible.set(true);
        
        // Also open via panelState for consistency
        panelState.openSettings();
        
        // Wait for store update to propagate and DOM to update
        await tick();
        await new Promise(resolve => setTimeout(resolve, 100));
        
        // Navigate to the report issue settings page
        settingsDeepLink.set('report_issue');
    }

    // --- Inactivity Timer (Login/2FA/Device Verify) ---
    const LOGIN_INACTIVITY_TIMEOUT_MS = 120000; // 2 minutes
    let inactivityTimer: ReturnType<typeof setTimeout> | null = null;
    let isTimerActive = false;
    // --- End Inactivity Timer ---

    const leftIconGrid = [
        ['videos', 'health', 'web'],
        ['calendar', 'nutrition', 'language'],
        ['plants', 'fitness', 'shipping'],
        ['shopping', 'jobs', 'books'],
        ['study', 'home', 'tv'],
        ['weather', 'events', 'legal'],
        ['travel', 'photos', 'maps']
    ];
    const rightIconGrid = [
        ['finance', 'business', 'files'],
        ['code', 'pcbdesign', 'audio'],
        ['mail', 'socialmedia', 'messages'],
        ['hosting', 'diagrams', 'news'],
        ['notes', 'whiteboards', 'projectmanagement'],
        ['design', 'publishing', 'pdfeditor'],
        ['slides', 'sheets', 'docs']
    ];
    
    // Combine icons for mobile grid - selected icons from both grids
    const mobileIconGrid = [
        ['videos', 'health', 'web', 'calendar', 'nutrition', 'language','plants', 'fitness', 'shipping','shopping', 'jobs', 'books'],
        ['finance', 'business', 'files', 'code', 'pcbdesign', 'audio','mail', 'socialmedia', 'messages','hosting', 'diagrams', 'news']
    ];

    // Constants for icon sizes
    const DESKTOP_ICON_SIZE = '67px'; 
    const MOBILE_ICON_SIZE = '36px';

    // Compute display state based on screen width using $derived (Svelte 5 runes mode)
    let showDesktopGrids = $derived(screenWidth > 600);
    let showMobileGrid = $derived(screenWidth <= 600);


    function setRateLimitTimer(duration: number) {
        if (rateLimitTimer) clearTimeout(rateLimitTimer);
        rateLimitTimer = setTimeout(() => {
            isRateLimited = false;
            localStorage.removeItem('loginRateLimit');
        }, duration);
    }

    // Add debounce helper
    function debounce<T extends (...args: any[]) => void>(
        fn: T,
        delay: number
    ): (...args: Parameters<T>) => void {
        let timeoutId: ReturnType<typeof setTimeout>;
        return (...args: Parameters<T>) => {
            clearTimeout(timeoutId);
            timeoutId = setTimeout(() => fn(...args), delay);
        };
    }

    // Modify email validation check
    const debouncedCheckEmail = debounce((email: string) => {
        if (!email) {
            emailError = '';
            showEmailWarning = false;
            isEmailValidationPending = false;
            return;
        }

        if (!email.includes('@')) {
            emailError = $text('signup.at_missing.text');
            showEmailWarning = true;
            isEmailValidationPending = false;
            return;
        }

        if (!email.match(/\.[a-z]{2,}$/i)) {
            emailError = $text('signup.domain_ending_missing.text');
            showEmailWarning = true;
            isEmailValidationPending = false;
            return;
        }

        emailError = '';
        showEmailWarning = false;
        isEmailValidationPending = false;
    }, 800);

    // Clear login failed warning when either email or password changes using $effect (Svelte 5 runes mode)
    $effect(() => {
        if (email || password) {
            loginFailedWarning = false;
            loginErrorMessage = null;
        }
    });

    // Update reactive statements to include email validation using $effect (Svelte 5 runes mode)
    $effect(() => {
        if (email) {
            isEmailValidationPending = true;
            debouncedCheckEmail(email);
        } else {
            emailError = '';
            showEmailWarning = false;
            isEmailValidationPending = false;
        }
    });

    // Initialize validation state when email is empty using $derived (Svelte 5 runes mode)
    let hasValidEmail = $derived(email && !emailError && !isEmailValidationPending);
    
    // Update helper for form validation to be false by default using $derived (Svelte 5 runes mode)
    let isFormValid = $derived(hasValidEmail && 
                     password && 
                     !loginFailedWarning);

    // Force validation check on empty email using $effect (Svelte 5 runes mode)
    $effect(() => {
        if (!email) {
            debouncedCheckEmail('');
        }
    });
    
    // Improve switchToSignup function to reset the signup step and ensure state changes are coordinated
    async function switchToSignup() {
        console.log('[Login] switchToSignup called - resetting login flow completely');
        
        // Cancel any pending conditional UI passkey request
        cancelConditionalUIPasskey();
        
        // Cancel any pending manual passkey login request
        // This prevents NotAllowedError when user navigates to signup during passkey login
        if (passkeyLoginAbortController) {
            passkeyLoginAbortController.abort();
            passkeyLoginAbortController = null;
            isPasskeyLoading = false;
            isLoading = false;
        }
        
        // COMPLETE RESET: Clear ALL login flow state before switching view
        // This ensures a clean slate when user switches to signup and back to login
        
        // Clear form data
        email = '';
        password = '';
        
        // Reset login step to initial state
        currentLoginStep = 'email';
        
        // Clear login method state from email lookup
        availableLoginMethods = [];
        preferredLoginMethod = 'password';
        tfaAppName = null;
        tfaEnabled = true; // Default to true for security (prevents user enumeration)
        
        // Clear 2FA and device verification views
        showTfaView = false;
        tfaErrorMessage = null;
        verifyDeviceErrorMessage = null;
        needsDeviceVerification.set(false);
        
        // Clear general login errors and warnings
        loginFailedWarning = false;
        emailError = '';
        showEmailWarning = false;
        isEmailValidationPending = false;
        
        // Clear rate limiting state (don't clear actual rate limit, just UI state)
        // Note: isRateLimited is preserved to respect actual rate limits
        isPolicyViolationLockout = false;
        isAccountDeleted = false;
        accountJustDeleted = false;
        
        // Clear account recovery mode
        isInAccountRecoveryMode = false;
        
        // Stop the inactivity timer since we're leaving the login flow
        stopInactivityTimer();
        
        // PRIVACY: Clear pending draft when user switches from login to signup
        // This ensures the saved message is deleted if user doesn't complete the flow
        clearPendingDraft();
        
        // SECURITY: Clear email encryption data from cryptoService
        // This ensures no sensitive data from login lookup persists
        cryptoService.clearAllEmailData();
        
        console.log('[Login] Login flow state reset complete');

        // CRITICAL: Check invite code requirement when switching to signup
        // This ensures we have the latest requirement status even if user hasn't reloaded the page
        // The requireInviteCode store is updated from the /session endpoint response
        // We call checkAuth() to refresh the session and get the latest invite code requirement
        console.debug('[Login] Checking invite code requirement before switching to signup...');
        try {
            // Call checkAuth to refresh session and update requireInviteCode store
            // This is a lightweight call that just checks the session endpoint
            await checkAuth();
            const inviteCodeRequired = get(requireInviteCode);
            console.debug(`[Login] Invite code requirement checked: ${inviteCodeRequired}`);
        } catch (error) {
            console.warn('[Login] Failed to check invite code requirement:', error);
            // Continue with signup even if check fails - the Basics component will handle validation
        }

        // Reset the signup step to alpha disclaimer when starting a new signup process
        // This ensures users see the alpha disclaimer before proceeding with signup
        currentSignupStep.set(STEP_ALPHA_DISCLAIMER);
        
        // Set the signup process flag, which will reactively change the view
        isInSignupProcess.set(true);
        
        // Wait for next tick to ensure the flag is processed before logging
        await tick();
        console.debug("Switched to signup view, isInSignupProcess:", $isInSignupProcess, "step:", $currentSignupStep);
        
        // Wait for DOM to update and signup content to render
        await new Promise(resolve => {
            requestAnimationFrame(() => {
                requestAnimationFrame(() => {
                    resolve(undefined);
                });
            });
        });
        
        // Note: Scroll position is intentionally preserved when switching to signup
        // This allows users to maintain their scroll position in the view
    }
    
    async function switchToLogin() {
        console.log('[Login] switchToLogin called - resetting signup process');

        // PRIVACY: Clear signup data (email and username) when switching to login
        // This ensures sensitive data is removed if user switches views
        clearSignupData();

        // Reset the signup step to alpha disclaimer for clean state when returning to signup later
        // This ensures users will start fresh if they switch back to signup
        currentSignupStep.set(STEP_ALPHA_DISCLAIMER);

        // Reset the signup process flag, which will reactively change the view
        isInSignupProcess.set(false);

        // PRIVACY: Clear pending draft when user switches from signup to login
        // This ensures the saved message is deleted if user doesn't complete the flow
        clearPendingDraft();
        
        // SECURITY: Clear any crypto data that may have been stored during signup
        // This ensures sensitive data from signup doesn't persist when returning to login
        cryptoService.clearAllEmailData();

        // Wait for the view change to take effect
        await tick();

        console.log('[Login] View should now be:', $isInSignupProcess ? 'signup' : 'login');

        // Only focus if not touch device
        if (emailInput && !isTouchDevice) {
            emailInput.focus();
        }
    }
    
    /**
     * Helper functions for passkey login
     */
    function arrayBufferToBase64Url(buffer: ArrayBuffer): string {
        const bytes = new Uint8Array(buffer);
        let binary = '';
        for (let i = 0; i < bytes.byteLength; i++) {
            binary += String.fromCharCode(bytes[i]);
        }
        return window.btoa(binary)
            .replace(/\+/g, '-')
            .replace(/\//g, '_')
            .replace(/=/g, '');
    }
    
    function base64UrlToArrayBuffer(base64url: string): ArrayBuffer {
        let base64 = base64url.replace(/-/g, '+').replace(/_/g, '/');
        while (base64.length % 4) {
            base64 += '=';
        }
        const binary = window.atob(base64);
        const bytes = new Uint8Array(binary.length);
        for (let i = 0; i < binary.length; i++) {
            bytes[i] = binary.charCodeAt(i);
        }
        return bytes.buffer;
    }
    
    function getSessionId(): string {
        let sessionId = sessionStorage.getItem('openmates_session_id');
        if (!sessionId) {
            sessionId = crypto.randomUUID();
            sessionStorage.setItem('openmates_session_id', sessionId);
        }
        return sessionId;
    }
    
    /**
     * Start passkey login - shows loading screen and initiates WebAuthn
     */
    async function startPasskeyLogin() {
        if (isPasskeyLoading || isLoading) return;

        // Cancel any pending conditional UI passkey request to avoid WebAuthn conflicts
        cancelConditionalUIPasskey();

        // Wait a bit longer to ensure the conditional UI request is fully cancelled
        // This prevents "A request is already pending" errors
        await new Promise(resolve => setTimeout(resolve, 100));

        // Show loading screen
        isPasskeyLoading = true;
        passkeyLoginAbortController = new AbortController();

        // Wait a tick for the UI to update, then start passkey login flow
        await tick();
        await performPasskeyLogin();
    }
    
    /**
     * Cancel passkey login and return to email login
     */
    function cancelPasskeyLogin() {
        // Abort any ongoing passkey operations
        if (passkeyLoginAbortController) {
            passkeyLoginAbortController.abort();
            passkeyLoginAbortController = null;
        }
        
        // Reset state
        isPasskeyLoading = false;
        isLoading = false;
        loginFailedWarning = false;
    }
    
    /**
     * Perform passkey login flow
     */
    async function performPasskeyLogin() {
        if (!isPasskeyLoading) return; // Check if still in passkey mode
        
        try {
            isLoading = true;
            loginFailedWarning = false;
            loginErrorMessage = null;
            
            const { getApiEndpoint, apiEndpoints } = await import('../config/api');
            const cryptoService = await import('../services/cryptoService');
            
            // Step 1: Initiate passkey assertion with backend (no email required for resident credentials)
            const initiateResponse = await fetch(getApiEndpoint(apiEndpoints.auth.passkey_assertion_initiate), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({}),
                credentials: 'include',
                signal: passkeyLoginAbortController?.signal
            });
            
            if (!initiateResponse.ok) {
                const errorData = await initiateResponse.json();
                console.error('Passkey assertion initiation failed:', errorData);
                loginFailedWarning = true;
                isPasskeyLoading = false;
                isLoading = false;
                return;
            }
            
            const initiateData = await initiateResponse.json();
            
            if (!initiateData.success) {
                console.error('Passkey assertion initiation failed:', initiateData.message);
                loginFailedWarning = true;
                isPasskeyLoading = false;
                isLoading = false;
                return;
            }
            
            // Step 2: Prepare WebAuthn request options
            const challenge = base64UrlToArrayBuffer(initiateData.challenge);
            
            // Prepare PRF extension input
            // Use the PRF eval.first from backend if provided, otherwise use challenge as fallback
            const prfEvalFirst = initiateData.extensions?.prf?.eval?.first || initiateData.challenge;
            const prfEvalFirstBuffer = base64UrlToArrayBuffer(prfEvalFirst);
            console.log('[Login] PRF extension request:', {
                hasPrfExtension: !!initiateData.extensions?.prf,
                prfEvalFirst: prfEvalFirst.substring(0, 20) + '...',
                usingFallback: !initiateData.extensions?.prf?.eval?.first,
                challenge: initiateData.challenge.substring(0, 20) + '...'
            });
            
            const publicKeyCredentialRequestOptions: PublicKeyCredentialRequestOptions = {
                challenge: challenge,
                rpId: initiateData.rp.id,
                timeout: initiateData.timeout,
                userVerification: initiateData.userVerification as UserVerificationRequirement,
                allowCredentials: initiateData.allowCredentials?.length > 0 
                    ? initiateData.allowCredentials.map((cred: any) => ({
                        type: cred.type,
                        id: base64UrlToArrayBuffer(cred.id),
                        transports: cred.transports
                    }))
                    : [],
                extensions: {
                    prf: {
                        eval: {
                            first: prfEvalFirstBuffer
                        }
                    }
                } as AuthenticationExtensionsClientInputs
            };
            
            console.log('[Login] WebAuthn request options prepared:', {
                rpId: publicKeyCredentialRequestOptions.rpId,
                hasExtensions: !!publicKeyCredentialRequestOptions.extensions,
                hasPrfExtension: !!(publicKeyCredentialRequestOptions.extensions as any)?.prf,
                allowCredentialsCount: publicKeyCredentialRequestOptions.allowCredentials?.length || 0
            });
            
            // Step 3: Get passkey assertion using WebAuthn API
            let assertion: PublicKeyCredential;
            try {
                assertion = await navigator.credentials.get({
                    publicKey: publicKeyCredentialRequestOptions,
                    signal: passkeyLoginAbortController?.signal
                }) as PublicKeyCredential;
            } catch (error: any) {
                // Handle expected cancellations first (don't log as errors)
                if (error.name === 'AbortError') {
                    // Request was aborted (e.g., user navigated to signup) - expected behavior
                    console.log('[Login] Passkey login was cancelled');
                    isPasskeyLoading = false;
                    isLoading = false;
                    return;
                }
                if (error.name === 'NotAllowedError') {
                    // NotAllowedError can occur when:
                    // 1. User cancelled the passkey prompt
                    // 2. Request timed out
                    // 3. User navigated away (e.g., to signup) before completing
                    // This is expected behavior during navigation, so log as info, not error
                    const isExpectedCancellation = $isInSignupProcess || !passkeyLoginAbortController;
                    if (isExpectedCancellation) {
                        console.log('[Login] Passkey login cancelled (expected during navigation)');
                    } else {
                        console.log('[Login] Passkey login was cancelled by user');
                    }
                    isPasskeyLoading = false;
                    isLoading = false;
                    return;
                }
                // Only log unexpected errors as errors
                console.error('WebAuthn assertion failed with unexpected error:', error);
                loginFailedWarning = true;
                isPasskeyLoading = false;
                isLoading = false;
                return;
            }
            
            if (!assertion || !(assertion instanceof PublicKeyCredential)) {
                console.error('Invalid assertion received');
                loginFailedWarning = true;
                isPasskeyLoading = false;
                isLoading = false;
                return;
            }
            
            const response = assertion.response as AuthenticatorAssertionResponse;
            
            // Step 4: Check PRF extension support
            const clientExtensionResults = assertion.getClientExtensionResults();
            console.log('[Login] Client extension results:', clientExtensionResults);
            const prfResults = clientExtensionResults?.prf as any;
            console.log('[Login] PRF results:', prfResults);
            
            // Check if PRF is enabled and has results
            // Note: Some authenticators may return PRF results even if enabled is false/undefined
            // We need to check both enabled flag and presence of results
            if (!prfResults) {
                console.error('[Login] PRF extension not found in client extension results', {
                    clientExtensionResults,
                    hasPrf: !!clientExtensionResults?.prf
                });
                loginFailedWarning = true;
                isPasskeyLoading = false;
                isLoading = false;
                return;
            }
            
            // Check if PRF is enabled (some browsers may not set this flag correctly)
            if (prfResults.enabled === false) {
                console.error('[Login] PRF extension explicitly disabled', {
                    prfResults,
                    enabled: prfResults.enabled
                });
                loginFailedWarning = true;
                isPasskeyLoading = false;
                isLoading = false;
                return;
            }
            
            // Extract PRF signature - handle both ArrayBuffer and hex string formats
            const prfSignatureBuffer = prfResults.results?.first;
            if (!prfSignatureBuffer) {
                console.error('[Login] PRF signature not found in results', {
                    prfResults,
                    hasResults: !!prfResults.results,
                    resultsKeys: prfResults.results ? Object.keys(prfResults.results) : []
                });
                loginFailedWarning = true;
                isPasskeyLoading = false;
                isLoading = false;
                return;
            }
            
            // Convert PRF signature to Uint8Array
            // Handle both ArrayBuffer and hex string formats
            let prfSignature: Uint8Array;
            if (typeof prfSignatureBuffer === 'string') {
                // Hex string format (e.g., "65caf64f0349e41168307bc91df7157fb8e22c8b59f96d445c716731fa6445bb")
                console.log('[Login] PRF signature is hex string, converting to Uint8Array');
                const hexString = prfSignatureBuffer;
                prfSignature = new Uint8Array(hexString.match(/.{1,2}/g)!.map(byte => parseInt(byte, 16)));
            } else if (prfSignatureBuffer instanceof ArrayBuffer) {
                // ArrayBuffer format
                console.log('[Login] PRF signature is ArrayBuffer, converting to Uint8Array');
                prfSignature = new Uint8Array(prfSignatureBuffer);
            } else if (ArrayBuffer.isView(prfSignatureBuffer)) {
                // TypedArray format (Uint8Array, etc.)
                console.log('[Login] PRF signature is TypedArray, converting to Uint8Array');
                prfSignature = new Uint8Array(prfSignatureBuffer.buffer, prfSignatureBuffer.byteOffset, prfSignatureBuffer.byteLength);
            } else {
                console.error('[Login] PRF signature is in unknown format', {
                    type: typeof prfSignatureBuffer,
                    constructor: prfSignatureBuffer?.constructor?.name,
                    value: prfSignatureBuffer
                });
                loginFailedWarning = true;
                isPasskeyLoading = false;
                isLoading = false;
                return;
            }
            
            // Validate PRF signature length (should be 32 bytes for SHA-256)
            if (prfSignature.length < 16 || prfSignature.length > 64) {
                console.error('[Login] PRF signature has invalid length', {
                    length: prfSignature.length,
                    expected: '16-64 bytes'
                });
                loginFailedWarning = true;
                isPasskeyLoading = false;
                isLoading = false;
                return;
            }
            
            console.log('[Login] PRF signature extracted successfully', {
                length: prfSignature.length,
                firstBytes: Array.from(prfSignature.slice(0, 4))
            });
            
            // Step 5: Extract credential data for backend
            const credentialId = arrayBufferToBase64Url(assertion.rawId);
            const clientDataJSONB64 = cryptoService.uint8ArrayToBase64(new Uint8Array(response.clientDataJSON));
            const authenticatorDataB64 = cryptoService.uint8ArrayToBase64(new Uint8Array(response.authenticatorData));
            
            // Step 6: Verify passkey assertion with backend
            const verifyResponse = await fetch(getApiEndpoint(apiEndpoints.auth.passkey_assertion_verify), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    credential_id: credentialId,
                    assertion_response: {
                        authenticatorData: authenticatorDataB64,
                        clientDataJSON: clientDataJSONB64,
                        signature: cryptoService.uint8ArrayToBase64(new Uint8Array(response.signature)),
                        userHandle: response.userHandle ? cryptoService.uint8ArrayToBase64(new Uint8Array(response.userHandle)) : null
                    },
                    client_data_json: clientDataJSONB64,
                    authenticator_data: authenticatorDataB64,
                    stay_logged_in: stayLoggedIn,
                    session_id: getSessionId()
                }),
                credentials: 'include',
                signal: passkeyLoginAbortController?.signal
            });
            
            if (!verifyResponse.ok) {
                const errorData = await verifyResponse.json();
                console.error('Passkey assertion verification failed:', errorData);
                loginErrorMessage = errorData.message || null;
                loginFailedWarning = true;
                isPasskeyLoading = false;
                isLoading = false;
                return;
            }
            
            const verifyData = await verifyResponse.json();
            
            if (!verifyData.success) {
                console.error('Passkey verification failed:', verifyData.message);
                loginErrorMessage = verifyData.message || null;
                loginFailedWarning = true;
                isPasskeyLoading = false;
                isLoading = false;
                return;
            }
            
            // Step 7: Get email salt from backend response
            let emailSalt = cryptoService.getEmailSalt();
            if (!emailSalt && verifyData.user_email_salt) {
                const { base64ToUint8Array } = await import('../services/cryptoService');
                emailSalt = base64ToUint8Array(verifyData.user_email_salt);
                cryptoService.saveEmailSalt(emailSalt, stayLoggedIn);
            }
            
            if (!emailSalt) {
                console.error('Email salt not found');
                loginFailedWarning = true;
                isPasskeyLoading = false;
                isLoading = false;
                return;
            }
            
            // Debug logging for key derivation
            console.log('[Login] Key derivation inputs:', {
                prfSignatureLength: prfSignature.length,
                prfSignatureFirstBytes: Array.from(prfSignature.slice(0, 4)),
                emailSaltLength: emailSalt.length,
                emailSaltFirstBytes: Array.from(emailSalt.slice(0, 4)),
                user_email_salt_from_backend: verifyData.user_email_salt?.substring(0, 20) + '...'
            });
            
            // Step 8: Derive wrapping key from PRF signature using HKDF
            const wrappingKey = await cryptoService.deriveWrappingKeyFromPRF(prfSignature, emailSalt);
            
            console.log('[Login] Wrapping key derived:', {
                wrappingKeyLength: wrappingKey.length,
                wrappingKeyFirstBytes: Array.from(wrappingKey.slice(0, 4))
            });
            
            // Step 9: Unwrap master key (needed to decrypt email)
            const encryptedMasterKey = verifyData.encrypted_master_key;
            const keyIv = verifyData.key_iv;
            
            if (!encryptedMasterKey || !keyIv) {
                console.error('Missing encrypted master key or IV');
                loginFailedWarning = true;
                isPasskeyLoading = false;
                isLoading = false;
                return;
            }
            
            const masterKey = await cryptoService.decryptKey(encryptedMasterKey, keyIv, wrappingKey);
            
            if (!masterKey) {
                console.error('Failed to unwrap master key');
                loginFailedWarning = true;
                isPasskeyLoading = false;
                isLoading = false;
                return;
            }
            
            // Step 10: Save master key to storage (needed for decrypting email)
            // Pass stayLoggedIn to ensure key is cleared on tab/browser close if user didn't check "Stay logged in"
            await cryptoService.saveKeyToSession(masterKey, stayLoggedIn);
            
            // Step 11: Decrypt email using master key (for passwordless login)
            // The server returns encrypted_email encrypted with master key (encrypted_email_with_master_key)
            let userEmail = verifyData.user_email;
            if (!userEmail && verifyData.encrypted_email) {
                // Decrypt email using master key (master key is already saved to storage at step 10)
                const { decryptWithMasterKey } = await import('../services/cryptoService');
                const decryptedEmail = await decryptWithMasterKey(verifyData.encrypted_email);
                if (decryptedEmail) {
                    userEmail = decryptedEmail;
                    console.log('[Login] Email decrypted from encrypted_email using master key');
                } else {
                    console.error('[Login] Failed to decrypt email with master key');
                    loginFailedWarning = true;
                    isPasskeyLoading = false;
                    isLoading = false;
                    return;
                }
            }
            
            if (!userEmail) {
                console.error('Email not available for key derivation');
                loginFailedWarning = true;
                isPasskeyLoading = false;
                isLoading = false;
                return;
            }
            
            // Step 12: Derive email encryption key from decrypted email
            const emailEncryptionKey = await cryptoService.deriveEmailEncryptionKey(userEmail, emailSalt);
            cryptoService.saveEmailEncryptionKey(emailEncryptionKey, stayLoggedIn);
            cryptoService.saveEmailSalt(emailSalt, stayLoggedIn);
            
            // Step 13: Generate lookup hash from PRF signature
            const lookupHash = await cryptoService.hashKeyFromPRF(prfSignature, emailSalt);
            
            // Step 14: Authenticate with lookup_hash to get full auth session (including ws_token)
            // The passkey verify endpoint doesn't return auth_session, so we need to call /auth/login
            if (!verifyData.auth_session) {
                console.log('[Login] No auth_session in verify response, authenticating with lookup_hash');
                
                // Get hashed_email for authentication
                const hashedEmail = await cryptoService.hashEmail(userEmail);
                
                // Authenticate using the regular login endpoint with lookup_hash
                const { getApiEndpoint, apiEndpoints } = await import('../config/api');
                const { getSessionId } = await import('../utils/sessionId');
                const authResponse = await fetch(getApiEndpoint(apiEndpoints.auth.login), {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        hashed_email: hashedEmail,
                        lookup_hash: lookupHash,
                        email_encryption_key: cryptoService.getEmailEncryptionKeyForApi(),
                        login_method: 'passkey',
                        credential_id: credentialId,
                        stay_logged_in: stayLoggedIn,
                        session_id: getSessionId()
                    }),
                    credentials: 'include'
                });
                
                if (!authResponse.ok) {
                    const errorData = await authResponse.json();
                    console.error('Passkey authentication failed:', errorData);
                    loginFailedWarning = true;
                    isPasskeyLoading = false;
                    isLoading = false;
                    return;
                }
                
                const authData = await authResponse.json();
                
                if (!authData.success) {
                    console.error('Passkey authentication failed:', authData.message);
                    loginFailedWarning = true;
                    isPasskeyLoading = false;
                    isLoading = false;
                    return;
                }
                
                // The /auth/login endpoint returns user and ws_token at the top level
                // Store them in verifyData for consistency with the rest of the flow
                verifyData.auth_session = {
                    user: authData.user,
                    ws_token: authData.ws_token
                };
                console.log('[Login] Authentication successful via login endpoint');
            }
            
            // Step 15: Store email encrypted with master key for client use
            await cryptoService.saveEmailEncryptedWithMasterKey(userEmail, stayLoggedIn);
            
            // Step 16: Store WebSocket token if provided (CRITICAL for WebSocket connection)
            // Check both verifyData.auth_session.ws_token and direct authData.ws_token for compatibility
            const wsToken = verifyData.auth_session?.ws_token;
            if (wsToken) {
                const { setWebSocketToken } = await import('../utils/cookies');
                setWebSocketToken(wsToken);
                console.debug('[Login] WebSocket token stored from login response');
            } else {
                console.warn('[Login] No ws_token in auth_session - WebSocket connection may fail');
            }
            
            // Step 17: Update user profile
            const userData = verifyData.auth_session?.user;
            if (userData) {
                // Log auto top-up fields from backend response - ERROR if missing
                const hasAutoTopupFields = 'auto_topup_low_balance_enabled' in userData;
                if (!hasAutoTopupFields) {
                    console.error('[Login] ERROR: Auto top-up fields missing from backend response (passkey path 1)!');
                    console.error('[Login] Received user object keys:', Object.keys(userData));
                    console.error('[Login] Full user object:', userData);
                } else {
                    console.debug('[Login] Auto top-up fields from backend (passkey path 1):', {
                        enabled: userData.auto_topup_low_balance_enabled,
                        threshold: userData.auto_topup_low_balance_threshold,
                        amount: userData.auto_topup_low_balance_amount,
                        currency: userData.auto_topup_low_balance_currency
                    });
                }
                
                // CRITICAL: Reset forcedLogoutInProgress and isLoggingOut flags BEFORE any database operations
                // This handles the race condition where orphaned database cleanup was triggered on page load
                // (setting these flags to true) but the user then successfully logs in with passkey.
                // Without this reset, userDB.saveUserData() would throw "Database initialization blocked during logout"
                const { forcedLogoutInProgress, isLoggingOut } = await import('../stores/signupState');
                if (get(forcedLogoutInProgress)) {
                    console.debug('[Login] Resetting forcedLogoutInProgress to false - successful passkey login (path 1)');
                    forcedLogoutInProgress.set(false);
                }
                if (get(isLoggingOut)) {
                    console.debug('[Login] Resetting isLoggingOut to false - successful passkey login (path 1)');
                    isLoggingOut.set(false);
                }
                // Also clear the cleanup marker to prevent future false positives
                if (typeof localStorage !== 'undefined') {
                    localStorage.removeItem('openmates_needs_cleanup');
                }
                
                // Save to IndexedDB first
                const { userDB } = await import('../services/userDB');
                await userDB.saveUserData(userData);
                
                const { updateProfile } = await import('../stores/userProfile');
                const userProfileData = {
                    username: userData.username || '',
                    profile_image_url: userData.profile_image_url || null,
                    credits: userData.credits || 0,
                    is_admin: userData.is_admin || false,
                    last_opened: userData.last_opened || '',
                    tfa_app_name: userData.tfa_app_name || null,
                    tfa_enabled: userData.tfa_enabled || false,
                    consent_privacy_and_apps_default_settings: userData.consent_privacy_and_apps_default_settings || false,
                    consent_mates_default_settings: userData.consent_mates_default_settings || false,
                    language: userData.language || 'en',
                    darkmode: userData.darkmode || false,
                    // Low balance auto top-up fields
                    auto_topup_low_balance_enabled: userData.auto_topup_low_balance_enabled ?? false,
                    auto_topup_low_balance_threshold: userData.auto_topup_low_balance_threshold,
                    auto_topup_low_balance_amount: userData.auto_topup_low_balance_amount,
                    auto_topup_low_balance_currency: userData.auto_topup_low_balance_currency
                };
                updateProfile(userProfileData);
                console.log('[Login] User profile updated:', { username: userProfileData.username, credits: userProfileData.credits });
            } else {
                console.warn('[Login] No user data in auth_session - user profile not updated');
            }
            
            // Step 18: Dispatch login success
            // CRITICAL: Check if user is in signup flow based on last_opened
            // This ensures signup state is preserved after login
            // Note: userData is already declared above, so we reuse it
            const inSignupFlow = userData?.last_opened ? isSignupPath(userData.last_opened) : false;
            
            email = '';
            isPasskeyLoading = false;
            isLoading = false;
            dispatch('loginSuccess', {
                user: userData,
                isMobile,
                inSignupFlow: inSignupFlow
            });
            
        } catch (error: any) {
            console.error('Error during passkey login:', error);
            if (error.name === 'AbortError') {
                // User cancelled - already handled
                return;
            }
            
            // Check for chunk loading errors (stale cache after deployment)
            if (isChunkLoadError(error)) {
                logChunkLoadError('Login.passkeyLogin', error);
                notificationStore.error(CHUNK_ERROR_MESSAGE, CHUNK_ERROR_NOTIFICATION_DURATION);
                isPasskeyLoading = false;
                isLoading = false;
                return;
            }
            
            loginFailedWarning = true;
            isPasskeyLoading = false;
            isLoading = false;
        }
    }
    
    /**
     * Start Conditional UI (passkey autofill) flow
     * This allows the browser to show passkey suggestions in the username/email autofill dropdown
     * The user can select a passkey without clicking a separate button
     * Passkeys will appear automatically when the page loads, not just when clicking the field
     * 
     * Reference: https://web.dev/articles/passkey-form-autofill
     */
    async function startConditionalUIPasskey() {
        // Don't start if already active
        if (conditionalUIAbortController) {
            console.log('[Login] Conditional UI passkey request already active');
            return;
        }
        
        // Check if WebAuthn and Conditional UI are supported
        if (!window.PublicKeyCredential) {
            console.log('[Login] WebAuthn not supported');
            return;
        }
        
        // Check if conditional mediation is available (required for autofill passkeys)
        try {
            const conditionalMediationAvailable = await PublicKeyCredential.isConditionalMediationAvailable?.();
            if (!conditionalMediationAvailable) {
                console.log('[Login] Conditional UI (passkey autofill) not supported by browser');
                isConditionalUISupported = false;
                return;
            }
            isConditionalUISupported = true;
            console.log('[Login] Conditional UI (passkey autofill) is supported - starting automatic passkey suggestions');
        } catch (error) {
            console.log('[Login] Error checking conditional UI support:', error);
            isConditionalUISupported = false;
            return;
        }
        
        // Create abort controller for cancelling the request
        conditionalUIAbortController = new AbortController();
        
        try {
            const { getApiEndpoint, apiEndpoints } = await import('../config/api');
            const cryptoService = await import('../services/cryptoService');
            
            // Step 1: Initiate passkey assertion with backend (no email required for discoverable credentials)
            const initiateResponse = await fetch(getApiEndpoint(apiEndpoints.auth.passkey_assertion_initiate), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({}),
                credentials: 'include',
                signal: conditionalUIAbortController?.signal
            });
            
            if (!initiateResponse.ok) {
                const errorData = await initiateResponse.json();
                console.log('[Login] Conditional UI passkey initiation failed (expected if no passkeys registered):', errorData);
                return;
            }
            
            const initiateData = await initiateResponse.json();
            
            if (!initiateData.success) {
                console.log('[Login] Conditional UI passkey initiation failed:', initiateData.message);
                return;
            }
            
            // Step 2: Prepare WebAuthn request options for conditional UI
            const challenge = base64UrlToArrayBuffer(initiateData.challenge);
            
            // Prepare PRF extension input
            const prfEvalFirst = initiateData.extensions?.prf?.eval?.first || initiateData.challenge;
            const prfEvalFirstBuffer = base64UrlToArrayBuffer(prfEvalFirst);
            
            console.log('[Login] Conditional UI: preparing WebAuthn options');
            
            const publicKeyCredentialRequestOptions: PublicKeyCredentialRequestOptions = {
                challenge: challenge,
                rpId: initiateData.rp.id,
                timeout: initiateData.timeout,
                userVerification: initiateData.userVerification as UserVerificationRequirement,
                // Empty allowCredentials enables discoverable credential discovery
                allowCredentials: [],
                extensions: {
                    prf: {
                        eval: {
                            first: prfEvalFirstBuffer
                        }
                    }
                } as AuthenticationExtensionsClientInputs
            };
            
            // Step 3: Start conditional UI WebAuthn request
            // This will show passkey options in the autofill dropdown when user focuses the email field
            // The request waits silently until user selects a passkey from autofill
            console.log('[Login] Starting conditional UI passkey request (autofill mode)');
            
            let assertion: PublicKeyCredential;
            try {
                assertion = await navigator.credentials.get({
                    publicKey: publicKeyCredentialRequestOptions,
                    // CRITICAL: mediation: 'conditional' enables autofill mode
                    // This makes passkeys appear in the username/email field autofill dropdown
                    mediation: 'conditional',
                    signal: conditionalUIAbortController?.signal
                }) as PublicKeyCredential;
            } catch (error: any) {
                if (error.name === 'AbortError') {
                    console.log('[Login] Conditional UI passkey request was cancelled');
                    return;
                }
                // NotAllowedError can happen if user focuses input but doesn't select a passkey
                // or if the request times out - we should restart it in this case
                if (error.name === 'NotAllowedError') {
                    console.log('[Login] Conditional UI request completed without selection - will restart automatically if needed');
                    // Reset abort controller so it can be restarted
                    conditionalUIAbortController = null;
                    return;
                }
                console.log('[Login] Conditional UI WebAuthn error:', error);
                // Reset abort controller on error so it can be retried
                conditionalUIAbortController = null;
                return;
            }
            
            if (!assertion || !(assertion instanceof PublicKeyCredential)) {
                console.log('[Login] No assertion from conditional UI');
                return;
            }
            
            console.log('[Login] User selected passkey from autofill, processing login...');
            
            // Show loading state when user selects a passkey from autofill
            isPasskeyLoading = true;
            isLoading = true;
            
            // Process the passkey assertion (same flow as manual passkey login)
            await processPasskeyAssertion(assertion, initiateData, cryptoService);
            
            // Reset abort controller after successful processing so it can be restarted if needed
            conditionalUIAbortController = null;
            
        } catch (error: any) {
            if (error.name === 'AbortError') {
                console.log('[Login] Conditional UI request aborted');
                return;
            }
            console.error('[Login] Error in conditional UI passkey flow:', error);
            
            // Check for chunk loading errors (stale cache after deployment)
            if (isChunkLoadError(error)) {
                logChunkLoadError('Login.conditionalUIPasskey', error);
                notificationStore.error(CHUNK_ERROR_MESSAGE, CHUNK_ERROR_NOTIFICATION_DURATION);
            }
            
            // Reset abort controller on error so it can be retried
            conditionalUIAbortController = null;
        }
    }
    
    /**
     * Process passkey assertion - shared logic for both manual and conditional UI passkey flows
     * Handles PRF extraction, key derivation, master key unwrapping, and login completion
     */
    async function processPasskeyAssertion(
        assertion: PublicKeyCredential, 
        initiateData: any,
        cryptoService: typeof import('../services/cryptoService')
    ) {
        try {
            const { getApiEndpoint, apiEndpoints } = await import('../config/api');
            
            const response = assertion.response as AuthenticatorAssertionResponse;
            
            // Check PRF extension support
            const clientExtensionResults = assertion.getClientExtensionResults();
            console.log('[Login] Client extension results:', clientExtensionResults);
            const prfResults = clientExtensionResults?.prf as any;
            console.log('[Login] PRF results:', prfResults);
            
            // Validate PRF extension results
            if (!prfResults) {
                console.error('[Login] PRF extension not found in client extension results');
                loginFailedWarning = true;
                isPasskeyLoading = false;
                isLoading = false;
                return;
            }
            
            if (prfResults.enabled === false) {
                console.error('[Login] PRF extension explicitly disabled');
                loginFailedWarning = true;
                isPasskeyLoading = false;
                isLoading = false;
                return;
            }
            
            // Extract PRF signature
            const prfSignatureBuffer = prfResults.results?.first;
            if (!prfSignatureBuffer) {
                console.error('[Login] PRF signature not found in results');
                loginFailedWarning = true;
                isPasskeyLoading = false;
                isLoading = false;
                return;
            }
            
            // Convert PRF signature to Uint8Array (handle multiple formats)
            let prfSignature: Uint8Array;
            if (typeof prfSignatureBuffer === 'string') {
                const hexString = prfSignatureBuffer;
                prfSignature = new Uint8Array(hexString.match(/.{1,2}/g)!.map(byte => parseInt(byte, 16)));
            } else if (prfSignatureBuffer instanceof ArrayBuffer) {
                prfSignature = new Uint8Array(prfSignatureBuffer);
            } else if (ArrayBuffer.isView(prfSignatureBuffer)) {
                prfSignature = new Uint8Array(prfSignatureBuffer.buffer, prfSignatureBuffer.byteOffset, prfSignatureBuffer.byteLength);
            } else {
                console.error('[Login] PRF signature is in unknown format');
                loginFailedWarning = true;
                isPasskeyLoading = false;
                isLoading = false;
                return;
            }
            
            // Validate PRF signature length
            if (prfSignature.length < 16 || prfSignature.length > 64) {
                console.error('[Login] PRF signature has invalid length:', prfSignature.length);
                loginFailedWarning = true;
                isPasskeyLoading = false;
                isLoading = false;
                return;
            }
            
            console.log('[Login] PRF signature extracted successfully');
            
            // Extract credential data for backend
            const credentialId = arrayBufferToBase64Url(assertion.rawId);
            const clientDataJSONB64 = cryptoService.uint8ArrayToBase64(new Uint8Array(response.clientDataJSON));
            const authenticatorDataB64 = cryptoService.uint8ArrayToBase64(new Uint8Array(response.authenticatorData));
            
            // Verify passkey assertion with backend
            const verifyResponse = await fetch(getApiEndpoint(apiEndpoints.auth.passkey_assertion_verify), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    credential_id: credentialId,
                    assertion_response: {
                        authenticatorData: authenticatorDataB64,
                        clientDataJSON: clientDataJSONB64,
                        signature: cryptoService.uint8ArrayToBase64(new Uint8Array(response.signature)),
                        userHandle: response.userHandle ? cryptoService.uint8ArrayToBase64(new Uint8Array(response.userHandle)) : null
                    },
                    client_data_json: clientDataJSONB64,
                    authenticator_data: authenticatorDataB64,
                    stay_logged_in: stayLoggedIn,
                    session_id: getSessionId()
                }),
                credentials: 'include'
            });
            
            if (!verifyResponse.ok) {
                const errorData = await verifyResponse.json();
                console.error('[Login] Passkey assertion verification failed:', errorData);
                loginErrorMessage = errorData.message || null;
                loginFailedWarning = true;
                isPasskeyLoading = false;
                isLoading = false;
                return;
            }
            
            const verifyData = await verifyResponse.json();
            
            if (!verifyData.success) {
                console.error('[Login] Passkey verification failed:', verifyData.message);
                loginErrorMessage = verifyData.message || null;
                loginFailedWarning = true;
                isPasskeyLoading = false;
                isLoading = false;
                return;
            }
            
            // Get email salt from backend response
            let emailSalt = cryptoService.getEmailSalt();
            if (!emailSalt && verifyData.user_email_salt) {
                const { base64ToUint8Array } = await import('../services/cryptoService');
                emailSalt = base64ToUint8Array(verifyData.user_email_salt);
                cryptoService.saveEmailSalt(emailSalt, stayLoggedIn);
            }
            
            if (!emailSalt) {
                console.error('[Login] Email salt not found');
                loginFailedWarning = true;
                isPasskeyLoading = false;
                isLoading = false;
                return;
            }
            
            // Derive wrapping key from PRF signature using HKDF
            const wrappingKey = await cryptoService.deriveWrappingKeyFromPRF(prfSignature, emailSalt);
            
            // Unwrap master key
            const encryptedMasterKey = verifyData.encrypted_master_key;
            const keyIv = verifyData.key_iv;
            
            if (!encryptedMasterKey || !keyIv) {
                console.error('[Login] Missing encrypted master key or IV');
                loginFailedWarning = true;
                isPasskeyLoading = false;
                isLoading = false;
                return;
            }
            
            const masterKey = await cryptoService.decryptKey(encryptedMasterKey, keyIv, wrappingKey);
            
            if (!masterKey) {
                console.error('[Login] Failed to unwrap master key');
                loginFailedWarning = true;
                isPasskeyLoading = false;
                isLoading = false;
                return;
            }
            
            // Save master key to storage
            await cryptoService.saveKeyToSession(masterKey, stayLoggedIn);
            
            // Decrypt email using master key
            let userEmail = verifyData.user_email;
            if (!userEmail && verifyData.encrypted_email) {
                const { decryptWithMasterKey } = await import('../services/cryptoService');
                const decryptedEmail = await decryptWithMasterKey(verifyData.encrypted_email);
                if (decryptedEmail) {
                    userEmail = decryptedEmail;
                    console.log('[Login] Email decrypted from encrypted_email using master key');
                } else {
                    console.error('[Login] Failed to decrypt email with master key');
                    loginFailedWarning = true;
                    isPasskeyLoading = false;
                    isLoading = false;
                    return;
                }
            }
            
            if (!userEmail) {
                console.error('[Login] Email not available for key derivation');
                loginFailedWarning = true;
                isPasskeyLoading = false;
                isLoading = false;
                return;
            }
            
            // Derive email encryption key
            const emailEncryptionKey = await cryptoService.deriveEmailEncryptionKey(userEmail, emailSalt);
            cryptoService.saveEmailEncryptionKey(emailEncryptionKey, stayLoggedIn);
            cryptoService.saveEmailSalt(emailSalt, stayLoggedIn);
            
            // Generate lookup hash from PRF signature
            const lookupHash = await cryptoService.hashKeyFromPRF(prfSignature, emailSalt);
            
            // Authenticate with lookup_hash to get full auth session
            if (!verifyData.auth_session) {
                console.log('[Login] No auth_session in verify response, authenticating with lookup_hash');
                
                const hashedEmail = await cryptoService.hashEmail(userEmail);
                const { getSessionId: getSessionIdUtil } = await import('../utils/sessionId');
                
                const authResponse = await fetch(getApiEndpoint(apiEndpoints.auth.login), {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        hashed_email: hashedEmail,
                        lookup_hash: lookupHash,
                        email_encryption_key: cryptoService.getEmailEncryptionKeyForApi(),
                        login_method: 'passkey',
                        credential_id: credentialId,
                        stay_logged_in: stayLoggedIn,
                        session_id: getSessionIdUtil()
                    }),
                    credentials: 'include'
                });
                
                if (!authResponse.ok) {
                    const errorData = await authResponse.json();
                    console.error('[Login] Passkey authentication failed:', errorData);
                    loginFailedWarning = true;
                    isPasskeyLoading = false;
                    isLoading = false;
                    return;
                }
                
                const authData = await authResponse.json();
                
                if (!authData.success) {
                    console.error('[Login] Passkey authentication failed:', authData.message);
                    loginFailedWarning = true;
                    isPasskeyLoading = false;
                    isLoading = false;
                    return;
                }
                
                verifyData.auth_session = {
                    user: authData.user,
                    ws_token: authData.ws_token
                };
                console.log('[Login] Authentication successful via login endpoint');
            }
            
            // Store email encrypted with master key
            await cryptoService.saveEmailEncryptedWithMasterKey(userEmail, stayLoggedIn);
            
            // Store WebSocket token
            const wsToken = verifyData.auth_session?.ws_token;
            if (wsToken) {
                const { setWebSocketToken } = await import('../utils/cookies');
                setWebSocketToken(wsToken);
                console.debug('[Login] WebSocket token stored from login response');
            }
            
            // Update user profile
            const userData = verifyData.auth_session?.user;
            if (userData) {
                // Log auto top-up fields from backend response - ERROR if missing
                const hasAutoTopupFields = 'auto_topup_low_balance_enabled' in userData;
                if (!hasAutoTopupFields) {
                    console.error('[Login] ERROR: Auto top-up fields missing from backend response (passkey path 2)!');
                    console.error('[Login] Received user object keys:', Object.keys(userData));
                    console.error('[Login] Full user object:', userData);
                } else {
                    console.debug('[Login] Auto top-up fields from backend (passkey path 2):', {
                        enabled: userData.auto_topup_low_balance_enabled,
                        threshold: userData.auto_topup_low_balance_threshold,
                        amount: userData.auto_topup_low_balance_amount,
                        currency: userData.auto_topup_low_balance_currency
                    });
                }
                
                // CRITICAL: Reset forcedLogoutInProgress and isLoggingOut flags BEFORE any database operations
                // This handles the race condition where orphaned database cleanup was triggered on page load
                // (setting these flags to true) but the user then successfully logs in with passkey.
                // Without this reset, userDB.saveUserData() would throw "Database initialization blocked during logout"
                const { forcedLogoutInProgress, isLoggingOut } = await import('../stores/signupState');
                if (get(forcedLogoutInProgress)) {
                    console.debug('[Login] Resetting forcedLogoutInProgress to false - successful passkey login (path 2)');
                    forcedLogoutInProgress.set(false);
                }
                if (get(isLoggingOut)) {
                    console.debug('[Login] Resetting isLoggingOut to false - successful passkey login (path 2)');
                    isLoggingOut.set(false);
                }
                // Also clear the cleanup marker to prevent future false positives
                if (typeof localStorage !== 'undefined') {
                    localStorage.removeItem('openmates_needs_cleanup');
                }
                
                // Save to IndexedDB first
                const { userDB } = await import('../services/userDB');
                await userDB.saveUserData(userData);
                
                const { updateProfile } = await import('../stores/userProfile');
                const userProfileData = {
                    username: userData.username || '',
                    profile_image_url: userData.profile_image_url || null,
                    credits: userData.credits || 0,
                    is_admin: userData.is_admin || false,
                    last_opened: userData.last_opened || '',
                    tfa_app_name: userData.tfa_app_name || null,
                    tfa_enabled: userData.tfa_enabled || false,
                    consent_privacy_and_apps_default_settings: userData.consent_privacy_and_apps_default_settings || false,
                    consent_mates_default_settings: userData.consent_mates_default_settings || false,
                    language: userData.language || 'en',
                    darkmode: userData.darkmode || false,
                    // Low balance auto top-up fields
                    auto_topup_low_balance_enabled: userData.auto_topup_low_balance_enabled ?? false,
                    auto_topup_low_balance_threshold: userData.auto_topup_low_balance_threshold,
                    auto_topup_low_balance_amount: userData.auto_topup_low_balance_amount,
                    auto_topup_low_balance_currency: userData.auto_topup_low_balance_currency
                };
                updateProfile(userProfileData);
                console.log('[Login] User profile updated');
            }
            
            // Dispatch login success
            // CRITICAL: Check if user is in signup flow based on last_opened
            // This ensures signup state is preserved after login
            const inSignupFlow = userData?.last_opened ? isSignupPath(userData.last_opened) : false;
            
            email = '';
            isPasskeyLoading = false;
            isLoading = false;
            dispatch('loginSuccess', {
                user: userData,
                isMobile,
                inSignupFlow: inSignupFlow
            });
            
        } catch (error: any) {
            console.error('[Login] Error processing passkey assertion:', error);
            
            // Check for chunk loading errors (stale cache after deployment)
            if (isChunkLoadError(error)) {
                logChunkLoadError('Login.processPasskeyAssertion', error);
                notificationStore.error(CHUNK_ERROR_MESSAGE, CHUNK_ERROR_NOTIFICATION_DURATION);
                isPasskeyLoading = false;
                isLoading = false;
                return;
            }
            
            loginFailedWarning = true;
            isPasskeyLoading = false;
            isLoading = false;
            // Restart conditional UI if we're still on the email step after error
            if (currentLoginStep === 'email' && currentView === 'login') {
                restartConditionalUIPasskeyIfNeeded();
            }
        }
    }
    
    /**
     * Cancel the conditional UI passkey request
     * Should be called when switching to a different login flow or unmounting
     */
    function cancelConditionalUIPasskey() {
        if (conditionalUIAbortController) {
            conditionalUIAbortController.abort();
            conditionalUIAbortController = null;
            console.log('[Login] Conditional UI passkey request cancelled');
        }
    }
    
    /**
     * Restart conditional UI passkey flow if conditions are met
     * Called when the login view becomes visible again or after a passkey selection
     */
    function restartConditionalUIPasskeyIfNeeded() {
        if (
            currentView === 'login' && 
            !$authStore.isAuthenticated && 
            !$isCheckingAuth && 
            showForm && 
            currentLoginStep === 'email' &&
            !$isInSignupProcess &&
            !conditionalUIAbortController
        ) {
            console.log('[Login] Restarting conditional UI passkey flow');
            startConditionalUIPasskey();
        }
    }

    // Add debug subscription to track isInSignupProcess changes
    onMount(() => {
        // CRITICAL: Set screenWidth synchronously at the start of onMount
        // This ensures JavaScript state matches CSS media queries from the first render
        // Without this, screenWidth starts at 0, causing layout mismatch:
        // - CSS sees 780px and applies desktop layout (expects grids)
        // - JavaScript sees 0px and doesn't show grids
        // - Result: desktop layout without grids = content shifted left
        if (typeof window !== 'undefined') {
            screenWidth = window.innerWidth;
            isMobile = screenWidth < MOBILE_BREAKPOINT;
        }
        
        const unsubscribe = isInSignupProcess.subscribe(value => {
            console.debug(`[Login.svelte] isInSignupProcess changed to: ${value}`);
        });
        
        // Start conditional UI passkey flow immediately when component mounts
        // This enables automatic passkey suggestions as soon as the page loads
        // Don't wait for other async operations - start it right away
        if (!$authStore.isAuthenticated && !$isInSignupProcess) {
            // Check support and start asynchronously without blocking
            if (window.PublicKeyCredential) {
                PublicKeyCredential.isConditionalMediationAvailable?.().then((available) => {
                    if (available) {
                        isConditionalUISupported = true;
                        // The reactive effect will start it when conditions are met
                    }
                }).catch(() => {
                    // Browser doesn't support conditional UI, that's okay
                });
            }
        }
        
        (async () => {
            // Check if device is touch-enabled
            isTouchDevice = 'ontouchstart' in window || navigator.maxTouchPoints > 0;
            
            showLoadingUntil = Date.now() + 500;
            
            // Check if user is in signup process based on last_opened
            if ($authStore.isAuthenticated && isSignupPath($userProfile.last_opened)) {
                // Get step name from path using the function from signupState
                const stepName = getStepFromPath($userProfile.last_opened);
                currentSignupStep.set(stepName);
                isInSignupProcess.set(true); // This will set currentView reactively
            }
            
            // Update screen width (already set above, but ensure it's current after any delays)
            // This handles edge cases where viewport might have changed
            if (typeof window !== 'undefined') {
                screenWidth = window.innerWidth;
                isMobile = screenWidth < MOBILE_BREAKPOINT;
            }
            
            const remainingTime = showLoadingUntil - Date.now();
            if (remainingTime > 0) {
                await new Promise(resolve => setTimeout(resolve, remainingTime));
            }
            
            await tick();
            showForm = true; // Show form before removing loading state
            // Note: gridsReady is now initialized to true, so grids show immediately
            
            // Only focus if not touch device and not authenticated
            if (!$authStore.isAuthenticated && emailInput && !isTouchDevice) {
                emailInput.focus();
            }

            // Check if we're still rate limited
            const rateLimitTimestamp = localStorage.getItem('loginRateLimit');
            if (rateLimitTimestamp) {
                const timeLeft = parseInt(rateLimitTimestamp) + RATE_LIMIT_DURATION - Date.now();
                if (timeLeft > 0) {
                    isRateLimited = true;
                    setRateLimitTimer(timeLeft);
                } else {
                    localStorage.removeItem('loginRateLimit');
                }
            }

            const lockoutUntil = localStorage.getItem('policy_violation_lockout');
            if (lockoutUntil) {
                const lockoutTime = parseInt(lockoutUntil);
                if (Date.now() < lockoutTime) {
                    isPolicyViolationLockout = true;
                    setTimeout(() => {
                        isPolicyViolationLockout = false;
                        localStorage.removeItem('policy_violation_lockout');
                    }, lockoutTime - Date.now());
                } else {
                    localStorage.removeItem('policy_violation_lockout');
                }
            }

            // Check if account was deleted
            isAccountDeleted = sessionStorage.getItem('account_deleted') === 'true';
            if (isAccountDeleted) {
                // Clear after reading once
                sessionStorage.removeItem('account_deleted');
            }
        })();
        
        // Add event listener for account deletion
        const handleAccountDeleted = () => {
            console.debug("Account deletion event received");
            accountJustDeleted = true;
            isAccountDeleted = true;
        };
        
        window.addEventListener('account-deleted', handleAccountDeleted);
        
        // Handle resize events
        const handleResize = () => {
            screenWidth = window.innerWidth;
            isMobile = screenWidth < MOBILE_BREAKPOINT;
        }; 
        window.addEventListener('resize', handleResize);
        
        // --- Inactivity Timer Cleanup ---
        return () => {
            unsubscribe();
            window.removeEventListener('resize', handleResize);
            window.removeEventListener('account-deleted', handleAccountDeleted);
            // Clear timer on component destruction
            if (inactivityTimer) {
                clearTimeout(inactivityTimer);
                console.debug("Login inactivity timer cleared on destroy");
            }
        };
        // --- End Inactivity Timer Cleanup ---
    });

    onDestroy(() => {
        if (rateLimitTimer) {
            clearTimeout(rateLimitTimer);
        }
        // Ensure timer is cleared if onMount cleanup didn't run or failed
        if (inactivityTimer) {
            clearTimeout(inactivityTimer);
        }
        // Clear connection timeout
        if (connectionTimeoutId) {
            clearTimeout(connectionTimeoutId);
            connectionTimeoutId = null;
        }
        
        // Cancel any pending conditional UI passkey request
        cancelConditionalUIPasskey();
        
        // Cancel any pending manual passkey login request
        if (passkeyLoginAbortController) {
            passkeyLoginAbortController.abort();
            passkeyLoginAbortController = null;
        }
        
        // PRIVACY: Clear pending draft when component is destroyed
        // This ensures the saved message is deleted if user closes the login interface
        // Note: This is a safety measure - the draft should already be cleared when user
        // switches views or clicks back, but this ensures cleanup even if component unmounts unexpectedly
        clearPendingDraft();
    });

    // --- Inactivity Timer Functions (Login/2FA/Device Verify) ---
    function handleInactivityTimeout() {
        // IMPORTANT: Do NOT reset the login interface if user is in account recovery mode
        // Account recovery is a multi-step process that requires verification code from email
        // and users need time to complete it without being interrupted
        if (isInAccountRecoveryMode) {
            console.debug("Login inactivity timeout triggered but user is in account recovery mode - NOT resetting.");
            // Just reset the timer, don't clear the form
            resetInactivityTimer();
            return;
        }
        
        console.debug("Login inactivity timeout triggered - resetting to email step for privacy/security.");
        
        // Clear all form data
        email = '';
        password = '';

        localStorage.clear();
        sessionStorage.clear();
        
        // Reset to email step (EmailLookup component)
        currentLoginStep = 'email';
        
        // Clear any error states
        loginFailedWarning = false;
        tfaErrorMessage = null;
        verifyDeviceErrorMessage = null;
        
        // Hide 2FA and device verification views
        showTfaView = false;
        needsDeviceVerification.set(false);
        
        // Stop the timer
        stopInactivityTimer();
        
        // Focus email input after a tick if not touch device
        tick().then(() => {
            if (emailInput && !isTouchDevice) {
                emailInput.focus();
            }
        });
    }

    function resetInactivityTimer() {
        if (inactivityTimer) clearTimeout(inactivityTimer);
        console.debug("Resetting Login/2FA/Device Verify inactivity timer...");
        inactivityTimer = setTimeout(handleInactivityTimeout, LOGIN_INACTIVITY_TIMEOUT_MS);
        isTimerActive = true;
    }

    function stopInactivityTimer() {
        if (inactivityTimer) {
            clearTimeout(inactivityTimer);
            console.debug("Stopping Login/2FA/Device Verify inactivity timer.");
            inactivityTimer = null;
        }
        isTimerActive = false;
    }

    function checkActivityAndManageTimer() {
        // Check if any login step is active (not just email step) OR if 2FA/Device Verify view is active
        const isInActiveLoginStep = currentLoginStep !== 'email' || email || password || showTfaView || showVerifyDeviceView;
        
        if (isInActiveLoginStep) {
            if (!isTimerActive) {
                console.debug("Login activity detected or active step/view, starting inactivity timer.");
            }
            resetInactivityTimer();
        } else {
            if (isTimerActive) {
                console.debug("No active login step and fields empty, stopping inactivity timer.");
                stopInactivityTimer();
            }
        }
    }
    // --- End Inactivity Timer Functions ---


    // Handler to switch back from 2FA or Device Verify view to standard login
    function handleSwitchBackToLogin() {
        showTfaView = false;
        needsDeviceVerification.set(false); // Explicitly turn off device verification flag
        email = ''; // Clear email
        password = ''; // Clear password
        tfaErrorMessage = null; // Clear 2FA errors
        verifyDeviceErrorMessage = null; // Clear device verification errors
        loginFailedWarning = false; // Clear general login errors
        // Reset to email step
        currentLoginStep = 'email';
        
        // PRIVACY: Clear pending draft when user switches back from 2FA/Device Verify to login
        // This ensures the saved message is deleted if user doesn't complete the flow
        clearPendingDraft();
        
        // Optionally focus email input after a tick if not touch
        tick().then(() => {
            if (emailInput && !isTouchDevice) {
                emailInput.focus();
            }
        });
    }

    // Strengthen the reactive statement to switch views when in signup process
    // Also reset showTfaView and showVerifyDeviceView if user logs out or switches to signup
    // Reset views if switching away from login or logging out using $effect (Svelte 5 runes mode)
    $effect(() => {
        // Only reset if view changes OR user is fully logged out (not just intermediate state)
        if (currentView !== 'login' || (!$authStore.isAuthenticated && !$authStore.isInitialized)) {
            tfaErrorMessage = null;
            verifyDeviceErrorMessage = null;
            // Check timer status when view changes or user logs out
            // This will stop the timer if fields are empty and not in an active view
            checkActivityAndManageTimer();
        }
    });

    $effect(() => {
        // Manage timer based on showTfaView or showVerifyDeviceView state changes
        if (showTfaView || showVerifyDeviceView) {
            console.debug("2FA or Device Verify view shown, ensuring timer is active.");
            checkActivityAndManageTimer(); // Start/reset timer when view appears
        } else {
             // When views are hidden (e.g., manual switch back, timeout, login success)
             // check if timer should stop (if email/password are also empty)
            checkActivityAndManageTimer();
        }
    });

    // Derive the main view from the signup process state. This is more robust against race conditions using $derived (Svelte 5 runes mode)
    let currentView = $derived($isInSignupProcess ? 'signup' : 'login');
    
    // Determine if tabs should be visible
    // Tabs should only be visible on login screen or during alpha disclaimer and basics steps
    // Once user reaches confirm email step, tabs should be hidden
    let showTabs = $derived(
        currentView === 'login' || 
        (currentView === 'signup' && ($currentSignupStep === STEP_ALPHA_DISCLAIMER || $currentSignupStep === STEP_BASICS))
    );
    
    // State for SignupNav (exposed from Signup component via bindable props)
    let signupSelectedAppName = $state<string | null>(null);
    let signupIsAdmin = $state(false);
    let signupIsInviteCodeValidated = $state(false);
    let signupShowSkip = $state(false);
    
    // Store references to Signup component's internal handlers
    // These will be set up to call Signup's handlers when invoked
    let signupCloseToDemo: (() => Promise<void>) | null = null;
    let signupStepFromNav: ((event: { step: string }) => void) | null = null;
    let signupSkip: (() => void) | null = null;
    let signupLogout: (() => Promise<void>) | null = null;
    
    // Handlers for SignupNav - these call the callbacks passed to Signup
    // Signup will update these callbacks (via bindable) to call its internal handlers
    async function handleSignupNavBack() {
        // Call the callback - Signup has updated it to call handleCloseToDemo
        onSignupNavBack();
    }
    
    function handleSignupNavStep(event: { step: string }) {
        // Call the callback - Signup has updated it to call handleStepFromNav
        onSignupNavStep(event);
    }
    
    function handleSignupNavSkip() {
        // Call the callback - Signup has updated it to call handleSkip
        onSignupNavSkip();
    }
    
    async function handleSignupNavLogout() {
        // Call the callback - Signup has updated it to call handleLogout
        await onSignupNavLogout();
    }
    
    // Callbacks passed to Signup - Signup will update these (via bindable) to call its internal handlers
    let onSignupNavBack = $state<() => void>(() => {});
    let onSignupNavStep = $state<(event: { step: string }) => void>(() => {});
    let onSignupNavSkip = $state<() => void>(() => {});
    let onSignupNavLogout = $state<() => Promise<void>>(async () => {});

    // Ensure form is shown when login view becomes visible (fixes issue when login interface is opened manually)
    // This handles the case where the Login component is shown/hidden without remounting
    $effect(() => {
        // When we're in login view and not authenticated, ensure the form is visible
        if (currentView === 'login' && !$authStore.isAuthenticated && !$isCheckingAuth) {
            // Use a small delay to ensure component is properly mounted/visible
            // Set a timeout to show the form even if onMount initialization hasn't completed
            const timeoutId = setTimeout(() => {
                showForm = true;
            }, 300); // Small delay to allow component to mount
            
            // Also try immediately after tick (in case component is already mounted)
            tick().then(() => {
                clearTimeout(timeoutId);
                showForm = true;
            });
            
            // Cleanup function to clear timeout if effect runs again
            return () => {
                clearTimeout(timeoutId);
            };
        }
    });

    // Start conditional UI passkey flow automatically when login view is visible
    // This enables passkeys to appear in the browser's autofill dropdown automatically
    // without requiring the user to click on the email field first
    $effect(() => {
        // Start conditional UI when:
        // 1. We're in login view (not signup)
        // 2. User is not authenticated
        // 3. Auth check is complete (not checking)
        // 4. Form is visible
        // 5. We're on the email step
        // 6. Not already active
        if (
            currentView === 'login' &&
            !$authStore.isAuthenticated &&
            !$isCheckingAuth &&
            showForm &&
            currentLoginStep === 'email' &&
            !$isInSignupProcess &&
            !conditionalUIAbortController
        ) {
            // Start conditional UI passkey flow (autofill passkeys)
            // This enables the OS/browser to show passkey suggestions automatically
            // The request will wait silently until user interacts with the email field
            console.log('[Login] Starting conditional UI passkey flow for automatic passkey suggestions');
            startConditionalUIPasskey();
        } else {
            // Cancel conditional UI if we're not in the right state
            if (conditionalUIAbortController && (currentView !== 'login' || $isInSignupProcess || currentLoginStep !== 'email')) {
                cancelConditionalUIPasskey();
            }
        }
    });

    // Monitor isCheckingAuth state and set timeout for server connection
    $effect(() => {
        // Clear any existing timeout when checking state changes
        if (connectionTimeoutId) {
            clearTimeout(connectionTimeoutId);
            connectionTimeoutId = null;
        }
        
        // When auth check starts, set a timeout
        if ($isCheckingAuth) {
            serverConnectionError = false; // Reset error state
            connectionTimeoutId = setTimeout(() => {
                // If still checking after timeout, show connection error
                if ($isCheckingAuth) {
                    console.warn("[Login] Server connection timeout - showing error message");
                    serverConnectionError = true;
                }
            }, SERVER_TIMEOUT_MS);
        } else {
            // Auth check completed (success or error), clear error state
            serverConnectionError = false;
        }
        
        // Cleanup function
        return () => {
            if (connectionTimeoutId) {
                clearTimeout(connectionTimeoutId);
                connectionTimeoutId = null;
            }
        };
    });

    // Handle other side-effects reactively using $effect (Svelte 5 runes mode)
    $effect(() => {
        if ($isInSignupProcess) {
            stopInactivityTimer();
        } else if (!$authStore.isAuthenticated) {
            stopInactivityTimer();
        }

        if (!$authStore.isAuthenticated) {
            if (sessionStorage.getItem('account_deleted') === 'true' || accountJustDeleted) {
                console.debug("Account deleted, showing deletion message");
                isAccountDeleted = true;
                isPolicyViolationLockout = true;
                
                if (accountJustDeleted) {
                    accountJustDeleted = false;
                }
            }
        }
    });
</script>

{#if !$authStore.isAuthenticated || $isInSignupProcess}
    <div class="login-container" bind:this={loginContainer} in:fade={{ duration: 300 }} out:fade={{ duration: 300 }}>
        <!-- Report issue button - fixed to top left for easy access during login/signup -->
        <div class="report-issue-button-wrapper">
            <button
                class="clickable-icon icon_bug report-issue-button"
                aria-label={$text('header.report_issue.text')}
                onclick={handleReportIssue}
                use:tooltip
            >
            </button>
        </div>
        
        {#if showDesktopGrids && gridsReady}
            <AppIconGrid iconGrid={leftIconGrid} shifted="columns" size={DESKTOP_ICON_SIZE}/>
        {/if}
        <div class="login-content">
                {#if showMobileGrid && gridsReady}
                    <div class="mobile-grid-fixed">
                        <AppIconGrid iconGrid={mobileIconGrid} shifted="columns" shifting="10px" gridGap="2px" size={MOBILE_ICON_SIZE} />
                    </div>
                {/if}
                
                <div class="login-box" class:payment-step={$currentSignupStep === STEP_PAYMENT} in:scale={{ duration: 300, delay: 150 }}>
                <!-- SignupNav - handles both login and signup navigation -->
                <!-- Show SignupNav when NOT authenticated OR when in signup process (even if authenticated) -->
                {#if !$authStore.isAuthenticated || $isInSignupProcess}
                    <SignupNav
                        mode={$isInSignupProcess ? 'signup' : 'login'}
                        onback={handleSignupNavBack}
                        onstep={handleSignupNavStep}
                        onskip={handleSignupNavSkip}
                        onlogout={handleSignupNavLogout}
                        onDemoClick={() => {
                            console.log('[Login] Demo back button clicked - closing login interface and returning to demo');
                            // PRIVACY: Clear signup data (email and username) when returning to demo
                            // This ensures sensitive data is removed if user abandons signup
                            clearSignupData();
                            // Clear email encryption key and salt when interrupting login to go back to demo
                            // This ensures sensitive data is removed if user abandons login attempt
                            cryptoService.clearAllEmailData();
                            // CRITICAL: Clear all sessionStorage drafts when returning to demo mode
                            // This ensures drafts don't persist if user interrupts login/signup
                            clearAllSessionStorageDrafts();
                            console.debug('[Login] Cleared all sessionStorage drafts when returning to demo');
                            // Dispatch event to close login interface and show demo
                            window.dispatchEvent(new CustomEvent('closeLoginInterface'));
                            // Also dispatch loadDemoChat event to ensure demo chat is loaded
                            // Small delay to ensure the interface closes before loading chat
                            setTimeout(() => {
                                window.dispatchEvent(new CustomEvent('loadDemoChat'));
                            }, 100);
                        }}
                        showSkip={signupShowSkip}
                        currentStep={$currentSignupStep}
                        selectedAppName={signupSelectedAppName}
                        showAdminButton={signupIsAdmin && $currentSignupStep === STEP_BASICS && signupIsInviteCodeValidated}
                    />
                {/if}
                {#if isPolicyViolationLockout || isAccountDeleted}
                    <div class="content-area" in:fade={{ duration: 400 }}>
                        <h1><mark>{@html $text('login.login.text')}</mark></h1>
                        <h2>{@html $text('login.to_chat_to_your.text')}<br><mark>{@html $text('login.digital_team_mates.text')}</mark></h2>
                        
                        <div class="form-container">
                            <p class="violation-message">
                                {@html $text('settings.your_account_got_deleted.text')}
                            </p>
                        </div>
                    </div>
                {:else if currentView === 'login'}
                    <div class="content-area" in:fade={{ duration: 400 }}>
                        <!-- Login/Signup tabs - only show on login screen -->
                        {#if showTabs}
                            <div class="login-tabs">
                                <button 
                                    class="tab-button active"
                                    onclick={() => {
                                        // Already on login view, no action needed
                                    }}
                                >
                                    {$text('login.login.text')}
                                </button>
                                <button 
                                    class="tab-button"
                                    onclick={switchToSignup}
                                >
                                    {$text('signup.sign_up.text')}
                                </button>
                            </div>
                        {/if}
                        
                        <h1><mark>{@html $text('login.login.text')}</mark></h1>
                        <h2>{@html $text('login.to_chat_to_your.text')}<br><mark>{@html $text('login.digital_team_mates.text')}</mark></h2>

                        <div class="form-container">
                            {#if showVerifyDeviceView}
                                <!-- Show Device Verification Component -->
                                <div in:fade={{ duration: 200 }}>
                                    <VerifyDevice2FA
                                        bind:isLoading
                                        bind:errorMessage={verifyDeviceErrorMessage}
                                        on:deviceVerified={async () => {
                                            console.debug("Device verified event received, re-checking auth...");
                                            verifyDeviceErrorMessage = null; // Clear error on success signal
                                            await checkAuth(); // Use imported checkAuth function
                                        }}
                                        on:switchToLogin={handleSwitchBackToLogin}
                                        on:tfaActivity={checkActivityAndManageTimer}
                                    />
                                </div>
                            {:else if isRateLimited}
                                <div class="rate-limit-message" in:fade={{ duration: 200 }}>
                                    {$text('signup.too_many_requests.text')}
                                </div>
                            {:else if $isCheckingAuth && !serverConnectionError}
                                <div class="checking-auth" in:fade={{ duration: 200 }}>
                                    <p>{@html $text('login.loading.text')}</p>
                                </div>
                            {:else if serverConnectionError}
                                <div class="connection-error" in:fade={{ duration: 200 }}>
                                    <p>{@html $text('login.cant_connect_to_server.text')}</p>
                                    <button 
                                        class="retry-button"
                                        onclick={() => {
                                            serverConnectionError = false;
                                            // Retry auth check
                                            checkAuth();
                                        }}
                                    >
                                        {$text('login.retry.text')}
                                    </button>
                                </div>
                            {:else}
                                <!-- Show Standard Login Form -->
                                <div
                                    class:visible={showForm}
                                    class:hidden={!showForm}
                                >
                                    {#if currentLoginStep === 'email'}
                                        {#if isPasskeyLoading}
                                            <!-- Passkey loading screen - replaces form elements -->
                                            <div class="passkey-loading-screen">
                                                <div class="passkey-loading-icon">
                                                    <span class="clickable-icon icon_passkey" style="width: 64px; height: 64px;"></span>
                                                </div>
                                                <p class="passkey-loading-text">{$text('login.logging_in_with_passkey.text')}</p>
                                            </div>
                                        {:else}
                                            <!-- Use EmailLookup component for email input -->
                                            <EmailLookup
                                                bind:email
                                                bind:isLoading
                                                bind:loginFailedWarning
                                                bind:stayLoggedIn
                                                isPasskeyLoading={isPasskeyLoading}
                                                onPasskeyClick={startPasskeyLogin}
                                                onCancelPasskey={cancelPasskeyLogin}
                                                on:lookupSuccess={(e) => {
                                                    availableLoginMethods = e.detail.availableLoginMethods;
                                                    preferredLoginMethod = e.detail.preferredLoginMethod;
                                                    stayLoggedIn = e.detail.stayLoggedIn;
                                                    tfaAppName = e.detail.tfa_app_name;
                                                    // tfa_enabled indicates if 2FA is actually configured (encrypted_tfa_secret exists)
                                                    // tfa_app_name is optional metadata and doesn't determine if 2FA is configured
                                                    tfaEnabled = e.detail.tfa_enabled || false;
                                                    // Use the helper function to safely set the login step
                                                    // Always go to password step after email lookup
                                                    // The user can use the "Login with passkey" button on the main screen if they want to use passkey
                                                    setLoginStep('password');
                                                }}
                                                on:userActivity={resetInactivityTimer}
                                            />
                                        {/if}
                                    {:else}
                                        <!-- Show appropriate login method component based on currentLoginStep -->
                                        {#if currentLoginStep === 'password'}
                                            <!-- Use PasswordAndTfaOtp component -->
                                            <PasswordAndTfaOtp
                                                {email}
                                                bind:isLoading
                                                errorMessage={loginErrorMessage || (loginFailedWarning ? $text('login.login_failed.text') : null)}
                                                {stayLoggedIn}
                                                {tfaAppName}
                                                tfa_required={tfaEnabled}
                                                on:loginSuccess={async (e) => {
                                                    console.log("Login success, in signup flow:", e.detail.inSignupFlow);
                                                    
                                                    // If user is in signup flow, set up the signup state
                                                    // Note: inSignupFlow can be true even if last_opened doesn't indicate signup
                                                    // (e.g., if tfa_enabled is false but last_opened was overwritten to demo-for-everyone)
                                                    // The signup step should already be set in PasswordAndTfaOtp, but we respect it here
                                                    if (e.detail.inSignupFlow) {
                                                        // If last_opened indicates a signup step, use it; otherwise default to one_time_codes
                                                        // (the actual OTP setup step, not the app reminder step)
                                                        const stepName = isSignupPath(e.detail.user?.last_opened)
                                                            ? getStepFromPath(e.detail.user.last_opened)
                                                            : STEP_ONE_TIME_CODES;
                                                        console.log("Setting signup step:", e.detail.user?.last_opened, "->", stepName);
                                                        currentSignupStep.set(stepName);
                                                        isInSignupProcess.set(true);
                                                        await tick(); // Wait for state to update
                                                    }
                                                    
                                                    email = '';
                                                    currentLoginStep = 'email';
                                                    // Reset account recovery mode on successful login
                                                    isInAccountRecoveryMode = false;
                                                    dispatch('loginSuccess', {
                                                        user: e.detail.user,
                                                        isMobile,
                                                        inSignupFlow: e.detail.inSignupFlow
                                                    });
                                                }}
                                                on:backToEmail={() => {
                                                    email = ''; // Clear email when going back to email step
                                                    currentLoginStep = 'email';
                                                    // Reset account recovery mode when going back to email
                                                    isInAccountRecoveryMode = false;
                                                }}
                                                on:switchToBackupCode={(e) => {
                                                    // Handle switch to backup code
                                                    currentLoginStep = 'backup_code';
                                                }}
                                                on:switchToRecoveryKey={() => {
                                                    // Handle switch to recovery key
                                                    currentLoginStep = 'recovery_key';
                                                }}
                                                on:accountRecoveryModeChanged={(e) => {
                                                    // Track account recovery mode to prevent inactivity timer from resetting
                                                    isInAccountRecoveryMode = e.detail.active;
                                                    console.debug('[Login] Account recovery mode changed:', e.detail.active);
                                                    // Reset inactivity timer when entering/exiting account recovery
                                                    if (e.detail.active) {
                                                        resetInactivityTimer();
                                                    }
                                                }}
                                                on:tfaActivity={resetInactivityTimer}
                                                on:userActivity={resetInactivityTimer}
                                            />
                                        {:else if currentLoginStep === 'backup_code'}
                                            <!-- Use EnterBackupCode component -->
                                            <EnterBackupCode
                                                {email}
                                                {password}
                                                {stayLoggedIn}
                                                bind:isLoading
                                                errorMessage={loginErrorMessage || (loginFailedWarning ? $text('login.login_failed.text') : null)}
                                                on:loginSuccess={async (e) => {
                                                    console.log("Login success (backup code), in signup flow:", e.detail.inSignupFlow);
                                                    
                                                    // If user is in signup flow, set up the signup state
                                                    // Note: inSignupFlow can be true even if last_opened doesn't indicate signup
                                                    // (e.g., if tfa_enabled is false but last_opened was overwritten to demo-for-everyone)
                                                    // The signup step should already be set in PasswordAndTfaOtp, but we respect it here
                                                    if (e.detail.inSignupFlow) {
                                                        // If last_opened indicates a signup step, use it; otherwise default to one_time_codes
                                                        // (the actual OTP setup step, not the app reminder step)
                                                        const stepName = isSignupPath(e.detail.user?.last_opened)
                                                            ? getStepFromPath(e.detail.user.last_opened)
                                                            : STEP_ONE_TIME_CODES;
                                                        console.log("Setting signup step:", e.detail.user?.last_opened, "->", stepName);
                                                        currentSignupStep.set(stepName);
                                                        isInSignupProcess.set(true);
                                                        await tick(); // Wait for state to update
                                                    }
                                                    
                                                    email = '';
                                                    password = '';
                                                    currentLoginStep = 'email';
                                                    dispatch('loginSuccess', {
                                                        user: e.detail.user,
                                                        isMobile,
                                                        inSignupFlow: e.detail.inSignupFlow
                                                    });
                                                }}
                                                on:backToEmail={() => {
                                                    email = ''; // Clear email when going back to email step
                                                    currentLoginStep = 'email';
                                                }}
                                                on:switchToOtp={() => currentLoginStep = 'password'}
                                                on:userActivity={resetInactivityTimer}
                                            />
                                        {:else if currentLoginStep === 'recovery_key'}
                                            <!-- Use EnterRecoveryKey component -->
                                            <EnterRecoveryKey
                                                {email}
                                                {stayLoggedIn}
                                                bind:isLoading
                                                errorMessage={loginErrorMessage || (loginFailedWarning ? $text('login.login_failed.text') : null)}
                                                on:loginSuccess={async (e) => {
                                                    console.log("Login success (recovery key), in signup flow:", e.detail.inSignupFlow);
                                                    
                                                    // If user is in signup flow, set up the signup state
                                                    // Note: inSignupFlow can be true even if last_opened doesn't indicate signup
                                                    // (e.g., if tfa_enabled is false but last_opened was overwritten to demo-for-everyone)
                                                    // The signup step should already be set in PasswordAndTfaOtp, but we respect it here
                                                    if (e.detail.inSignupFlow) {
                                                        // If last_opened indicates a signup step, use it; otherwise default to one_time_codes
                                                        // (the actual OTP setup step, not the app reminder step)
                                                        const stepName = isSignupPath(e.detail.user?.last_opened)
                                                            ? getStepFromPath(e.detail.user.last_opened)
                                                            : STEP_ONE_TIME_CODES;
                                                        console.log("Setting signup step:", e.detail.user?.last_opened, "->", stepName);
                                                        currentSignupStep.set(stepName);
                                                        isInSignupProcess.set(true);
                                                        await tick(); // Wait for state to update
                                                    }
                                                    
                                                    email = '';
                                                    currentLoginStep = 'email';
                                                    dispatch('loginSuccess', {
                                                        user: e.detail.user,
                                                        isMobile,
                                                        inSignupFlow: e.detail.inSignupFlow
                                                    });
                                                }}
                                                on:backToEmail={() => {
                                                    email = ''; // Clear email when going back to email step
                                                    currentLoginStep = 'email';
                                                }}
                                                on:switchToOtp={() => currentLoginStep = 'password'}
                                                on:userActivity={resetInactivityTimer}
                                            />
                                        {:else if currentLoginStep === 'security_key'}
                                            <!-- TODO: Replace with SecurityKey component -->
                                            <div class="placeholder-component">
                                                <p>Security Key Component (to be implemented later)</p>
                                                <button type="button" onclick={() => currentLoginStep = 'email'}>Back to Email</button>
                                            </div>
                                        {/if}
                                    {/if}
                                </div>
                            {/if} <!-- End standard login form / rate limit / loading block -->
                        </div> <!-- End form-container -->

                    </div> <!-- End content-area for login view -->
                {:else} <!-- Handles currentView !== 'login' -->
                    <div class="content-area" in:fade={{ duration: 200 }}>
                        <!-- Login/Signup tabs - only show during alpha disclaimer and basics steps -->
                        {#if showTabs}
                            <div class="login-tabs">
                                <button 
                                    class="tab-button"
                                    onclick={switchToLogin}
                                >
                                    {$text('login.login.text')}
                                </button>
                                <button 
                                    class="tab-button active"
                                    onclick={() => {
                                        // Already on signup view, no action needed
                                    }}
                                >
                                    {$text('signup.sign_up.text')}
                                </button>
                            </div>
                        {/if}
                        <Signup 
                            onswitchToLogin={switchToLogin}
                            bind:selectedAppName={signupSelectedAppName}
                            bind:is_admin={signupIsAdmin}
                            bind:isInviteCodeValidated={signupIsInviteCodeValidated}
                            bind:showSkip={signupShowSkip}
                            bind:onSignupNavBack
                            bind:onSignupNavStep
                            bind:onSignupNavSkip
                            bind:onSignupNavLogout
                        />
                        <!-- Removed stray </button> here -->
                    </div>
                {/if} <!-- This closes the main #if / :else if / :else block -->
            </div> <!-- End login-box -->
        </div> <!-- End login-content -->

        {#if showDesktopGrids && gridsReady}
            <AppIconGrid iconGrid={rightIconGrid} shifted="columns" size={DESKTOP_ICON_SIZE}/>
        {/if}
    </div>
{/if}

<style>
    .violation-message {
        color: var(--color-error);
        padding: 24px;
        text-align: center;
        font-weight: 500;
        font-size: 16px;
        line-height: 1.5;
        background-color: var(--color-error-light);
        border-radius: 8px;
        margin: 24px 0;
    }
    
    /* Passkey loading screen */
    .passkey-loading-screen {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        padding: 40px 20px;
        min-height: 200px;
    }
    
    .passkey-loading-icon {
        margin-bottom: 24px;
    }
    
    .passkey-loading-icon .clickable-icon {
        width: 64px;
        height: 64px;
        background-color: var(--color-primary-start);
        border-radius: 16px;
    }
    
    .passkey-loading-text {
        color: var(--color-grey-80);
        font-size: 16px;
        font-weight: 500;
        margin: 0;
        text-align: center;
    }

    /* Navigation area styles moved to SignupNav.svelte to avoid duplication */

    /* Connection error styles */
    .connection-error {
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        gap: 1rem;
        background-color: var(--color-grey-20);
        z-index: 1;
        padding: 2rem;
        text-align: center;
    }

    .connection-error p {
        color: var(--color-error);
        font-size: 1.1rem;
        margin: 0;
    }

    .retry-button {
        all: unset;
        padding: 10px 20px;
        border-radius: 8px;
        background-color: var(--color-button-primary);
        color: white;
        font-size: 14px;
        font-weight: 500;
        cursor: pointer;
        transition: all 0.2s ease;
        margin-top: 0.5rem;
    }

    .retry-button:hover {
        background-color: var(--color-button-primary-hover);
        transform: scale(1.02);
    }

    .retry-button:active {
        background-color: var(--color-button-primary-pressed);
        transform: scale(0.98);
    }

    /* Login/Signup tabs - Modern segmented control design */
    .login-tabs {
        display: flex;
        gap: 8px;
        margin-bottom: 32px;
        padding: 4px;
        background-color: var(--color-grey-0);
        border-radius: 12px;
        position: relative;
    }

    .tab-button {
        all: unset;
        flex: 1;
        padding: 12px 20px;
        text-align: center;
        font-size: 16px;
        font-weight: 500;
        color: var(--color-grey-70);
        cursor: pointer;
        border-radius: 8px;
        transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
        position: relative;
        z-index: 1;
    }

    .tab-button:hover:not(.active) {
        color: var(--color-text);
        background-color: var(--color-grey-20);
    }

    .tab-button.active {
        color: var(--color-font-button);
        background: var(--color-primary);
        box-shadow: 0 2px 8px rgba(72, 107, 205, 0.25);
        font-weight: 600;
    }

    .tab-button:active:not(.active) {
        transform: scale(0.98);
    }

    /* Report issue button - positioned at top left of login container */
    .report-issue-button-wrapper {
        position: absolute;
        top: 15px;
        left: 15px;
        z-index: 100; /* Above app icon grids */
        background-color: var(--color-grey-10);
        border-radius: 40px;
        padding: 8px;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
        display: flex;
        align-items: center;
        justify-content: center;
    }

    .report-issue-button {
        margin: 5px;
    }

    /* Adjust position on mobile */
    @media (max-width: 600px) {
        .report-issue-button-wrapper {
            top: 10px;
            left: 10px;
        }
    }

</style>
