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
    import { getApiEndpoint, apiEndpoints } from '../../config/api';
    import InputWarning from '../common/InputWarning.svelte';
    import { SettingsInput, SettingsInfoBox, SettingsConsentToggle, SettingsSectionHeading, SettingsButton, SettingsGradientLink } from './elements';
    import { replaceState } from '$app/navigation';
    import { authStore } from '../../stores/authStore';
    import { notificationStore } from '../../stores/notificationStore';

    // Category toggles
    type CategoryKey = 'updates_and_announcements' | 'tips_and_tricks' | 'daily_inspirations';
    const CATEGORY_ORDER: CategoryKey[] = [
        'updates_and_announcements',
        'tips_and_tricks',
        'daily_inspirations',
    ];
    let categoriesLoaded = $state(false);
    let categoryPrefs = $state<Record<CategoryKey, boolean>>({
        updates_and_announcements: true,
        tips_and_tricks: true,
        daily_inspirations: false,
    });
    let savedPrefs = $state<Record<CategoryKey, boolean>>({
        updates_and_announcements: true,
        tips_and_tricks: true,
        daily_inspirations: false,
    });
    let isSaving = $state(false);
    let hasUnsavedChanges = $derived(
        CATEGORY_ORDER.some(key => categoryPrefs[key] !== savedPrefs[key])
    );
    
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
    let showEmailForm = $state(false);
    
    /**
     * Debounce helper function for email validation
     */
    function debounce<T extends (...args: unknown[]) => void>(
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
                // Refresh the category toggles — the user is now a confirmed
                // subscriber, so the UI should switch from disabled to active.
                void loadCategoryPreferences();
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
    
    /**
     * Load the authenticated user's current category preferences. Anonymous
     * visitors of the page skip this — their subscribe form still works but
     * the toggles are hidden (there's no subscriber row to attach them to).
     */
    async function loadCategoryPreferences() {
        if (!$authStore.isAuthenticated) {
            categoriesLoaded = true;
            return;
        }
        try {
            const resp = await fetch(getApiEndpoint(apiEndpoints.newsletter.categories), {
                method: 'GET',
                headers: { Accept: 'application/json' },
                credentials: 'include',
            });
            if (!resp.ok) {
                categoriesLoaded = true;
                return;
            }
            const data = await resp.json();
            if (data?.categories && typeof data.categories === 'object') {
                categoryPrefs = { ...categoryPrefs, ...data.categories };
                savedPrefs = { ...categoryPrefs };
            }
        } catch (err) {
            console.error('[SettingsNewsletter] Failed to load category prefs:', err);
        } finally {
            categoriesLoaded = true;
        }
    }

    async function saveCategories() {
        if (isSaving || !hasUnsavedChanges) return;
        isSaving = true;
        errorMessage = '';
        try {
            const resp = await fetch(getApiEndpoint(apiEndpoints.newsletter.categories), {
                method: 'PATCH',
                headers: {
                    'Content-Type': 'application/json',
                    Accept: 'application/json',
                },
                credentials: 'include',
                body: JSON.stringify({ categories: { ...categoryPrefs } }),
            });
            if (!resp.ok) {
                errorMessage = $text('settings.newsletter_categories.save_error');
                return;
            }
            const data = await resp.json();
            if (data?.categories) {
                categoryPrefs = { ...categoryPrefs, ...data.categories };
            }
            savedPrefs = { ...categoryPrefs };
            notificationStore.addNotification('success', $text('settings.newsletter_categories.saved'));
        } catch (err) {
            console.error('[SettingsNewsletter] Failed to save category prefs:', err);
            errorMessage = $text('settings.newsletter_categories.save_error');
        } finally {
            isSaving = false;
        }
    }

    $effect(() => {
        // Runs once on mount (and on re-auth) to hydrate the toggles.
        void loadCategoryPreferences();
    });

    // Handle deep link actions - format: #settings/newsletter/confirm/{token}, #settings/newsletter/unsubscribe/{token}, #settings/email/block/{email}
    // Clear the hash immediately on detection to prevent double-firing from
    // component remounts or $effect re-runs while the API call is in flight.
    $effect(() => {
        if (typeof window === 'undefined' || isProcessingAction) {
            return;
        }

        const hash = window.location.hash;

        const confirmMatch = hash.match(/^#settings\/newsletter\/confirm\/(.+)$/);
        if (confirmMatch) {
            const token = confirmMatch[1];
            isProcessingAction = true;
            replaceState(window.location.pathname + window.location.search, {});
            setTimeout(() => { handleConfirmSubscription(token); }, 500);
            return;
        }

        const unsubscribeMatch = hash.match(/^#settings\/newsletter\/unsubscribe\/(.+)$/);
        if (unsubscribeMatch) {
            const token = unsubscribeMatch[1];
            isProcessingAction = true;
            replaceState(window.location.pathname + window.location.search, {});
            setTimeout(() => { handleUnsubscribe(token); }, 500);
            return;
        }

        const blockMatch = hash.match(/^#settings\/email\/block\/(.+)$/);
        if (blockMatch) {
            const encodedEmail = blockMatch[1];
            const emailToBlock = decodeURIComponent(encodedEmail);
            isProcessingAction = true;
            replaceState(window.location.pathname + window.location.search, {});
            setTimeout(() => { handleBlockEmail(emailToBlock); }, 500);
            return;
        }
    });
</script>

<div class="newsletter-settings">
    <p class="page-description">{$text('settings.newsletter_description')}</p>

    {#if $authStore.isAuthenticated && categoriesLoaded}
        <!-- Authenticated: category toggles with batch save -->
        <div data-testid="newsletter-categories-section">
            <SettingsSectionHeading
                title={$text('settings.newsletter_categories.heading')}
                icon="mail"
            />
            <p class="section-description">{$text('settings.newsletter_categories.description')}</p>

            {#each CATEGORY_ORDER as key (key)}
                <div class="category-item" data-testid="newsletter-category-toggle-{key}">
                    <SettingsConsentToggle
                        bind:checked={categoryPrefs[key]}
                        consentText={$text(`settings.newsletter_categories.${key}.title`)}
                        ariaLabel={$text(`settings.newsletter_categories.${key}.title`)}
                    />
                    <p class="category-description">{$text(`settings.newsletter_categories.${key}.description`)}</p>
                </div>
            {/each}

            {#if hasUnsavedChanges}
                <SettingsButton
                    variant="primary"
                    fullWidth
                    loading={isSaving}
                    disabled={isSaving}
                    onClick={saveCategories}
                    dataTestid="newsletter-save-button"
                >
                    {$text('settings.newsletter_categories.save')}
                </SettingsButton>
            {/if}
        </div>

        <!-- Subscribe with a different email address -->
        {#if showEmailForm}
            <div class="newsletter-form">
                <SettingsInput
                    bind:value={email}
                    bind:inputRef={emailInput}
                    type="email"
                    placeholder={$text('settings.newsletter_email_placeholder')}
                    disabled={isSubmitting}
                    hasError={!!emailError}
                    ariaLabel={$text('settings.newsletter_email_placeholder')}
                    autocomplete="email"
                    onKeydown={handleKeyPress}
                />
                {#if showEmailWarning && emailError}
                    <InputWarning message={emailError} />
                {/if}
                <SettingsButton
                    variant="secondary"
                    fullWidth
                    loading={isSubmitting}
                    disabled={!isFormValid || isSubmitting}
                    onClick={handleSubscribe}
                    dataTestid="newsletter-subscribe-button"
                >
                    {$text('settings.newsletter_subscribe_button')}
                </SettingsButton>
            </div>
        {:else}
            <div data-testid="newsletter-change-email-button">
                <SettingsGradientLink onClick={() => showEmailForm = true}>
                    {$text('settings.newsletter_change_email')}
                </SettingsGradientLink>
            </div>
        {/if}

        {#if successMessage}
            <SettingsInfoBox type="success">{successMessage}</SettingsInfoBox>
        {/if}
        {#if errorMessage}
            <SettingsInfoBox type="error">{errorMessage}</SettingsInfoBox>
        {/if}
    {:else if !$authStore.isAuthenticated}
        <!-- Not authenticated: subscribe form -->
        <div class="newsletter-form">
            <SettingsInput
                bind:value={email}
                bind:inputRef={emailInput}
                type="email"
                placeholder={$text('settings.newsletter_email_placeholder')}
                disabled={isSubmitting}
                hasError={!!emailError}
                ariaLabel={$text('settings.newsletter_email_placeholder')}
                autocomplete="email"
                onKeydown={handleKeyPress}
            />
            {#if showEmailWarning && emailError}
                <InputWarning message={emailError} />
            {/if}
            <SettingsButton
                variant="primary"
                fullWidth
                loading={isSubmitting}
                disabled={!isFormValid || isSubmitting}
                onClick={handleSubscribe}
                dataTestid="newsletter-subscribe-button"
                ariaLabel={$text('settings.newsletter_subscribe_button')}
            >
                {$text('settings.newsletter_subscribe_button')}
            </SettingsButton>

            {#if isProcessingAction}
                <SettingsInfoBox type="info">{$text('settings.newsletter_processing')}</SettingsInfoBox>
            {/if}
            {#if successMessage}
                <SettingsInfoBox type="success">{successMessage}</SettingsInfoBox>
            {/if}
            {#if errorMessage}
                <SettingsInfoBox type="error">{errorMessage}</SettingsInfoBox>
            {/if}
        </div>
    {/if}

    <p class="info-text">{$text('settings.newsletter_info')}</p>
</div>

<style>
    .newsletter-settings {
        padding: 0 0.625rem;
    }

    .page-description {
        font-size: var(--font-size-p, 0.875rem);
        color: var(--color-grey-70);
        margin: 0 0 1rem 0;
        line-height: 1.4;
    }

    .section-description {
        font-size: var(--font-size-xxs);
        color: var(--color-grey-50);
        margin: 0 0 0.75rem 0;
        padding: 0 0.625rem;
        line-height: 1.4;
    }

    .category-item {
        margin-bottom: 0.25rem;
    }

    .category-description {
        font-size: var(--font-size-xxs);
        color: var(--color-grey-50);
        margin: -0.25rem 0 0.75rem 3.75rem;
        line-height: 1.4;
    }

    .newsletter-form {
        display: flex;
        flex-direction: column;
        gap: 0.75rem;
        margin-top: 1rem;
    }

    .info-text {
        font-size: var(--font-size-xxs);
        color: var(--color-grey-50);
        margin: 1.5rem 0 0 0;
        line-height: 1.4;
    }
</style>
