<script lang="ts">
    import { fade, scale } from 'svelte/transition';
    import { text } from '@repo/ui';
    import AppIconGrid from './AppIconGrid.svelte';
    import { createEventDispatcher } from 'svelte';
    import { authStore, isCheckingAuth, needsDeviceVerification, login, checkAuth } from '../stores/authStore'; // Import login and checkAuth functions
    import { currentSignupStep, isInSignupProcess, STEP_BASICS, getStepFromPath, STEP_ONE_TIME_CODES } from '../stores/signupState';
    import { onMount, onDestroy } from 'svelte';
    import { MOBILE_BREAKPOINT } from '../styles/constants';
    import { tick } from 'svelte';
    import Signup from './signup/Signup.svelte';
    import VerifyDevice2FA from './VerifyDevice2FA.svelte'; // Import VerifyDevice2FA component
    import { userProfile } from '../stores/userProfile';
    import { sessionExpiredWarning } from '../stores/uiStateStore'; // Import sessionExpiredWarning store
    // Import new login method components
    import EmailLookup from './EmailLookup.svelte';
    import PasswordAndTfaOtp from './PasswordAndTfaOtp.svelte';
    import EnterBackupCode from './EnterBackupCode.svelte';
    import EnterRecoveryKey from './EnterRecoveryKey.svelte';
    // Import crypto service to clear email encryption data
    import * as cryptoService from '../services/cryptoService';
    
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
    let emailInput: HTMLInputElement; // Reference to the email input element

    // Add state for minimum loading time control using $state (Svelte 5 runes mode)
    let showLoadingUntil = $state(0);

    // Add state to control form visibility using $state (Svelte 5 runes mode)
    let showForm = $state(false);
    
    // Add state for server connection timeout using $state (Svelte 5 runes mode)
    const SERVER_TIMEOUT_MS = 3000; // 3 seconds timeout
    let serverConnectionError = $state(false);
    let connectionTimeoutId: ReturnType<typeof setTimeout> | null = null;
    
    // Add state to control grid visibility - initially hide all grids using $state (Svelte 5 runes mode)
    let gridsReady = $state(false);

    // currentView is now declared using $derived below

    // Add touch detection using $state (Svelte 5 runes mode)
    let isTouchDevice = $state(false);

    // Add email validation state using $state (Svelte 5 runes mode)
    let emailError = $state('');
    let showEmailWarning = $state(false);
    let isEmailValidationPending = $state(false);
    let loginFailedWarning = $state(false);

    // Add rate limiting state using $state (Svelte 5 runes mode)
    const RATE_LIMIT_DURATION = 120000; // 120 seconds in milliseconds
    let isRateLimited = $state(false);
    let rateLimitTimer: ReturnType<typeof setTimeout>;

    let isPolicyViolationLockout = $state(false);
    let isAccountDeleted = $state(false);

    // Add state for tracking account deletion during the current session using $state (Svelte 5 runes mode)
    let accountJustDeleted = $state(false);

    // Add timer for session expired warning auto-fade
    let sessionExpiredTimer: ReturnType<typeof setTimeout> | null = null;

    // Derive device verification view state using $derived (Svelte 5 runes mode)
    let showVerifyDeviceView = $derived($needsDeviceVerification);

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

    // Auto-fade session expired warning after 8 seconds using $effect (Svelte 5 runes mode)
    $effect(() => {
        if ($sessionExpiredWarning) {
            // Clear any existing timer
            if (sessionExpiredTimer) {
                clearTimeout(sessionExpiredTimer);
            }
            // Set new timer to clear the warning after 8 seconds
            sessionExpiredTimer = setTimeout(() => {
                sessionExpiredWarning.set(false);
                sessionExpiredTimer = null;
            }, 8000);
        } else {
            // Clear timer if warning is manually cleared
            if (sessionExpiredTimer) {
                clearTimeout(sessionExpiredTimer);
                sessionExpiredTimer = null;
            }
        }
    });

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

    // Clear login failed warning and session expired warning when either email or password changes using $effect (Svelte 5 runes mode)
    $effect(() => {
        if (email || password) {
            loginFailedWarning = false;
            $sessionExpiredWarning = false; // Clear session expired warning
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
        // Clear login and 2FA state before switching view
        email = '';
        password = '';
        showTfaView = false;
        tfaErrorMessage = null;
        loginFailedWarning = false; // Also clear general login errors

        // Reset the signup step to basics when starting a new signup process
        currentSignupStep.set(STEP_BASICS);
        
        // Set the signup process flag, which will reactively change the view
        isInSignupProcess.set(true);
        
        // Wait for next tick to ensure the flag is processed before logging
        await tick();
        console.debug("Switched to signup view, isInSignupProcess:", $isInSignupProcess, "step:", $currentSignupStep);
    }
    
    async function switchToLogin() {
        // Reset the signup process flag, which will reactively change the view
        isInSignupProcess.set(false);
        
        // Wait for the view change to take effect
        await tick();
        
        // Only focus if not touch device
        if (emailInput && !isTouchDevice) {
            emailInput.focus();
        }
    }

    // Add debug subscription to track isInSignupProcess changes
    onMount(() => {
        const unsubscribe = isInSignupProcess.subscribe(value => {
            console.debug(`[Login.svelte] isInSignupProcess changed to: ${value}`);
        });
        
        (async () => {
            // Check if device is touch-enabled
            isTouchDevice = 'ontouchstart' in window || navigator.maxTouchPoints > 0;
            
            showLoadingUntil = Date.now() + 500;
            
            // Check if user is in signup process based on last_opened
            if ($authStore.isAuthenticated && $userProfile.last_opened?.startsWith('/signup/')) {
                // Get step name from path using the function from signupState
                const stepName = getStepFromPath($userProfile.last_opened);
                currentSignupStep.set(stepName);
                isInSignupProcess.set(true); // This will set currentView reactively
            }
            
            // Set initial screen width
            screenWidth = window.innerWidth;
            // Set initial mobile state
            isMobile = screenWidth < MOBILE_BREAKPOINT;
            
            const remainingTime = showLoadingUntil - Date.now();
            if (remainingTime > 0) {
                await new Promise(resolve => setTimeout(resolve, remainingTime));
            }
            
            await tick();
            showForm = true; // Show form before removing loading state
            // Now that we've determined the screen size and loading is complete, show the appropriate grid
            gridsReady = true;
            
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
        // Clear session expired timer
        if (sessionExpiredTimer) {
            clearTimeout(sessionExpiredTimer);
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
    });

    // --- Inactivity Timer Functions (Login/2FA/Device Verify) ---
    function handleInactivityTimeout() {
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
        $sessionExpiredWarning = false;
        
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
        $sessionExpiredWarning = false; // Clear session expired warning
        // Reset to email step
        currentLoginStep = 'email';
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
    <div class="login-container" in:fade={{ duration: 300 }} out:fade={{ duration: 300 }}>
        {#if showDesktopGrids && gridsReady}
            <AppIconGrid iconGrid={leftIconGrid} shifted="columns" size={DESKTOP_ICON_SIZE}/>
        {/if}
        <div class="login-content">
            {#if showMobileGrid && gridsReady}
                <div class="mobile-grid-fixed">
                    <AppIconGrid iconGrid={mobileIconGrid} shifted="columns" shifting="10px" gridGap="2px" size={MOBILE_ICON_SIZE} />
                </div>
            {/if}
            
            <div class="login-box" in:scale={{ duration: 300, delay: 150 }}>
                <!-- Demo back button - only show when not in signup process and login interface was opened manually -->
                <!-- Uses the same navigation style as SignupNav.svelte -->
                {#if !$isInSignupProcess && !$authStore.isAuthenticated}
                    <div class="nav-area">
                        <button 
                            class="nav-button"
                            onclick={() => {
                                // Clear email encryption key and salt when interrupting login to go back to demo
                                // This ensures sensitive data is removed if user abandons login attempt
                                cryptoService.clearAllEmailData();
                                // Dispatch event to close login interface and show demo
                                window.dispatchEvent(new CustomEvent('closeLoginInterface'));
                            }}
                            aria-label={$text('login.demo.text')}
                        >
                            <div class="clickable-icon icon_back"></div>
                            {$text('login.demo.text')}
                        </button>
                    </div>
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
                                        <!-- Use EmailLookup component for email input -->
                                        <EmailLookup
                                            bind:email
                                            bind:isLoading
                                            bind:loginFailedWarning
                                            bind:stayLoggedIn
                                            on:lookupSuccess={(e) => {
                                                availableLoginMethods = e.detail.availableLoginMethods;
                                                preferredLoginMethod = e.detail.preferredLoginMethod;
                                                stayLoggedIn = e.detail.stayLoggedIn;
                                                tfaAppName = e.detail.tfa_app_name;
                                                // tfa_enabled indicates if 2FA is actually configured (encrypted_tfa_secret exists)
                                                // tfa_app_name is optional metadata and doesn't determine if 2FA is configured
                                                tfaEnabled = e.detail.tfa_enabled || false;
                                                // Use the helper function to safely set the login step
                                                setLoginStep(preferredLoginMethod);
                                            }}
                                            on:userActivity={resetInactivityTimer}
                                        />
                                    {:else}
                                        <!-- Show appropriate login method component based on currentLoginStep -->
                                        {#if currentLoginStep === 'password'}
                                            <!-- Use PasswordAndTfaOtp component -->
                                            <PasswordAndTfaOtp
                                                {email}
                                                bind:isLoading
                                                errorMessage={loginFailedWarning ? $text('login.login_failed.text') : null}
                                                {stayLoggedIn}
                                                {tfaAppName}
                                                tfa_required={tfaEnabled}
                                                on:loginSuccess={async (e) => {
                                                    console.log("Login success, in signup flow:", e.detail.inSignupFlow);
                                                    
                                                    // If user is in signup flow, set up the signup state
                                                    // Note: inSignupFlow can be true even if last_opened doesn't start with '/signup/'
                                                    // (e.g., if tfa_enabled is false but last_opened was overwritten to demo-welcome)
                                                    // The signup step should already be set in PasswordAndTfaOtp, but we respect it here
                                                    if (e.detail.inSignupFlow) {
                                                        // If last_opened indicates a signup step, use it; otherwise default to one_time_codes
                                                        // (the actual OTP setup step, not the app reminder step)
                                                        const stepName = e.detail.user?.last_opened?.startsWith('/signup/')
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
                                                on:switchToBackupCode={(e) => {
                                                    // Handle switch to backup code
                                                    currentLoginStep = 'backup_code';
                                                }}
                                                on:switchToRecoveryKey={(e) => {
                                                    // Handle switch to recovery key
                                                    currentLoginStep = 'recovery_key';
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
                                                errorMessage={loginFailedWarning ? $text('login.login_failed.text') : null}
                                                on:loginSuccess={async (e) => {
                                                    console.log("Login success (backup code), in signup flow:", e.detail.inSignupFlow);
                                                    
                                                    // If user is in signup flow, set up the signup state
                                                    // Note: inSignupFlow can be true even if last_opened doesn't start with '/signup/'
                                                    // (e.g., if tfa_enabled is false but last_opened was overwritten to demo-welcome)
                                                    // The signup step should already be set in PasswordAndTfaOtp, but we respect it here
                                                    if (e.detail.inSignupFlow) {
                                                        // If last_opened indicates a signup step, use it; otherwise default to one_time_codes
                                                        // (the actual OTP setup step, not the app reminder step)
                                                        const stepName = e.detail.user?.last_opened?.startsWith('/signup/')
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
                                                errorMessage={loginFailedWarning ? $text('login.login_failed.text') : null}
                                                on:loginSuccess={async (e) => {
                                                    console.log("Login success (recovery key), in signup flow:", e.detail.inSignupFlow);
                                                    
                                                    // If user is in signup flow, set up the signup state
                                                    // Note: inSignupFlow can be true even if last_opened doesn't start with '/signup/'
                                                    // (e.g., if tfa_enabled is false but last_opened was overwritten to demo-welcome)
                                                    // The signup step should already be set in PasswordAndTfaOtp, but we respect it here
                                                    if (e.detail.inSignupFlow) {
                                                        // If last_opened indicates a signup step, use it; otherwise default to one_time_codes
                                                        // (the actual OTP setup step, not the app reminder step)
                                                        const stepName = e.detail.user?.last_opened?.startsWith('/signup/')
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
                                        {:else if currentLoginStep === 'passkey'}
                                            <!-- TODO: Replace with Passkey component -->
                                            <div class="placeholder-component">
                                                <p>Passkey Component (to be implemented later)</p>
                                                <button type="button" onclick={() => currentLoginStep = 'email'}>Back to Email</button>
                                            </div>
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

                        <!-- Show signup link only when EmailLookup is visible -->
                        {#if showForm && !$isCheckingAuth && !showVerifyDeviceView && currentLoginStep === 'email'}
                            <div class="bottom-positioned">
                                <button class="text-button" onclick={switchToSignup}>
                                    <span class="clickable-icon icon_user"></span>
                                    {$text('login.create_account.text')}
                                </button>
                            </div>
                        {/if}
                    </div> <!-- End content-area for login view -->
                {:else} <!-- Handles currentView !== 'login' -->
                    <div in:fade={{ duration: 200 }}>
                        <Signup on:switchToLogin={switchToLogin} />
                        <!-- Removed stray </button> here -->
                    </div>
                {/if} <!-- This closes the main #if / :else if / :else block -->
            </div> <!-- End login-box -->
        </div>

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
    
    .bottom-positioned {
        margin-top: 40px;
        display: flex;
        justify-content: center;
        width: 100%;
    }
    
    .text-button {
        display: flex;
        align-items: center;
        justify-content: center;
    }
    
    .text-button .clickable-icon.icon_user {
        margin-right: 8px;
    }

    /* Navigation area for demo button - matches SignupNav.svelte styling */
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

</style>
