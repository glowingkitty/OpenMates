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
    import { text } from '@repo/ui';
    import { locale } from 'svelte-i18n';
    import { getApiEndpoint, apiEndpoints } from '../../config/api';
    import InputWarning from '../common/InputWarning.svelte';
    
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
    
    // Get current language for newsletter subscription
    // Default to 'en' if locale is not available
    let currentLanguage = $derived($locale || 'en');
    
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
            emailError = $text('settings.newsletter_email_required.text');
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
            const response = await fetch(getApiEndpoint(apiEndpoints.newsletter.subscribe), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Accept': 'application/json',
                    'Origin': window.location.origin
                },
                body: JSON.stringify({
                    email: email.trim().toLowerCase(),
                    language: currentLanguage
                }),
                credentials: 'include'
            });
            
            const data = await response.json();
            
            if (response.ok && data.success) {
                // Show success message
                successMessage = data.message || $text('settings.newsletter_subscribe_success.text');
                // Clear email input
                email = '';
                emailError = '';
                showEmailWarning = false;
            } else {
                // Show error message from API or default error
                errorMessage = data.message || $text('settings.newsletter_subscribe_error.text');
            }
        } catch (error) {
            console.error('[SettingsNewsletter] Error subscribing to newsletter:', error);
            errorMessage = $text('settings.newsletter_subscribe_error.text');
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
</script>

<div class="newsletter-settings">
    <p>{$text('settings.newsletter_description.text')}</p>
    
    <!-- Email input form -->
    <div class="newsletter-form">
        <div class="input-group">
            <div class="input-wrapper">
                <span class="clickable-icon icon_mail"></span>
                <input
                    bind:this={emailInput}
                    type="email"
                    placeholder={$text('settings.newsletter_email_placeholder.text')}
                    bind:value={email}
                    onkeypress={handleKeyPress}
                    disabled={isSubmitting}
                    class:error={!!emailError}
                    aria-label={$text('settings.newsletter_email_placeholder.text')}
                    autocomplete="email"
                />
                {#if showEmailWarning && emailError}
                    <InputWarning
                        message={emailError}
                        target={emailInput}
                    />
                {/if}
            </div>
        </div>
        
        <div class="button-container">
            <button
                onclick={handleSubscribe}
                disabled={!isFormValid || isSubmitting}
                aria-label={$text('settings.newsletter_subscribe_button.text')}
            >
                {#if isSubmitting}
                    {$text('settings.newsletter_subscribing.text')}
                {:else}
                    {$text('settings.newsletter_subscribe_button.text')}
                {/if}
            </button>
        </div>
        
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
        <p class="info-text">{$text('settings.newsletter_info.text')}</p>
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
