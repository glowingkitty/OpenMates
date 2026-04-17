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
    import { SettingsInput, SettingsInfoBox, SettingsItem } from './elements';
    import { replaceState } from '$app/navigation';
    import { authStore } from '../../stores/authStore';

    // Category toggles
    type CategoryKey = 'updates_and_announcements' | 'tips_and_tricks' | 'daily_inspirations';
    const CATEGORY_ORDER: CategoryKey[] = [
        'updates_and_announcements',
        'tips_and_tricks',
        'daily_inspirations',
    ];
    let categoriesLoaded = $state(false);
    let isSubscribedToNewsletter = $state(false);
    let categoryPrefs = $state<Record<CategoryKey, boolean>>({
        updates_and_announcements: true,
        tips_and_tricks: true,
        daily_inspirations: false,
    });
    let savingCategory = $state<CategoryKey | null>(null);
    
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
                // Reset UI — they're no longer a subscriber, hide toggles.
                isSubscribedToNewsletter = false;
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
            isSubscribedToNewsletter = false;
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
            isSubscribedToNewsletter = Boolean(data?.subscribed);
            if (data?.categories && typeof data.categories === 'object') {
                categoryPrefs = { ...categoryPrefs, ...data.categories };
            }
        } catch (err) {
            console.error('[SettingsNewsletter] Failed to load category prefs:', err);
        } finally {
            categoriesLoaded = true;
        }
    }

    async function toggleCategory(key: CategoryKey) {
        if (!isSubscribedToNewsletter || savingCategory) return;
        const next = !categoryPrefs[key];
        savingCategory = key;
        // Optimistic update so the toggle feels instant.
        const prev = categoryPrefs[key];
        categoryPrefs = { ...categoryPrefs, [key]: next };
        try {
            const resp = await fetch(getApiEndpoint(apiEndpoints.newsletter.categories), {
                method: 'PATCH',
                headers: {
                    'Content-Type': 'application/json',
                    Accept: 'application/json',
                },
                credentials: 'include',
                body: JSON.stringify({ categories: { [key]: next } }),
            });
            if (!resp.ok) {
                categoryPrefs = { ...categoryPrefs, [key]: prev };
                errorMessage = $text('settings.newsletter_categories.save_error');
                return;
            }
            const data = await resp.json();
            if (data?.categories) {
                categoryPrefs = { ...categoryPrefs, ...data.categories };
            }
        } catch (err) {
            categoryPrefs = { ...categoryPrefs, [key]: prev };
            console.error('[SettingsNewsletter] Failed to save category pref:', err);
            errorMessage = $text('settings.newsletter_categories.save_error');
        } finally {
            savingCategory = null;
        }
    }

    $effect(() => {
        // Runs once on mount (and on re-auth) to hydrate the toggles.
        void loadCategoryPreferences();
    });

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

    {#if $authStore.isAuthenticated && categoriesLoaded && isSubscribedToNewsletter}
        <!-- Authenticated + subscribed: show category toggles, no subscribe form -->
        <div class="newsletter-categories" data-testid="newsletter-categories-section">
            <h3 class="categories-heading">
                {$text('settings.newsletter_categories.heading')}
            </h3>
            <p class="categories-description">
                {$text('settings.newsletter_categories.description')}
            </p>
            {#each CATEGORY_ORDER as key (key)}
                <SettingsItem
                    type="submenu"
                    icon={key === 'daily_inspirations' ? 'subsetting_icon sparkles' : key === 'tips_and_tricks' ? 'subsetting_icon info' : 'subsetting_icon mail'}
                    title={$text(`settings.newsletter_categories.${key}.title`)}
                    subtitleTop={$text(`settings.newsletter_categories.${key}.description`)}
                    hasToggle={true}
                    checked={categoryPrefs[key]}
                    disabled={savingCategory !== null && savingCategory !== key}
                    onClick={() => toggleCategory(key)}
                    data-testid={`newsletter-category-toggle-${key}`}
                />
            {/each}
        </div>

        <!-- Success/error messages from deep link actions -->
        {#if successMessage}
            <SettingsInfoBox type="success">
                {successMessage}
            </SettingsInfoBox>
        {/if}
        {#if errorMessage}
            <SettingsInfoBox type="error">
                {errorMessage}
            </SettingsInfoBox>
        {/if}
    {:else}
        <!-- Not subscribed (or not authenticated): show subscribe form -->
        <div class="newsletter-form">
            <div class="input-group">
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
                    <InputWarning
                        message={emailError}
                    />
                {/if}
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
                <SettingsInfoBox type="info">
                    {$text('settings.newsletter_processing')}
                </SettingsInfoBox>
            {/if}

            <!-- Success message -->
            {#if successMessage}
                <SettingsInfoBox type="success">
                    {successMessage}
                </SettingsInfoBox>
            {/if}

            <!-- Error message -->
            {#if errorMessage}
                <SettingsInfoBox type="error">
                    {errorMessage}
                </SettingsInfoBox>
            {/if}
        </div>
    {/if}

    <!-- Additional information -->
    <div class="newsletter-info">
        <p class="info-text">{$text('settings.newsletter_info')}</p>
    </div>
</div>

<style>
    .newsletter-settings {
        margin: var(--spacing-10);
    }
    
    
    .newsletter-form {
        display: flex;
        flex-direction: column;
        gap: var(--spacing-6);
    }
    
    .input-group {
        margin-bottom: 1rem;
    }

    .button-container button {
        width: 100%;
        margin-bottom: var(--spacing-5);
    }
    
    .newsletter-categories {
        margin-top: var(--spacing-8);
        padding-top: var(--spacing-6);
        border-top: 1px solid var(--color-grey-80, #e0e0e0);
    }

    .categories-heading {
        font-size: var(--font-size-sm);
        font-weight: 600;
        margin: 0 0 var(--spacing-2) 0;
    }

    .categories-description {
        font-size: var(--font-size-xxs);
        color: var(--color-grey-50);
        margin: 0 0 var(--spacing-4) 0;
        line-height: 1.4;
    }

    .newsletter-info {
        margin-top: var(--spacing-4);
    }
    
    .info-text {
        font-size: var(--font-size-xxs);
        color: var(--color-grey-50);
        margin: 0;
        line-height: 1.4;
    }
</style>
