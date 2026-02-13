<!-- yaml_details
# YAML file explains structure of the UI.
The yaml structure is used as a base for auto generating & auto updating the documentations
and to help LLMs to answer questions regarding how the UI is used.
Instruction to AI: Only update the yaml structure if the UI structure is updated enough to justify
changes to the documentation (to keep the documentation up to date).
-->
<!-- yaml

-->
<script lang="ts">
    import { text, notificationStore } from '@repo/ui';
    import { locale } from 'svelte-i18n';
    import { getApiEndpoint, apiEndpoints } from '../../config/api';
    import InputWarning from '../common/InputWarning.svelte';
    import { replaceState } from '$app/navigation';
    
    // State for email input and form submission
    let email = $state('');
    let isSubmitting = $state(false);
    let successMessage = $state('');
    let errorMessage = $state('');
    
    // Email validation state
    let showEmailWarning = $state(false);
    let emailError = $state('');
    let isEmailValidationPending = $state(false);
    let emailInput = $state<HTMLInputElement>();
    
    // State for newsletter actions from email links
    let isProcessingAction = $state(false);
    
    /**
     * Debounce helper function for email validation
     */
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
    
    /**
     * Email validation check (same as in Basics.svelte)
     */
    const debouncedCheckEmail = debounce((email: string) => {
        if (!email) {
            emailError = '';
            showEmailWarning = false;
            isEmailValidationPending = false;
            return;
        }

        if (!email.includes('@')) {
            emailError = $text('signup.at_missing');
            showEmailWarning = true;
            isEmailValidationPending = false;
            return;
        }

        if (!email.match(/\.[a-z]{2,}$/i)) {
            emailError = $text('signup.domain_ending_missing');
            showEmailWarning = true;
            isEmailValidationPending = false;
            return;
        }

        emailError = '';
        showEmailWarning = false;
        isEmailValidationPending = false;
    }, 800);
    
    // Watch email changes and validate
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
    
    /**
     * Handles newsletter subscription form submission.
     * Sends email to backend which will send a confirmation email to the user.
     */
    async function handleSubscribe() {
        // Reset messages
        successMessage = '';
        errorMessage = '';
        
        // Validate email before submission
        if (!email || !email.trim()) {
            emailError = $text('settings.newsletter_email_required');
            showEmailWarning = true;
            if (emailInput) {
                emailInput.focus();
            }
            return;
        }
        
        // Check if email validation is pending or has errors
        if (isEmailValidationPending || emailError) {
            if (emailInput) {
                emailInput.focus();
            }
            return;
        }
        
        isSubmitting = true;
        
        try {
            // Get current language for newsletter subscription
            // Use the same logic as Basics.svelte: localStorage or browser default
            const currentLang = localStorage.getItem('preferredLanguage') || 
                              navigator.language.split('-')[0] || 
                              'en';
            
            // Get dark mode setting for newsletter subscription
            // Use the same logic as Basics.svelte: localStorage or system preference
            const prefersDarkMode = window.matchMedia && 
                                  window.matchMedia('(prefers-color-scheme: dark)').matches;
            const darkModeEnabled = localStorage.getItem('darkMode') === 'true' || prefersDarkMode;
            
            const response = await fetch(getApiEndpoint(apiEndpoints.newsletter.subscribe), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Accept': 'application/json',
                    'Origin': window.location.origin
                },
                body: JSON.stringify({
                    email: email.trim().toLowerCase(),
                    language: currentLang,
                    darkmode: darkModeEnabled
                }),
                credentials: 'include'
            });
            
            const data = await response.json();
            
            if (response.ok && data.success) {
                // Show success message
                successMessage = data.message || $text('settings.newsletter_subscribe_success');
                // Clear email input
                email = '';
                emailError = '';
                showEmailWarning = false;
            } else {
                // Show error message from API or default error
                errorMessage = data.message || $text('settings.newsletter_subscribe_error');
            }
        } catch (error) {
            console.error('[SettingsNewsletter] Error subscribing to newsletter:', error);
            errorMessage = $text('settings.newsletter_subscribe_error');
        } finally {
            isSubmitting = false;
        }
    }
    
    /**
     * Handles Enter key press in email input field.
     */
    function handleKeyPress(event: KeyboardEvent) {
        if (event.key === 'Enter' && !isSubmitting && !isEmailValidationPending && !emailError) {
            handleSubscribe();
        }
    }
    
    // Check if form is valid
    let isFormValid = $derived(
        email && 
        !emailError && 
        !isEmailValidationPending
    );
    
    /**
     * Handle newsletter confirmation from email link.
     * Similar to how SettingsInvoices handles refund deep links.
     */
    async function handleConfirmSubscription(token: string) {
        isProcessingAction = true;
        errorMessage = '';
        successMessage = '';
        
        try {
            const response = await fetch(getApiEndpoint(`${apiEndpoints.newsletter.confirm}/${token}`), {
                method: 'GET',
                headers: {
                    'Accept': 'application/json',
                    'Origin': window.location.origin
                },
                credentials: 'include'
            });
            
            const data = await response.json();
            
            if (response.ok && data.success) {
                successMessage = data.message || $text('settings.newsletter_confirm_success');
            } else {
                errorMessage = data.message || $text('settings.newsletter_confirm_error');
            }
        } catch (error) {
            console.error('[SettingsNewsletter] Error confirming newsletter subscription:', error);
            errorMessage = $text('settings.newsletter_confirm_error');
        } finally {
            isProcessingAction = false;
        }
    }
    
    /**
     * Handle newsletter unsubscribe from email link.
     */
    async function handleUnsubscribe(token: string) {
        isProcessingAction = true;
        errorMessage = '';
        successMessage = '';
        
        try {
            const response = await fetch(getApiEndpoint(`${apiEndpoints.newsletter.unsubscribe}/${token}`), {
                method: 'GET',
                headers: {
                    'Accept': 'application/json',
                    'Origin': window.location.origin
                },
                credentials: 'include'
            });
            
            const data = await response.json();
            
            if (response.ok && data.success) {
                successMessage = data.message || $text('settings.newsletter_unsubscribe_success');
            } else {
                errorMessage = data.message || $text('settings.newsletter_unsubscribe_error');
            }
        } catch (error) {
            console.error('[SettingsNewsletter] Error unsubscribing from newsletter:', error);
            errorMessage = $text('settings.newsletter_unsubscribe_error');
        } finally {
            isProcessingAction = false;
        }
    }
    
    /**
     * Handle email blocking from email link.
     */
    async function handleBlockEmail(emailToBlock: string) {
        isProcessingAction = true;
        errorMessage = '';
        successMessage = '';
        
        try {
            const response = await fetch(getApiEndpoint(apiEndpoints.emailBlock.blockEmail), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Accept': 'application/json',
                    'Origin': window.location.origin
                },
                body: JSON.stringify({
                    email: emailToBlock.toLowerCase().trim()
                }),
                credentials: 'include'
            });
            
            const data = await response.json();
            
            if (response.ok && data.success) {
                successMessage = data.message || $text('settings.newsletter_block_success');
            } else {
                errorMessage = data.message || $text('settings.newsletter_block_error');
            }
        } catch (error) {
            console.error('[SettingsNewsletter] Error blocking email:', error);
            errorMessage = $text('settings.newsletter_block_error');
        } finally {
            isProcessingAction = false;
        }
    }
    
    // Handle deep link actions - format: #settings/newsletter/confirm/{token}, #settings/newsletter/unsubscribe/{token}, #settings/email/block/{email}
    // Similar to how SettingsInvoices handles refund deep links
    // Process immediately when component is ready (no need to wait for data like invoices)
    $effect(() => {
        if (typeof window === 'undefined' || isProcessingAction) {
            return;
        }
        
        const hash = window.location.hash;
        
        // Check for newsletter confirmation deep link (e.g., #settings/newsletter/confirm/{token})
        const confirmMatch = hash.match(/^#settings\/newsletter\/confirm\/(.+)$/);
        if (confirmMatch) {
            const token = confirmMatch[1];
            console.debug(`[SettingsNewsletter] Deep link confirmation detected for token: ${token.substring(0, 10)}...`);
            
            // Mark as processing to prevent re-processing
            isProcessingAction = true;
            
            // Small delay to ensure UI is ready
            setTimeout(() => {
                handleConfirmSubscription(token).finally(() => {
                    // Clear the deep link from URL after processing
                    replaceState(window.location.pathname + window.location.search, {});
                });
            }, 500);
            return;
        }
        
        // Check for newsletter unsubscribe deep link (e.g., #settings/newsletter/unsubscribe/{token})
        const unsubscribeMatch = hash.match(/^#settings\/newsletter\/unsubscribe\/(.+)$/);
        if (unsubscribeMatch) {
            const token = unsubscribeMatch[1];
            console.debug(`[SettingsNewsletter] Deep link unsubscribe detected for token: ${token.substring(0, 10)}...`);
            
            // Mark as processing to prevent re-processing
            isProcessingAction = true;
            
            // Small delay to ensure UI is ready
            setTimeout(() => {
                handleUnsubscribe(token).finally(() => {
                    // Clear the deep link from URL after processing
                    replaceState(window.location.pathname + window.location.search, {});
                });
            }, 500);
            return;
        }
        
        // Check for email block deep link (e.g., #settings/email/block/{email})
        const blockMatch = hash.match(/^#settings\/email\/block\/(.+)$/);
        if (blockMatch) {
            const encodedEmail = blockMatch[1];
            const emailToBlock = decodeURIComponent(encodedEmail);
            console.debug(`[SettingsNewsletter] Deep link email block detected for: ${emailToBlock.substring(0, 10)}...`);
            
            // Mark as processing to prevent re-processing
            isProcessingAction = true;
            
            // Small delay to ensure UI is ready
            setTimeout(() => {
                handleBlockEmail(emailToBlock).finally(() => {
                    // Clear the deep link from URL after processing
                    replaceState(window.location.pathname + window.location.search, {});
                });
            }, 500);
            return;
        }
    });
</script>

<div class="newsletter-settings">
    <p>{$text('settings.newsletter_description')}</p>
    
    <!-- Email input form -->
    <div class="newsletter-form">
        <div class="input-group">
            <div class="input-wrapper">
                <span class="clickable-icon icon_mail"></span>
                <input
                    bind:this={emailInput}
                    type="email"
                    placeholder={$text('settings.newsletter_email_placeholder')}
                    bind:value={email}
                    onkeypress={handleKeyPress}
                    disabled={isSubmitting}
                    class:error={!!emailError}
                    aria-label={$text('settings.newsletter_email_placeholder')}
                    autocomplete="email"
                />
                {#if showEmailWarning && emailError}
                    <InputWarning
                        message={emailError}
                    />
                {/if}
            </div>
        </div>
        
        <div class="button-container">
            <button
                onclick={handleSubscribe}
                disabled={!isFormValid || isSubmitting}
                aria-label={$text('settings.newsletter_subscribe_button')}
            >
                {#if isSubmitting}
                    {$text('settings.newsletter_subscribing')}
                {:else}
                    {$text('settings.newsletter_subscribe_button')}
                {/if}
            </button>
        </div>
        
        <!-- Processing action message (from email links) -->
        {#if isProcessingAction}
            <div class="message processing-message" role="alert">
                {$text('settings.newsletter_processing')}
            </div>
        {/if}
        
        <!-- Success message -->
        {#if successMessage}
            <div class="message success-message" role="alert">
                {successMessage}
            </div>
        {/if}
        
        <!-- Error message -->
        {#if errorMessage}
            <div class="message error-message" role="alert">
                {errorMessage}
            </div>
        {/if}
    </div>
    
    <!-- Additional information -->
    <div class="newsletter-info">
        <p class="info-text">{$text('settings.newsletter_info')}</p>
    </div>
</div>

<style>
    .newsletter-settings {
        margin: 20px;
    }
    
    
    .newsletter-form {
        display: flex;
        flex-direction: column;
        gap: 12px;
    }
    
    .input-group {
        margin-bottom: 1rem;
    }
    
    .input-wrapper {
        position: relative;
        display: flex;
        align-items: center;
        width: 100%;
        max-width: 350px;
        margin: 0 auto;
    }
    
    .input-wrapper .clickable-icon {
        position: absolute;
        left: 1rem;
        color: var(--color-grey-60);
        z-index: 1;
    }
    
    .input-wrapper input.error {
        border-color: var(--color-error, #e74c3c);
    }
    
    .button-container button {
        width: 100%;
        margin-bottom: 10px;
    }
    .message {
        padding: 10px 12px;
        border-radius: 8px;
        font-size: 14px;
        line-height: 1.4;
    }
    
    .success-message {
        background-color: var(--color-success-light, #e8f5e9);
        color: var(--color-success-dark, #2e7d32);
        border: 1px solid var(--color-success, #4caf50);
    }
    
    .error-message {
        background-color: var(--color-error-light, #ffebee);
        color: var(--color-error-dark, #c62828);
        border: 1px solid var(--color-error, #f44336);
    }
    
    .processing-message {
        background-color: var(--color-info-light, #e3f2fd);
        color: var(--color-info-dark, #1565c0);
        border: 1px solid var(--color-info, #2196f3);
    }
    
    .newsletter-info {
        margin-top: 8px;
    }
    
    .info-text {
        font-size: 12px;
        color: var(--color-grey-50);
        margin: 0;
        line-height: 1.4;
    }
</style>
