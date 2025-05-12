<script lang="ts">
    import { fade, scale } from 'svelte/transition';
    import { text } from '@repo/ui';
    import AppIconGrid from './AppIconGrid.svelte';
    import InputWarning from './common/InputWarning.svelte';
    import { createEventDispatcher } from 'svelte';
    import { authStore, isCheckingAuth, needsDeviceVerification, login, checkAuth } from '../stores/authStore'; // Import login and checkAuth functions
    import { currentSignupStep, isInSignupProcess } from '../stores/signupState';
    import { onMount, onDestroy } from 'svelte';
    import { MOBILE_BREAKPOINT } from '../styles/constants';
    import { tick } from 'svelte';
    import Signup from './signup/Signup.svelte';
    import Login2FA from './Login2FA.svelte'; // Import Login2FA component
    import VerifyDevice2FA from './VerifyDevice2FA.svelte'; // Import VerifyDevice2FA component
    import { userProfile } from '../stores/userProfile';
    import { collectDeviceSignals } from '../utils/deviceSignals'; // Import the new utility
    
    const dispatch = createEventDispatcher();

    // Form data
    let email = '';
    let password = '';
    let isLoading = false;
    let showTfaView = false; // State to control 2FA view visibility
    let tfa_app_name: string | null = null; // State to store 2FA app name
    let tfaErrorMessage: string | null = null; // State for 2FA error messages
    let verifyDeviceErrorMessage: string | null = null; // State for device verification errors

    // Add state for mobile view
    let isMobile = false;
    let screenWidth = 0;
    let emailInput: HTMLInputElement; // Reference to the email input element

    // Add state for minimum loading time control
    let showLoadingUntil = 0;

    // Add state to control form visibility
    let showForm = false;
    
    // Add state to control grid visibility - initially hide all grids
    let gridsReady = false;

    // Add state for view management
    let currentView: 'login' | 'signup' = 'login';

    // Add touch detection
    let isTouchDevice = false;

    // Add email validation state
    let emailError = '';
    let showEmailWarning = false;
    let isEmailValidationPending = false;
    let loginFailedWarning = false;

    // Add rate limiting state
    const RATE_LIMIT_DURATION = 120000; // 120 seconds in milliseconds
    let isRateLimited = false;
    let rateLimitTimer: ReturnType<typeof setTimeout>;

    let isPolicyViolationLockout = false;
    let isAccountDeleted = false;

    // Add state for tracking account deletion during the current session
    let accountJustDeleted = false;

    // Derive device verification view state
    $: showVerifyDeviceView = $needsDeviceVerification;

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

    // Compute display state based on screen width
    $: showDesktopGrids = screenWidth > 600;
    $: showMobileGrid = screenWidth <= 600;

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

    // Clear login failed warning when either email or password changes
    $: {
        if (email || password) {
            loginFailedWarning = false;
        }
    }

    // Update reactive statements to include email validation
    $: {
        if (email) {
            isEmailValidationPending = true;
            debouncedCheckEmail(email);
        } else {
            emailError = '';
            showEmailWarning = false;
            isEmailValidationPending = false;
        }
    }

    // Initialize validation state when email is empty
    $: hasValidEmail = email && !emailError && !isEmailValidationPending;
    
    // Update helper for form validation to be false by default
    $: isFormValid = hasValidEmail && 
                     password && 
                     !loginFailedWarning;

    // Force validation check on empty email
    $: {
        if (!email) {
            debouncedCheckEmail('');
        }
    }
    
    // Improve switchToSignup function to reset the signup step and ensure state changes are coordinated
    async function switchToSignup() {
        // Clear login and 2FA state before switching view
        email = '';
        password = '';
        showTfaView = false;
        tfaErrorMessage = null;
        loginFailedWarning = false; // Also clear general login errors

        // Reset the signup step to 1 when starting a new signup process
        currentSignupStep.set(1);
        
        // Set the signup process flag first
        isInSignupProcess.set(true);
        
        // Wait for next tick to ensure the flag is processed
        await tick();
        
        // Now update the view
        currentView = 'signup';
        console.debug("Switched to signup view, isInSignupProcess:", $isInSignupProcess, "step:", $currentSignupStep);
    }
    
    async function switchToLogin() {
        // First change the view
        currentView = 'login';
        
        // Wait for the view change to take effect
        await tick();
        
        // Then reset the signup process flag
        isInSignupProcess.set(false);
        
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
                const stepMatch = $userProfile.last_opened.match(/\/signup\/step-(\d+)/);
                if (stepMatch && stepMatch[1]) {
                    const step = parseInt(stepMatch[1], 10);
                    currentSignupStep.set(step);
                    currentView = 'signup';
                    isInSignupProcess.set(true);
                }
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
        
        return () => {
            unsubscribe();
            window.removeEventListener('resize', handleResize);
            window.removeEventListener('account-deleted', handleAccountDeleted);
        };

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
    });

    // --- Inactivity Timer Functions (Login/2FA/Device Verify) ---
    function handleInactivityTimeout() {
        console.debug("Login/2FA/Device Verify inactivity timeout triggered.");
        email = '';
        password = '';
        if (showTfaView || showVerifyDeviceView) {
            // Call the function which handles clearing fields, hiding views,
            // and potentially focusing the email input.
            handleSwitchBackToLogin(); // Re-use this function
        }
        stopInactivityTimer(); // Stop the timer state
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
        // Check if email/password has content OR if 2FA/Device Verify view is active
        if (email || password || showTfaView || showVerifyDeviceView) {
            if (!isTimerActive) {
                console.debug("Login/2FA/Device Verify activity detected or view active, starting timer.");
            }
            resetInactivityTimer();
        } else {
            if (isTimerActive) {
                console.debug("Login/2FA/Device Verify fields empty and not in active view, stopping timer.");
                stopInactivityTimer();
            }
        }
    }
    // --- End Inactivity Timer Functions ---


    async function handleSubmit() {
        isLoading = true;
        loginFailedWarning = false;

        try {
            // Collect device signals before logging in
            const deviceSignals = await collectDeviceSignals();
    
            // Use the imported login function (first step, no TFA code), pass signals
            const result = await login(email, password, undefined, undefined, deviceSignals); // Use imported login function

            if (result.success && result.tfa_required) {
                // Password OK, 2FA required - switch to 2FA view
                console.debug("Switching to 2FA view");
                tfa_app_name = result.tfa_app_name || null;
                tfaErrorMessage = null; // Clear previous errors
                showTfaView = true;
            } else if (result.success && !result.tfa_required) {
                // Full login success (no 2FA or 2FA already handled - though shouldn't happen here)
                console.debug('Login successful (no 2FA required or already handled)');
                // Clear the form fields after successful login
                email = '';
                password = '';
                showTfaView = false; // Ensure 2FA view is hidden
                
                dispatch('loginSuccess', { 
                    user: $userProfile, 
                    isMobile,
                    inSignupFlow: result.inSignupFlow 
                });
            } else {
                // Login failed (invalid email/password)
                console.warn("Login failed:", result.message);
                loginFailedWarning = true; // Show general login failed warning
                showTfaView = false; // Ensure 2FA view is hidden
            }
        } catch (error) {
            console.error('Login handleSubmit error:', error);
            loginFailedWarning = true; // Show general login failed warning
            showTfaView = false; // Ensure 2FA view is hidden
        } finally {
            isLoading = false;
        }
    }

    // Handler to switch back from 2FA or Device Verify view to standard login
    function handleSwitchBackToLogin() {
        showTfaView = false;
        needsDeviceVerification.set(false); // Explicitly turn off device verification flag
        email = ''; // Clear email
        password = ''; // Clear password
        tfaErrorMessage = null; // Clear 2FA errors
        verifyDeviceErrorMessage = null; // Clear device verification errors
        loginFailedWarning = false; // Clear general login errors
        // Optionally focus email input after a tick if not touch
        tick().then(() => {
            if (emailInput && !isTouchDevice) {
                emailInput.focus();
            }
        });
    }
    
    // Handler for 2FA code submission from Login2FA component
    async function handleTfaSubmit(event: CustomEvent<{ authCode: string; codeType: 'otp' | 'backup' }>) { // Updated event detail type
        const { authCode, codeType } = event.detail; // Destructure code and type
        isLoading = true;
        tfaErrorMessage = null; // Clear previous error

        try {
            console.debug(`Submitting login with ${codeType} code...`);
            // Collect device signals again before submitting 2FA code
            // (In case something changed slightly, though less critical here than initial login)
            const deviceSignals = await collectDeviceSignals();
            // Call imported login function again, this time with the TFA code, type, and signals
            const result = await login(email, password, authCode, codeType, deviceSignals); // Use imported login function

            if (result.success && !result.tfa_required) {
                // Full login success after 2FA (OTP or Backup)
                console.debug(`Login successful after ${codeType} verification`);
                
                if (result.backup_code_used) {
                    // Backup code was used, show success message
                    console.debug(`Backup code used. Remaining: ${result.remaining_backup_codes}`);
                    // Backup code was used, complete login immediately (same as OTP)
                    email = ''; // Clear credentials
                    password = '';
                    showTfaView = false; // Hide 2FA view
                    stopInactivityTimer(); // Stop timer on successful login

                    dispatch('loginSuccess', {
                        user: $userProfile,
                        isMobile,
                        inSignupFlow: result.inSignupFlow // Assuming backup code usage might still be part of signup recovery?
                    });
                } else {
                    // OTP code was used, complete login immediately
                    email = ''; // Clear credentials
                    password = '';
                    showTfaView = false; // Hide 2FA view
                    stopInactivityTimer(); // Stop timer on successful login

                    dispatch('loginSuccess', {
                        user: $userProfile,
                        isMobile,
                        inSignupFlow: result.inSignupFlow 
                    });
                }
            } else if (!result.success && result.tfa_required) {
                // Invalid 2FA code (OTP or Backup)
                console.warn(`Invalid ${codeType} code submitted`);
                tfaErrorMessage = result.message || `Invalid ${codeType === 'backup' ? 'backup' : 'verification'} code`;
            } else {
                // Other unexpected error during 2FA step
                console.error(`Unexpected error during ${codeType} submission:`, result.message);
                tfaErrorMessage = result.message || "An unexpected error occurred.";
            }
        } catch (error) {
            console.error('handleTfaSubmit error:', error);
            tfaErrorMessage = `An error occurred during ${codeType} verification.`;
        } finally {
            isLoading = false;
        }
    }

    // Strengthen the reactive statement to switch views when in signup process
    // Also reset showTfaView and showVerifyDeviceView if user logs out or switches to signup
    // Reset views if switching away from login or logging out
    $: {
        // Only reset if view changes OR user is fully logged out (not just intermediate state)
        if (currentView !== 'login' || (!$authStore.isAuthenticated && !$authStore.isInitialized)) {
            tfaErrorMessage = null;
            verifyDeviceErrorMessage = null;
            // Check timer status when view changes or user logs out
            // This will stop the timer if fields are empty and not in an active view
            checkActivityAndManageTimer();
        }
    }

    $: {
        // Manage timer based on showTfaView or showVerifyDeviceView state changes
        if (showTfaView || showVerifyDeviceView) {
            console.debug("2FA or Device Verify view shown, ensuring timer is active.");
            checkActivityAndManageTimer(); // Start/reset timer when view appears
        } else {
             // When views are hidden (e.g., manual switch back, timeout, login success)
             // check if timer should stop (if email/password are also empty)
            checkActivityAndManageTimer();
        }
    }

    // Strengthen the reactive statement to handle signup process, logout, and device verification need
    $: {
        if ($authStore.isAuthenticated && $isInSignupProcess) {
            console.debug("Detected signup process, switching to signup view");
            currentView = 'signup';
            // needsDeviceVerification should be false already if authenticated, but double-check
            if ($needsDeviceVerification) needsDeviceVerification.set(false); // Keep this reset
            stopInactivityTimer(); // Stop timer when switching to signup
        } else if (!$authStore.isAuthenticated) {
            // If device verification is needed, stay in login view but show VerifyDevice2FA
            if ($needsDeviceVerification) {
                console.debug("Device verification needed, ensuring login view is active.");
                currentView = 'login';
                // showTfaView = false; // REMOVED: Don't reset based on device verification need alone
            } else if (currentView !== 'login' && !$isInSignupProcess) {
                // Force view to login when logged out, ONLY IF NOT needing device verification AND NOT in signup process
               currentView = 'login'; // This will trigger the reset in the first reactive block
            }
            stopInactivityTimer(); 

             // Check for account deletion (either from storage or from event)
            if (sessionStorage.getItem('account_deleted') === 'true' || accountJustDeleted) {
                console.debug("Account deleted, showing deletion message");
                isAccountDeleted = true;
                isPolicyViolationLockout = true;
                
                // Reset the flag after we've handled it, but keep in sessionStorage for reloads
                if (accountJustDeleted) {
                    accountJustDeleted = false;
                }
            }
        }
    }
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
                            {#if showTfaView}
                                <!-- Show 2FA Input Component -->
                                <div in:fade={{ duration: 200 }}>
                                    <Login2FA
                                        selectedAppName={tfa_app_name}
                                        on:submitTfa={handleTfaSubmit}
                                        on:switchToLogin={handleSwitchBackToLogin}
                                        bind:isLoading
                                        errorMessage={tfaErrorMessage}
                                        on:tfaActivity={checkActivityAndManageTimer}
                                    />
                                </div>
                            {:else if showVerifyDeviceView}
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
                            {:else if $isCheckingAuth}
                                <div class="checking-auth" in:fade={{ duration: 200 }}>
                                    <p>{@html $text('login.loading.text')}</p>
                                </div>
                            {:else}
                                <!-- Show Standard Login Form -->
                                <form 
                                    on:submit|preventDefault={handleSubmit} 
                                    class:visible={showForm}
                                    class:hidden={!showForm} 
                                >
                                    <div class="input-group">
                                        <div class="input-wrapper">
                                            <span class="clickable-icon icon_mail"></span>
                                            <input 
                                                type="email"
                                                bind:value={email}
                                                placeholder={$text('login.email_placeholder.text')}
                                                required
                                                autocomplete="email"
                                                bind:this={emailInput}
                                                class:error={!!emailError || loginFailedWarning}
                                                on:input={checkActivityAndManageTimer}
                                            />
                                            {#if showEmailWarning && emailError}
                                                <InputWarning
                                                    message={emailError} 
                                                    target={emailInput} 
                                                />
                                            {:else if loginFailedWarning}
                                                <InputWarning 
                                                    message={$text('login.login_failed.text')} 
                                                    target={emailInput} 
                                                />
                                            {/if}
                                        </div>
                                    </div>

                                    <div class="input-group">
                                        <div class="input-wrapper">
                                            <span class="clickable-icon icon_secret"></span>
                                            <input 
                                                type="password"
                                                bind:value={password}
                                                placeholder={$text('login.password_placeholder.text')}
                                                required
                                                autocomplete="current-password"
                                                on:input={checkActivityAndManageTimer}
                                            />
                                        </div>
                                    </div>

                                    <button 
                                        type="submit" 
                                        class="login-button" 
                                        disabled={isLoading || !isFormValid} 
                                    >
                                        {#if isLoading}
                                            <span class="loading-spinner"></span>
                                        {:else}
                                            {$text('login.login_button.text')}
                                        {/if}
                                    </button>
                                </form>
                            {/if} <!-- End standard login form / rate limit / loading block -->
                        </div> <!-- End form-container -->

                        <!-- Show signup link only when not verifying device -->
                        <div class="bottom-positioned" class:visible={showForm && !$isCheckingAuth && !showVerifyDeviceView} hidden={!showForm || $isCheckingAuth || showVerifyDeviceView}>
                            <span class="color-grey-60">{@html $text('login.not_signed_up_yet.text')}</span><br>
                            <button class="text-button" on:click={switchToSignup}>
                                {$text('login.click_here_to_create_a_new_account.text')}
                            </button>
                        </div>
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
</style>