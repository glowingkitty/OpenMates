<script lang="ts">
    /**
     * PasswordAndTfaOtp.svelte - Component for password input with optional 2FA
     * Makes a single request to /login with all required data
     * Integrates Login2FA functionality for enhanced UX
     */
    import { createEventDispatcher, onMount, onDestroy } from 'svelte';
    import { fade } from 'svelte/transition';
    import { text } from '@repo/ui';
    import InputWarning from './common/InputWarning.svelte';
    import { getApiEndpoint, apiEndpoints } from '../config/api';
    import { tfaAppIcons } from '../config/tfa';
    import * as cryptoService from '../services/cryptoService';
    import { updateProfile } from '../stores/userProfile';
    import { getSessionId } from '../utils/sessionId';
    import { notificationStore } from '../stores/notificationStore';
    import AccountRecovery from './AccountRecovery.svelte';

    const dispatch = createEventDispatcher();
    
    // State for account recovery view
    let showAccountRecovery = $state(false);
    
    // Notify parent when account recovery mode changes (for inactivity timer management)
    $effect(() => {
        dispatch('accountRecoveryModeChanged', { active: showAccountRecovery });
    });

    // Props using Svelte 5 runes mode
    let { 
        email = '',
        isLoading = $bindable(false),
        errorMessage = null,
        tfaErrorMessage = null,
        stayLoggedIn = false,
        tfaAppName = null,
        previewMode = false,
        previewTfaAppName = 'Google Authenticator',
        tfa_required = false, // Default to false - only show 2FA input if explicitly required
        highlight = []
    }: {
        email?: string,
        isLoading?: boolean,
        errorMessage?: string | null,
        tfaErrorMessage?: string | null,
        stayLoggedIn?: boolean,
        tfaAppName?: string | null,
        previewMode?: boolean,
        previewTfaAppName?: string,
        tfa_required?: boolean,
        highlight?: (
            'check-2fa' |
            'app-name' |
            'input-area' |
            'login-btn' |
            'login-with-another-account' |
            'login-with-backup-code' |
            'login-with-recoverykey'
        )[]
    } = $props();

    // Form data using Svelte 5 runes
    let password = $state('');
    let tfaCode = $state('');
    let isBackupMode = $state(false);

    // Local state for tfa_required - initialized from prop value at component mount.
    //
    // The /lookup endpoint always returns tfa_enabled=true for anti-enumeration.
    // The login handler independently checks the actual 2FA status and skips
    // TFA validation for users without 2FA — so showing the OTP field always
    // is safe and prevents account-existence oracles.
    let tfaRequiredState = $state(tfa_required);

    // Input references using Svelte 5 runes
    let passwordInput: HTMLInputElement = $state();
    let tfaInput: HTMLInputElement = $state();

    // Add rate limiting state using Svelte 5 runes
    const RATE_LIMIT_DURATION = 120000; // 120 seconds in milliseconds
    let isRateLimited = $state(false);
    let rateLimitTimer: ReturnType<typeof setTimeout>;

    // Guard flag to prevent infinite auto-resubmit loops.
    // Set to true while an auto-resubmit is in-flight; reset after the response is processed.
    let isAutoResubmitting = $state(false);

    // TFA app display logic using Svelte 5 runes
    let currentAppIndex = $state(0);
    let animationInterval: number | null = null;
    let currentDisplayedApp = $state(previewMode ? previewTfaAppName : (tfaAppName || ''));
    const appNames = Object.keys(tfaAppIcons);

    // Get the icon class for the app name, or undefined if not found using Svelte 5 runes
    let tfaAppIconClass = $derived(currentDisplayedApp in tfaAppIcons ? tfaAppIcons[currentDisplayedApp] : undefined);

    // Reactive statements for backup mode using Svelte 5 runes
    let inputPlaceholder = $derived(isBackupMode ? $text('login.enter_backup_code') : $text('signup.enter_one_time_code'));
    let toggleButtonText = $derived(isBackupMode ? $text('login.login_with_tfa_app') : $text('login.login_with_backup_code'));
    let inputMaxLength = $derived(isBackupMode ? 14 : 6);

    // Validation using Svelte 5 runes - use local state variable
    let isPasswordValid = $derived(password.length > 0);
    let isTfaValid = $derived(!tfaRequiredState || (isBackupMode ? tfaCode.length === 14 : tfaCode.length === 6));
    let isFormValid = $derived(isPasswordValid && isTfaValid);

    // Helper function to generate opacity style using Svelte 5 runes
    type HighlightableId = typeof highlight[number];
    let getStyle = $derived((id: HighlightableId) => `opacity: ${highlight.length === 0 || highlight.includes(id) ? 1 : 0.5}`);

    // Rate limiting functions
    function setRateLimitTimer(duration: number) {
        if (rateLimitTimer) clearTimeout(rateLimitTimer);
        rateLimitTimer = setTimeout(() => {
            isRateLimited = false;
            localStorage.removeItem('passwordTfaRateLimit');
        }, duration);
    }

    // Update the animation logic to stop when a selected app is provided using Svelte 5 runes
    $effect(() => {
        if (tfaAppName) {
            currentDisplayedApp = tfaAppName;
            if (animationInterval) clearInterval(animationInterval);
        } else if (previewMode) {
            if (animationInterval) clearInterval(animationInterval);
            animationInterval = setInterval(() => {
                currentAppIndex = (currentAppIndex + 1) % appNames.length;
                currentDisplayedApp = appNames[currentAppIndex];
            }, 4000) as unknown as number;
        } else {
            currentDisplayedApp = tfaAppName || (previewMode ? previewTfaAppName : '');
        }
    });

    // Start animation in preview mode if no app name is selected
    onMount(() => {
        if (previewMode && !tfaAppName) {
            animationInterval = setInterval(() => {
                currentAppIndex = (currentAppIndex + 1) % appNames.length;
                currentDisplayedApp = appNames[currentAppIndex];
            }, 4000) as unknown as number;
        } else {
            currentDisplayedApp = tfaAppName || (previewMode ? previewTfaAppName : '');
        }
        // Focus password input on mount if not preview mode
        if (!previewMode && passwordInput) {
            passwordInput.focus();
        }
        
        // Check if we're still rate limited on mount
        const rateLimitTimestamp = localStorage.getItem('passwordTfaRateLimit');
        if (rateLimitTimestamp) {
            const timeLeft = parseInt(rateLimitTimestamp) + RATE_LIMIT_DURATION - Date.now();
            if (timeLeft > 0) {
                isRateLimited = true;
                setRateLimitTimer(timeLeft);
            } else {
                localStorage.removeItem('passwordTfaRateLimit');
            }
        }
    });

    onDestroy(() => {
        if (animationInterval) clearInterval(animationInterval);
        if (rateLimitTimer) clearTimeout(rateLimitTimer);
    });

    // Handle form submission - makes single request to /login
    async function handleSubmit() {
        if (!isPasswordValid || (tfaRequiredState && !isTfaValid) || isLoading) return;

        isLoading = true;
        errorMessage = null;
        tfaErrorMessage = null;

        try {
            // Generate hashed email and lookup hash
            const hashed_email = await cryptoService.hashEmail(email);
            
            // Generate lookup hash (password + salt)
            // According to security.md: lookup_hash = SHA256(login_secret + salt)
            // We need to use the user_email_salt as the salt for the lookup hash
            const userEmailSalt = cryptoService.getEmailSalt();
            
            if (!userEmailSalt) {
                console.error('Email salt not found in storage. Cannot generate lookup hash.');
                errorMessage = 'Authentication data not found. Please try logging in again.';
                return;
            }
            
            // Use the hashKey function from cryptoService which properly handles salt
            const lookup_hash = await cryptoService.hashKey(password, userEmailSalt);

            // Prepare request body
            const requestBody: any = {
                hashed_email,
                lookup_hash,
                stay_logged_in: stayLoggedIn  // Send stay logged in preference
            };

            // Add 2FA code if provided and required
            if (tfaRequiredState && tfaCode) {
                requestBody.tfa_code = tfaCode;
                requestBody.code_type = isBackupMode ? 'backup' : 'otp';
            }
            
            // Add email encryption key for zero-knowledge email decryption
            const email_encryption_key = cryptoService.getEmailEncryptionKeyForApi();
            if (email_encryption_key) {
                requestBody.email_encryption_key = email_encryption_key;
            }

            // Add sessionId for device fingerprint uniqueness (multi-browser support)
            requestBody.session_id = getSessionId();

            // Send single login request
            const response = await fetch(getApiEndpoint(apiEndpoints.auth.login), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Accept': 'application/json',
                    'Origin': window.location.origin
                },
                body: JSON.stringify(requestBody),
                credentials: 'include'
            });

            // Check for rate limiting first
            if (response.status === 429) {
                console.warn("Rate limit hit for password/TFA login");
                isRateLimited = true;
                localStorage.setItem('passwordTfaRateLimit', Date.now().toString());
                setRateLimitTimer(RATE_LIMIT_DURATION);
                return;
            }

            const data = await response.json();
            
            // Debug logging to understand response structure
            console.debug('[PasswordAndTfaOtp] Login response:', {
                ok: response.ok,
                status: response.status,
                success: data.success,
                tfa_required: data.tfa_required,
                message: data.message,
                hasUser: !!data.user
            });

            if (response.ok && data.success) {
                // Check if 2FA is required before treating as successful login
                // SECURITY: Backend returns success=True with tfa_required=True for non-existent accounts
                // to prevent email enumeration - we must check tfa_required first
                // Explicitly check for true (not just truthy) to handle edge cases
                if (data.tfa_required === true) {
                    console.debug('[PasswordAndTfaOtp] 2FA required detected');
                    // Check if 2FA is actually configured (tfa_enabled indicates encrypted_tfa_secret exists)
                    // tfa_app_name is optional and doesn't indicate if 2FA is configured
                    const isTfaConfigured = data.user?.tfa_enabled === true;
                    // Import isSignupPath helper for checking signup paths
                    const { isSignupPath } = await import('../stores/signupState');
                    const isInSignupFlow = isSignupPath(data.user?.last_opened) || false;

                    // AUTO-RESUBMIT: Users who skipped 2FA during signup get back an anti-enumeration
                    // response on first login attempt (success=true, tfa_required=true, tfa_enabled=false,
                    // last_opened=null, message="2FA required") because the backend can't distinguish them
                    // from non-existent accounts when no tfa_code is supplied.
                    //
                    // Fix: when 2FA is not configured and no code was submitted yet, automatically
                    // re-send the same credentials with tfa_code="" so the backend takes the
                    // Scenario 1 path (no 2FA) and returns a real login response.
                    //
                    // Security: if the account doesn't actually exist, the backend returns
                    // success=false with message="login.code_wrong" on the re-submit, which
                    // causes the OTP field to appear — preserving anti-enumeration protection.
                    //
                    // See docs/architecture/auth.md for the full anti-enumeration design.
                    if (!isTfaConfigured && !tfaCode && !isAutoResubmitting && data.message === '2FA required') {
                        console.debug('[PasswordAndTfaOtp] No 2FA configured and no code submitted — auto-resubmitting with empty tfa_code to bypass anti-enumeration gate');
                        isAutoResubmitting = true;
                        try {
                            // Re-use the already-computed hashed_email and lookup_hash from the outer scope.
                            const resubmitBody: any = {
                                hashed_email,
                                lookup_hash,
                                stay_logged_in: stayLoggedIn,
                                tfa_code: '',
                                code_type: 'otp'
                            };
                            const emailEncKey = cryptoService.getEmailEncryptionKeyForApi();
                            if (emailEncKey) resubmitBody.email_encryption_key = emailEncKey;
                            resubmitBody.session_id = getSessionId();

                            const resubmitResponse = await fetch(getApiEndpoint(apiEndpoints.auth.login), {
                                method: 'POST',
                                headers: {
                                    'Content-Type': 'application/json',
                                    'Accept': 'application/json',
                                    'Origin': window.location.origin
                                },
                                body: JSON.stringify(resubmitBody),
                                credentials: 'include'
                            });

                            if (resubmitResponse.status === 429) {
                                console.warn('[PasswordAndTfaOtp] Rate limit hit on auto-resubmit');
                                isRateLimited = true;
                                localStorage.setItem('passwordTfaRateLimit', Date.now().toString());
                                setRateLimitTimer(RATE_LIMIT_DURATION);
                                return;
                            }

                            const resubmitData = await resubmitResponse.json();
                            console.debug('[PasswordAndTfaOtp] Auto-resubmit response:', {
                                ok: resubmitResponse.ok,
                                status: resubmitResponse.status,
                                success: resubmitData.success,
                                tfa_required: resubmitData.tfa_required,
                                message: resubmitData.message
                            });

                            if (resubmitResponse.ok && resubmitData.success && !resubmitData.tfa_required) {
                                // Real user with no 2FA — backend took the Scenario 1 path and logged them in.
                                await handleSuccessfulLogin(resubmitData);
                                return;
                            }

                            // Account doesn't exist (anti-enumeration) or some other issue —
                            // fall through to show OTP field so UX is consistent with wrong-password behaviour.
                            console.debug('[PasswordAndTfaOtp] Auto-resubmit did not yield a clean login — showing OTP field (anti-enumeration)');
                        } finally {
                            isAutoResubmitting = false;
                        }
                        // Fall through: tfaRequiredState = true will be set below
                    }

                    // If account exists but 2FA is not configured (user hasn't finished signup),
                    // hide the 2FA field and redirect to signup to complete setup
                    if (data.user && !isTfaConfigured && isInSignupFlow) {
                        console.debug('[PasswordAndTfaOtp] Account exists but 2FA not configured - hiding 2FA field and redirecting to signup');
                        // Hide 2FA field for this case
                        tfaRequiredState = false;
                        
                        // Update profile with user data if available
                        if (data.user) {
                            // Log auto top-up fields from backend response - ERROR if missing
                            const hasAutoTopupFields = 'auto_topup_low_balance_enabled' in data.user;
                            if (!hasAutoTopupFields) {
                                console.error('[PasswordAndTfaOtp] ERROR: Auto top-up fields missing from backend response (2FA not configured path)!');
                                console.error('[PasswordAndTfaOtp] Received user object keys:', Object.keys(data.user));
                                console.error('[PasswordAndTfaOtp] Full user object:', data.user);
                            }
                            
                            // Save to IndexedDB first
                            const { userDB } = await import('../services/userDB');
                            await userDB.saveUserData(data.user);
                            
                            const userProfileData = {
                                username: data.user.username || '',
                                profile_image_url: data.user.profile_image_url || null,
                                credits: data.user.credits || 0,
                                is_admin: data.user.is_admin || false,
                                last_opened: data.user.last_opened || '',
                                tfa_app_name: data.user.tfa_app_name || null,
                                tfa_enabled: data.user.tfa_enabled || false,
                                consent_privacy_and_apps_default_settings: data.user.consent_privacy_and_apps_default_settings || false,
                                consent_mates_default_settings: data.user.consent_mates_default_settings || false,
                                language: data.user.language || 'en',
                                darkmode: data.user.darkmode || false,
                                // Low balance auto top-up fields
                                auto_topup_low_balance_enabled: data.user.auto_topup_low_balance_enabled ?? false,
                                auto_topup_low_balance_threshold: data.user.auto_topup_low_balance_threshold,
                                auto_topup_low_balance_amount: data.user.auto_topup_low_balance_amount,
                                auto_topup_low_balance_currency: data.user.auto_topup_low_balance_currency
                            };
                            updateProfile(userProfileData);
                        }
                        
                        // Dispatch event to redirect to signup
                        dispatch('loginSuccess', {
                            user: data.user,
                            inSignupFlow: true
                        });
                        return;
                    }
                    
                    // All other cases (including non-existent accounts) - show 2FA field
                    // This prevents email enumeration
                    tfaRequiredState = true;
                    // Show TFA-specific error message only for TFA field
                    // SECURITY: Don't show error when message is "2FA required" - this prevents email enumeration
                    // The backend returns "2FA required" for failed authentication to prevent revealing account existence
                    if (data.message === 'login.code_wrong') {
                        tfaErrorMessage = $text('login.code_wrong');
                        errorMessage = null;
                    } else if (data.message === '2FA required') {
                        // Don't show error message - just show the 2FA input field
                        // This is used for security (preventing email enumeration)
                        tfaErrorMessage = null;
                        errorMessage = null;
                    } else {
                        tfaErrorMessage = data.message || $text('login.code_wrong');
                        errorMessage = null;
                    }
                } else {
                    // Login successful (no 2FA required)
                    await handleSuccessfulLogin(data);
                }
            } else {
                if (data.tfa_required) {
                    // Check if 2FA is actually configured (tfa_enabled indicates encrypted_tfa_secret exists)
                    // tfa_app_name is optional and doesn't indicate if 2FA is configured
                    // CRITICAL: Only check tfa_enabled if user object is present
                    // When auth fails, backend omits user object for anti-enumeration
                    const hasUserData = data.user !== undefined && data.user !== null;
                    const isTfaConfigured = data.user?.tfa_enabled === true;
                    // Import isSignupPath helper for checking signup paths
                    const { isSignupPath } = await import('../stores/signupState');
                    const isInSignupFlow = isSignupPath(data.user?.last_opened) || false;
                    
                    // If 2FA is required but not actually configured (tfa_enabled is false) AND user is in signup flow,
                    // redirect to signup instead of asking for a 2FA code
                    // This handles the case where user hasn't completed 2FA setup during signup
                    // CRITICAL: Only do this if we have user data - otherwise we can't determine signup flow
                    if (hasUserData && !isTfaConfigured && isInSignupFlow) {
                        console.debug('[PasswordAndTfaOtp] 2FA required but not configured - redirecting to signup flow');
                        // Update profile with user data if available
                        if (data.user) {
                            // Log auto top-up fields from backend response - ERROR if missing
                            const hasAutoTopupFields = 'auto_topup_low_balance_enabled' in data.user;
                            if (!hasAutoTopupFields) {
                                console.error('[PasswordAndTfaOtp] ERROR: Auto top-up fields missing from backend response (2FA required path 2)!');
                                console.error('[PasswordAndTfaOtp] Received user object keys:', Object.keys(data.user));
                                console.error('[PasswordAndTfaOtp] Full user object:', data.user);
                            }
                            
                            // Save to IndexedDB first
                            const { userDB } = await import('../services/userDB');
                            await userDB.saveUserData(data.user);
                            
                            const userProfileData = {
                                username: data.user.username || '',
                                profile_image_url: data.user.profile_image_url || null,
                                credits: data.user.credits || 0,
                                is_admin: data.user.is_admin || false,
                                last_opened: data.user.last_opened || '',
                                tfa_app_name: data.user.tfa_app_name || null,
                                tfa_enabled: data.user.tfa_enabled || false,
                                consent_privacy_and_apps_default_settings: data.user.consent_privacy_and_apps_default_settings || false,
                                consent_mates_default_settings: data.user.consent_mates_default_settings || false,
                                language: data.user.language || 'en',
                                darkmode: data.user.darkmode || false,
                                // Low balance auto top-up fields
                                auto_topup_low_balance_enabled: data.user.auto_topup_low_balance_enabled ?? false,
                                auto_topup_low_balance_threshold: data.user.auto_topup_low_balance_threshold,
                                auto_topup_low_balance_amount: data.user.auto_topup_low_balance_amount,
                                auto_topup_low_balance_currency: data.user.auto_topup_low_balance_currency
                            };
                            updateProfile(userProfileData);
                        }
                        
                        // Dispatch event to redirect to signup
                        dispatch('loginSuccess', {
                            user: data.user,
                            inSignupFlow: true
                        });
                        return;
                    }
                    
                    // CRITICAL FIX: When we have no user data, we cannot determine if 2FA is configured
                    // Backend intentionally omits user data on failed auth to prevent email enumeration
                    // In this case, we should:
                    // 1. Keep the 2FA field visible if it was already shown (tfaRequiredState was true)
                    // 2. Show appropriate error message based on whether code was submitted
                    if (!hasUserData) {
                        // No user data = auth failed (wrong password/lookup_hash) or account doesn't exist
                        // Keep 2FA field visible and show password error since we can't determine 2FA status
                        console.debug('[PasswordAndTfaOtp] Auth failed, no user data (anti-enumeration). Keeping 2FA visible, showing password error.');
                        tfaRequiredState = true; // Keep 2FA field visible
                        // Show error on password field - the password/lookup_hash is likely wrong
                        errorMessage = $text('login.email_or_password_wrong');
                        tfaErrorMessage = null;
                    } else if (isTfaConfigured) {
                        // User data present and 2FA is configured
                        // Update local tfa_required state if server indicates it's needed AND 2FA is configured
                        tfaRequiredState = true;
                        // Show TFA-specific error message only for TFA field
                        // SECURITY: Don't show error when message is "2FA required" - this prevents email enumeration
                        // The backend returns "2FA required" for failed authentication to prevent revealing account existence
                        if (data.message === 'login.code_wrong') {
                            tfaErrorMessage = $text('login.code_wrong');
                            errorMessage = null;
                        } else if (data.message === '2FA required') {
                            // Don't show error message - just show the 2FA input field
                            // This is used for security (preventing email enumeration)
                            tfaErrorMessage = null;
                            errorMessage = null;
                        }
                    } else {
                        // User data present but 2FA is not configured (tfa_enabled === false)
                        // Don't show 2FA input
                        console.debug('[PasswordAndTfaOtp] 2FA required but not configured - not showing 2FA input');
                        tfaRequiredState = false;
                        tfaErrorMessage = null;
                    }
                } else {
                    // tfa_required is false - handle regular error messages
                    // Show password/email error for password field
                    if (data.message === 'login.email_or_password_wrong') {
                        errorMessage = $text('login.email_or_password_wrong');
                    } else {
                        errorMessage = data.message || $text('login.email_or_password_wrong');
                    }
                    tfaErrorMessage = null;
                }
            }
        } catch (error) {
            console.error('Login error:', error);
            errorMessage = 'An error occurred during login';
        } finally {
            isLoading = false;
        }
    }

    // Handle successful login
    //
    // ARCHITECTURE: This function is split into two phases:
    //   Phase 1 (critical): ws_token storage, master key decryption+storage — blocks login on failure
    //   Phase 2 (non-critical): profile update, notifications, pair credentials — runs after dispatch
    //
    // Regression fix for v1.0 encryption rebuild (commits 92a1e4ea6, 1ccfdf8cc):
    // Previously, the loginSuccess dispatch was at the BOTTOM of a single try-catch block
    // containing all post-login operations. If ANY non-critical operation (dynamic import,
    // IndexedDB save, notification) threw an uncaught exception, the dispatch never fired,
    // leaving the login dialog open despite a successful backend authentication.
    // The fix: dispatch loginSuccess immediately after critical crypto succeeds, then
    // run non-critical operations in a separate non-blocking block.
    async function handleSuccessfulLogin(data: any) {
        console.debug('[PasswordAndTfaOtp] [1/5] handleSuccessfulLogin called with data:', {
            hasUser: !!data.user,
            hasEncryptedKey: !!data.user?.encrypted_key,
            hasSalt: !!data.user?.salt,
            hasKeyIv: !!data.user?.key_iv,
            hasWsToken: !!data.ws_token
        });

        // CRITICAL: Store WebSocket token FIRST before any auth state changes
        // This must happen before calling setAuthenticatedState to prevent race conditions
        if (data.ws_token) {
            const { setWebSocketToken } = await import('../utils/cookies');
            setWebSocketToken(data.ws_token);
            console.debug('[PasswordAndTfaOtp] [2/5] WebSocket token stored from login response');
        } else {
            console.warn('[PasswordAndTfaOtp] No ws_token in login response - WebSocket connection may fail on Safari/iPad');
        }

        // CRITICAL: Validate required data for master key decryption
        // If any required field is missing, show error instead of silently failing
        if (!data.user) {
            console.error('[PasswordAndTfaOtp] CRITICAL: Login response missing user object!');
            errorMessage = $text('login.login_failed');
            return;
        }

        if (!data.user.encrypted_key) {
            console.error('[PasswordAndTfaOtp] CRITICAL: Login response missing encrypted_key! User object keys:', Object.keys(data.user));
            errorMessage = $text('login.login_failed');
            return;
        }

        if (!data.user.salt) {
            console.error('[PasswordAndTfaOtp] CRITICAL: Login response missing salt! User object keys:', Object.keys(data.user));
            errorMessage = $text('login.login_failed');
            return;
        }

        // ── Phase 1: Critical crypto operations (blocks login on failure) ──
        // Decrypt and save master key (Web Crypto API)
        try {
            // Decode salt from base64
            const saltString = atob(data.user.salt);
            const salt = new Uint8Array(saltString.length);
            for (let i = 0; i < saltString.length; i++) {
                salt[i] = saltString.charCodeAt(i);
            }

            // Derive wrapping key from password
            const wrappingKey = await cryptoService.deriveKeyFromPassword(password, salt);

            // Unwrap master key with IV (Web Crypto API)
            const keyIv = data.user.key_iv || ''; // IV for key unwrapping
            console.debug('[PasswordAndTfaOtp] [3/5] Decrypting master key...');
            const masterKey = await cryptoService.decryptKey(data.user.encrypted_key, keyIv, wrappingKey);

            if (!masterKey) {
                console.error('[PasswordAndTfaOtp] Master key decryption returned null/undefined');
                errorMessage = 'Failed to decrypt master key. Please try again.';
                return;
            }

            // Save extractable master key to IndexedDB
            // Extractable keys allow wrapping for recovery keys while still using Web Crypto API
            // Pass stayLoggedIn to ensure key is cleared on tab/browser close if user didn't check "Stay logged in"
            // CRITICAL: Wrap in try-catch to handle IndexedDB failures (e.g., blocked by other tabs)
            try {
                await cryptoService.saveKeyToSession(masterKey, stayLoggedIn);
                console.debug('[PasswordAndTfaOtp] [4/5] Master key unwrapped and saved (extractable).');
            } catch (saveError) {
                console.error('[PasswordAndTfaOtp] CRITICAL: Failed to save master key to IndexedDB!', saveError);
                errorMessage = 'Failed to save login data. Please try refreshing the page or using a different browser.';
                return;
            }
        } catch (e) {
            console.error('[PasswordAndTfaOtp] Error during key decryption:', e);
            errorMessage = 'Error during key decryption. Please try again.';
            return;
        }

        // ── Determine signup flow (needed for dispatch payload) ──
        let inSignupFlow = false;
        try {
            const { isSignupPath } = await import('../stores/signupState');
            inSignupFlow = isSignupPath(data.user?.last_opened) || false;
        } catch (importErr) {
            console.error('[PasswordAndTfaOtp] Failed to import signupState:', importErr);
            // Default to false — non-signup login is the common case
        }

        // ── Dispatch loginSuccess IMMEDIATELY ──
        // This is the critical state transition: the parent chain (Login.svelte → ActiveChat.svelte)
        // will call setAuthenticatedState() which closes the login dialog and shows the chat editor.
        // All operations after this point are non-critical and must not block the UI transition.
        console.debug('[PasswordAndTfaOtp] [5/5] Dispatching loginSuccess event (inSignupFlow=' + inSignupFlow + ')');

        // Capture email before dispatching — the parent (Login.svelte) clears its
        // email variable in the loginSuccess handler, which reactively updates this
        // prop to '' before Phase 2 async code below can use it.
        const emailForStorage = email;

        // Clear sensitive data before dispatching
        password = '';
        tfaCode = '';

        dispatch('loginSuccess', {
            user: data.user,
            inSignupFlow: inSignupFlow
        });

        // ── Phase 2: Non-critical post-login operations (non-blocking) ──
        // These operations run after the loginSuccess dispatch. Failures here do NOT
        // prevent the UI from transitioning to the logged-in state.
        try {
            // Store pair login credentials in sessionStorage
            try {
                // Note: encrypted_key and salt come from data.user, not from local scope
                sessionStorage.setItem('openmates_pair_encrypted_key', data.user.encrypted_key);
                sessionStorage.setItem('openmates_pair_salt', data.user.salt);
            } catch (pairStoreErr) {
                // Non-fatal — pair login will show an error to re-login if needed
                console.warn('[PasswordAndTfaOtp] Failed to store pair credentials:', pairStoreErr);
            }

            // Save email encrypted with master key for payment processing
            try {
                const emailStoredSuccessfully = await cryptoService.saveEmailEncryptedWithMasterKey(emailForStorage, false);
                if (!emailStoredSuccessfully) {
                    console.error('[PasswordAndTfaOtp] Failed to encrypt and store email with master key during login');
                }
            } catch (emailErr) {
                console.error('[PasswordAndTfaOtp] Error storing encrypted email:', emailErr);
            }

            console.debug('[PasswordAndTfaOtp] Login success, in signup flow:', inSignupFlow, {
                last_opened: data.user?.last_opened,
                tfa_enabled: data.user?.tfa_enabled
            });

            // If user completed signup but has no 2FA, show a reminder notification.
            if (!inSignupFlow && data.user?.tfa_enabled === false) {
                try {
                    notificationStore.addNotificationWithOptions('warning', {
                        title: $text('notifications.security_reminder.title'),
                        message: $text('notifications.security_reminder.message'),
                        actionLabel: $text('notifications.security_reminder.action'),
                        onAction: () => {
                            if (typeof window !== 'undefined') {
                                window.location.hash = '#settings/account/security';
                            }
                        },
                        duration: 0,
                        dismissible: true,
                    });
                } catch (notifError) {
                    console.warn('[PasswordAndTfaOtp] Failed to show 2FA reminder notification:', notifError);
                }
            }

            // If in signup flow, set signup state IMMEDIATELY
            // This prevents WebSocket from sending set_active_chat and overwriting last_opened
            if (inSignupFlow) {
                try {
                    const { isInSignupProcess, currentSignupStep, getStepFromPath } = await import('../stores/signupState');
                    const stepName = getStepFromPath(data.user.last_opened);
                    currentSignupStep.set(stepName);
                    isInSignupProcess.set(true);
                    console.debug('[PasswordAndTfaOtp] Signup flow detected - set isInSignupProcess=true, step:', stepName);
                } catch (signupErr) {
                    console.error('[PasswordAndTfaOtp] Failed to set signup state:', signupErr);
                }
            }

            // Update user profile with received data
            if (data.user) {
                // Save to IndexedDB - wrap in try-catch for IndexedDB failures
                try {
                    const { userDB } = await import('../services/userDB');
                    await userDB.saveUserData(data.user);
                } catch (userDbError) {
                    console.error('[PasswordAndTfaOtp] Failed to save user data to IndexedDB:', userDbError);
                }

                const userProfileData = {
                    username: data.user.username || '',
                    profile_image_url: data.user.profile_image_url || null,
                    credits: data.user.credits || 0,
                    is_admin: data.user.is_admin || false,
                    last_opened: data.user.last_opened || '',
                    tfa_app_name: data.user.tfa_app_name || null,
                    tfa_enabled: data.user.tfa_enabled || false,
                    consent_privacy_and_apps_default_settings: data.user.consent_privacy_and_apps_default_settings || false,
                    consent_mates_default_settings: data.user.consent_mates_default_settings || false,
                    language: data.user.language || 'en',
                    darkmode: data.user.darkmode || false,
                    auto_topup_low_balance_enabled: data.user.auto_topup_low_balance_enabled ?? false,
                    auto_topup_low_balance_threshold: data.user.auto_topup_low_balance_threshold,
                    auto_topup_low_balance_amount: data.user.auto_topup_low_balance_amount,
                    auto_topup_low_balance_currency: data.user.auto_topup_low_balance_currency
                };

                updateProfile(userProfileData);
                console.debug('[PasswordAndTfaOtp] User profile updated with login data');
            }
        } catch (postLoginErr) {
            // Non-critical: log but do not show error to user — login already succeeded
            console.error('[PasswordAndTfaOtp] Non-critical post-login error (login still succeeded):', postLoginErr);
        }
    }

    // Handle input for TFA code (supports both OTP and backup codes)
    function handleTfaInput(event: Event) {
        const input = event.target as HTMLInputElement;
        let value = input.value;

        if (isBackupMode) {
            // Allow letters, digits, hyphens. Convert to uppercase. Limit length.
            // Basic format XXXX-XXXX-XXXX
            value = value.toUpperCase().replace(/[^A-Z0-9-]/g, '');
            // Auto-add hyphens (simple approach)
            if (value.length === 4 || value.length === 9) {
                if (!value.endsWith('-')) {
                    value += '-';
                }
            }
            tfaCode = value.slice(0, 14); // Limit to XXXX-XXXX-XXXX format length
        } else {
            // Allow only digits and limit length for OTP
            tfaCode = value.replace(/\D/g, '').slice(0, 6);
        }
        
        input.value = tfaCode; // Ensure input reflects sanitized value

        // Dispatch activity events whenever input changes
        dispatch('tfaActivity');
        dispatch('userActivity');
    }

    // Function to toggle between OTP and Backup Code mode
    function toggleBackupMode() {
        isBackupMode = !isBackupMode;
        tfaCode = ''; // Clear input when switching modes
        errorMessage = null; // Clear error message
        tfaErrorMessage = null; // Clear TFA error message
        if (tfaInput) {
            tfaInput.focus(); // Re-focus input
        }
    }

    // Handle back to email
    function handleBackToEmail() {
        // Clear email encryption key and salt specifically (security: remove sensitive data when interrupting login)
        cryptoService.clearAllEmailData();
        dispatch('backToEmail');
    }

    // Handle switch to recovery key
    function handleSwitchToRecoveryKey() {
        dispatch('switchToRecoveryKey');
    }

    // Clear error message when user starts typing again and dispatch activity using Svelte 5 runes
    $effect(() => {
        if (tfaCode) {
            tfaErrorMessage = null;
            dispatch('userActivity');
        }
    });

    // Dispatch activity when password changes and clear password error using Svelte 5 runes
    $effect(() => {
        if (password) {
            errorMessage = null;
            dispatch('userActivity');
        }
    });
</script>

<div class="password-tfa-login" in:fade={{ duration: 300 }}>
    {#if showAccountRecovery}
        <!-- Account Recovery UI - replaces the login form -->
        <AccountRecovery
            {email}
            on:back={() => {
                showAccountRecovery = false;
            }}
            on:resetComplete={() => {
                // Account reset completed successfully
                // CRITICAL: Do NOT dispatch loginSuccess - user is NOT logged in!
                // The backend resets credentials but does NOT create a session.
                // User must login with their new credentials.
                console.log('[PasswordAndTfaOtp] Account reset completed, returning to login');
                
                // CRITICAL: Clear the old email salt from storage!
                // After recovery, the server has a NEW user_email_salt.
                // We must clear the old one so the /lookup endpoint returns the new salt.
                // Otherwise, login will fail with "Invalid lookup hash" because
                // the client would compute lookup_hash with the old salt.
                cryptoService.clearEmailSalt();
                cryptoService.clearEmailEncryptionKey();
                console.log('[PasswordAndTfaOtp] Cleared old email salt and encryption key after account reset');
                
                // Show success notification with instructions to login
                notificationStore.success(
                    $text('login.account_reset_complete_login_now'),
                    8000
                );
                
                // Dispatch backToEmail event to FULLY RESET the login interface
                // This clears the email and returns to the initial login state where
                // the user must either click "Login with passkey" or enter their email.
                // NOTE: We use 'backToEmail' (not 'back') because Login.svelte listens for this event.
                dispatch('backToEmail');
            }}
        />
    {:else if isRateLimited}
        <div class="rate-limit-message" in:fade={{ duration: 200 }}>
            {$text('signup.too_many_requests')}
        </div>
    {:else}
        <!-- Combined password and 2FA form -->
        <form onsubmit={(e) => { e.preventDefault(); handleSubmit(); }}>
        <!-- Hidden username field for accessibility -->
        <input
            type="email"
            name="username"
            value={email}
            autocomplete="username"
            style="position: absolute; left: -9999px; opacity: 0; pointer-events: none;"
            tabindex="-1"
            readonly
        />

        <!-- Show email address above password input -->
        <div class="email-display">
            <span class="color-grey-70">{email}</span>
        </div>

        <!-- Password input -->
        <div class="input-group">
            <div class="input-wrapper">
                <span class="clickable-icon icon_password"></span>
                <input
                    id="login-password-input"
                    bind:this={passwordInput}
                    type="password"
                    bind:value={password}
                    placeholder={$text('login.password_placeholder')}
                    required
                    autocomplete="current-password"
                    class:error={!!errorMessage}
                    oninput={() => dispatch('userActivity')}
                />
                {#if errorMessage}
                    <InputWarning
                        message={errorMessage}
                    />
                {/if}
            </div>
        </div>

        <!-- 2FA section - only visible if required -->
        {#if tfaRequiredState}
        <!-- Wrap check-2fa text for conditional hiding -->
        <div class="check-2fa-container" class:hidden={isBackupMode}>
            <p id="check-2fa" class="check-2fa-text" style={getStyle('check-2fa')}>
                {#if isBackupMode}
                    {@html $text('login.backup_code_is_single_use')}
                {:else if currentDisplayedApp}
                    <span class="app-name-inline">{@html $text('login.check_your_2fa_app').replace('{tfa_app}', '')}</span>
                    <span class="app-name-inline">
                        {#if tfaAppIconClass}
                            <span class="icon provider-{tfaAppIconClass} mini-icon {previewMode && !tfaAppName ? 'fade-animation' : ''}"></span>
                        {/if}
                        <span class="{previewMode && !tfaAppName ? 'fade-text' : ''}">{currentDisplayedApp}</span>
                    </span>
                {:else}
                    {@html $text('login.check_your_2fa_app').replace('{tfa_app}', $text('login.your_tfa_app'))}
                {/if}
            </p>

            <div id="input-group" style={getStyle('input-area')}>
                <div class="input-wrapper">
                    {#if isBackupMode}
                        <span class="clickable-icon icon_text"></span>
                        <input
                            id="login-otp-input"
                            bind:this={tfaInput}
                            type="text"
                            bind:value={tfaCode}
                            oninput={handleTfaInput}
                            placeholder={inputPlaceholder}
                            inputmode="text"
                            maxlength={inputMaxLength}
                            autocomplete="one-time-code"
                            class:error={!!errorMessage}
                            onkeypress={(e) => { if (e.key === 'Enter') handleSubmit(); }}
                        />
                    {:else}
                        <span class="clickable-icon icon_2fa"></span>
                        <input
                            id="login-otp-input"
                            bind:this={tfaInput}
                            type="text"
                            bind:value={tfaCode}
                            oninput={handleTfaInput}
                            placeholder={inputPlaceholder}
                            inputmode="numeric"
                            maxlength={inputMaxLength}
                            autocomplete="one-time-code"
                            class:error={!!errorMessage}
                            onkeypress={(e) => { if (e.key === 'Enter') handleSubmit(); }}
                        />
                    {/if}
                    {#if tfaErrorMessage}
                        <InputWarning
                            message={tfaErrorMessage}
                        />
                    {/if}
                </div>
            </div>
        </div>
        {/if}

        <button
            id="login-submit-button"
            type="submit"
            class="login-button"
            disabled={isLoading || !isFormValid}
        >
            {#if isLoading}
                <span class="loading-spinner"></span>
            {:else}
                {$text('login.login_button')}
            {/if}
        </button>
    </form>
    {/if}

    <!-- Login options container - always visible -->
    <div class="login-options-container">
        <!-- Back to email button -->
        <div id="login-with-another-account" style={getStyle('login-with-another-account')}>
            <button class="login-option-button" onclick={handleBackToEmail}>
                <span class="clickable-icon icon_user"></span>
                <mark>{$text('login.login_with_another_account')}</mark>
            </button>
        </div>

        <!-- Toggle Button - only if TFA is required and not in account recovery mode -->
        {#if tfaRequiredState && !showAccountRecovery}
        <div id="login-with-backup-code" style={getStyle('login-with-backup-code')}>
            <button class="login-option-button" onclick={toggleBackupMode} disabled={isLoading}>
                {#if isBackupMode}
                <span class="clickable-icon icon_2fa"></span>
                {:else}
                <span class="clickable-icon icon_text"></span>
                {/if}
                <mark>{toggleButtonText}</mark>
            </button>
        </div>
        {/if}

        <!-- Login with recovery key -->
        <div id="login-with-recoverykey" style={getStyle('login-with-recoverykey')}>
            <button class="login-option-button" onclick={handleSwitchToRecoveryKey}>
                <span class="clickable-icon icon_warning"></span>
                <mark>{$text('login.login_with_recovery_key')}</mark>
            </button>
        </div>
        
        <!-- Can't login to account? - only show when NOT in account recovery mode -->
        {#if !showAccountRecovery}
        <div class="cant-login-divider">
            <hr />
        </div>
        <div id="cant-login">
            <button class="login-option-button cant-login-button" data-testid="cant-login-button" onclick={() => showAccountRecovery = true}>
                <span class="clickable-icon icon_warning"></span>
                <mark>{$text('login.cant_login')}</mark>
            </button>
        </div>
        {/if}
    </div>
</div>

<style>
    .login-button {
        margin: 20px 0px 10px 0px;
    }
    .password-tfa-login {
        display: flex;
        flex-direction: column;
        width: 100%;
    }

    .email-display {
        text-align: center;
        margin-bottom: 10px;
    }

    .login-options-container {
        display: flex;
        flex-direction: column;
        align-self: center;
        width: fit-content;
    }

    .check-2fa-text {
        margin: 0 0 10px 0;
    }

    .app-name-inline {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        vertical-align: middle
    }

    .mini-icon {
        width: 24px;
        height: 24px;
        border-radius: 4px;
        flex-shrink: 0;
    }

    .login-option-button {
        display: flex;
        align-items: center;
        justify-content: center;
        padding: 0px 0px;
        background: none;
        border: none;
        cursor: pointer;
        filter: none;
    }

    .login-option-button .clickable-icon {
        margin-right: 8px;
    }

    .loading-spinner {
        border: 3px solid rgba(255, 255, 255, 0.3);
        border-radius: 50%;
        border-top: 3px solid white;
        width: 18px;
        height: 18px;
        animation: spin 1s linear infinite;
    }

    @keyframes spin {
        0% { transform: rotate(0deg); }
        100% { transform: rotate(360deg); }
    }

    .rate-limit-message {
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
    
    .cant-login-divider {
        width: 100%;
    }
    
    .cant-login-divider hr {
        border: none;
        border-top: 1px solid var(--color-grey-30);
    }
</style>
