<script lang="ts">
    import { fade, scale } from 'svelte/transition';
    import { text } from '@repo/ui';
    import AppIconGrid from './AppIconGrid.svelte';
    import InputWarning from './common/InputWarning.svelte';
    import { createEventDispatcher } from 'svelte';
    import { authStore, isCheckingAuth } from '../stores/authStore';
    import { currentSignupStep, isInSignupProcess } from '../stores/signupState';
    import { onMount, onDestroy } from 'svelte';
    import { MOBILE_BREAKPOINT } from '../styles/constants';
    import { tick } from 'svelte';
    import Signup from './signup/Signup.svelte';
    
    const dispatch = createEventDispatcher();

    // Form data
    let email = '';
    let password = '';
    let isLoading = false;

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

    // Add state for showing warning
    let showWarning = false;

    // Add email validation state
    let emailError = '';
    let showEmailWarning = false;
    let isEmailValidationPending = false;
    let loginFailedWarning = false;

    // Add rate limiting state
    const RATE_LIMIT_DURATION = 120000; // 120 seconds in milliseconds
    let isRateLimited = false;
    let rateLimitTimer: ReturnType<typeof setTimeout>;

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
    
    function switchToSignup() {
        currentView = 'signup';
    }
    
    async function switchToLogin() {
        currentView = 'login';
        await tick();
        // Only focus if not touch device
        if (emailInput && !isTouchDevice) {
            emailInput.focus();
        }
    }

    onMount(() => {
        (async () => {
            // Check if device is touch-enabled
            isTouchDevice = 'ontouchstart' in window || navigator.maxTouchPoints > 0;
            
            showLoadingUntil = Date.now() + 500;
            
            // Check if user is in signup process based on last_opened
            if ($authStore.isAuthenticated && $authStore.user?.last_opened?.startsWith('/signup/')) {
                // Extract step number from path
                const stepMatch = $authStore.user.last_opened.match(/\/signup\/step-(\d+)/);
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
        })();
        
        // Handle resize events
        const handleResize = () => {
            screenWidth = window.innerWidth;
            isMobile = screenWidth < MOBILE_BREAKPOINT;
        };
        
        window.addEventListener('resize', handleResize);
        return () => window.removeEventListener('resize', handleResize);
    });

    onDestroy(() => {
        if (rateLimitTimer) {
            clearTimeout(rateLimitTimer);
        }
    });

    async function handleSubmit() {
        isLoading = true;
        loginFailedWarning = false;

        try {
            // Use the unified authStore for login
            const result = await authStore.login(email, password);

            if (!result.success) {
                loginFailedWarning = true;
                if (result.message) {
                    emailError = result.message;
                    showEmailWarning = true;
                }
                return;
            }

            console.debug('Login successful');
            
            // Check if we need to switch to signup flow
            if (result.inSignupFlow) {
                console.debug('User is in signup process, switching to signup view');
                currentView = 'signup';
                // Wait for the next tick to ensure components are updated
                await tick();
            }
            
            dispatch('loginSuccess', { 
                user: $authStore.user,
                isMobile,
                inSignupFlow: result.inSignupFlow
            });
        } catch (error) {
            console.error('Login error details:', error);
            loginFailedWarning = true;
        } finally {
            isLoading = false;
        }
    }
    
    // Strengthen the reactive statement to switch views when in signup process
    $: {
        if ($authStore.isAuthenticated && $isInSignupProcess) {
            console.debug("Detected signup process, switching to signup view");
            currentView = 'signup';
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
                {#if currentView === 'login'}
                    <div class="content-area" in:fade={{ duration: 400 }}>
                        <h1><mark>{@html $text('login.login.text')}</mark></h1>
                        <h2>{@html $text('login.to_chat_to_your.text')}<br><mark>{@html $text('login.digital_team_mates.text')}</mark></h2>

                        <div class="form-container">
                            {#if isRateLimited}
                                <div class="rate-limit-message" in:fade={{ duration: 200 }}>
                                    {$text('signup.too_many_requests.text')}
                                </div>
                            {:else if $isCheckingAuth}
                                <div class="checking-auth" in:fade={{ duration: 200 }}>
                                    <p>{@html $text('login.loading.text')}</p>
                                </div>
                            {:else}
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
                            {/if}
                        </div>

                        <div class="bottom-positioned" class:visible={showForm && !$isCheckingAuth} hidden={!showForm || $isCheckingAuth}>
                            <span class="color-grey-60">{@html $text('login.not_signed_up_yet.text')}</span><br>
                            <button class="text-button" on:click={switchToSignup}>
                                {$text('login.click_here_to_create_a_new_account.text')}
                            </button>
                        </div>
                    </div>
                {:else}
                    <div in:fade={{ duration: 200 }}>
                        <Signup on:switchToLogin={switchToLogin} />
                    </div>
                {/if}
            </div>
        </div>

        {#if showDesktopGrids && gridsReady}
            <AppIconGrid iconGrid={rightIconGrid} shifted="columns" size={DESKTOP_ICON_SIZE}/>
        {/if}
    </div>
{/if}