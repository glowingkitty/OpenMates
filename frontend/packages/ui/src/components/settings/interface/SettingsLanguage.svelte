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
    import { text, SUPPORTED_LANGUAGES } from '@repo/ui';
    import SettingsItem from '../../SettingsItem.svelte';
    import { locale, locales } from 'svelte-i18n';
    import { browser } from '$app/environment';
    import { waitLocale } from 'svelte-i18n';
    import { loadMetaTags, getMetaTags } from '../../../config/meta';
    import { createEventDispatcher, onMount } from 'svelte';
    import { settingsNavigationStore, updateBreadcrumbsWithLanguage } from '../../../stores/settingsNavigationStore';
    import { getApiUrl, apiEndpoints } from '../../../config/api'; // Import API config

    const dispatch = createEventDispatcher();

    // Type definition for supported languages
    type Language = {
        code: string;
        name: string;
        shortCode: string; // Two letter code for display
    };

    // Import supported languages from single source of truth
    const baseLanguages: Language[] = SUPPORTED_LANGUAGES;

    // Current language state
    let currentLanguage = $state('en');
    
    // Browser's default language (set only once)
    let browserLanguage = $state('en');

    // Use languages in the order defined in languages.json (single source of truth)
    // Order: English first, German second, then by global speaker count
    // No need to re-sort - respect the intended order from languages.json
    let sortedLanguages: Language[] = $state(baseLanguages);

    // Find the current language object using Svelte 5 runes
    let currentLanguageObj = $derived(baseLanguages.find(lang => lang.code === currentLanguage) || baseLanguages[0]);

    // Initialize locale from browser language
    // Note: We preserve the order from languages.json instead of re-sorting
    const initializeLocale = () => {
        if (browser) {
            // Get saved locale
            const savedLocale = localStorage.getItem('preferredLanguage');
            
            // Get browser language
            browserLanguage = navigator.language.split('-')[0];
            if (!baseLanguages.some(lang => lang.code === browserLanguage)) {
                browserLanguage = 'en'; // Default to English if browser language not supported
            }
            
            // Set current language
            if (savedLocale && baseLanguages.some(lang => lang.code === savedLocale)) {
                currentLanguage = savedLocale;
            } else {
                currentLanguage = browserLanguage;
            }
            
            // Use languages in their original order from languages.json
            // This preserves: English first, German second, then by speaker count
            sortedLanguages = baseLanguages;
        }
    };

    // Enhanced language change handling
    const handleLanguageChange = async (newLocale: string) => {
        if (!browser) return;
        
        // Skip if already selected
        if (newLocale === currentLanguage) return;
        
        try {
            // Set new locale first
            locale.set(newLocale);
            
            // Update current language after locale is set
            currentLanguage = newLocale;

            // Store preference in localStorage
            localStorage.setItem('preferredLanguage', newLocale);
            
            // Store preference in cookies for SSR (expires in 1 year)
            document.cookie = `preferredLanguage=${newLocale}; path=/; max-age=31536000; SameSite=Lax`;
            
            // Wait for translations to load
            await waitLocale();

            // Update HTML lang attribute
            document.documentElement.setAttribute('lang', newLocale);

            try {
                // Attempt to reload meta tags with new language (with proper error handling)
                await loadMetaTags();
            } catch (metaError) {
                console.error('Error loading meta tags:', metaError);
                // Continue execution even if meta tags fail to load
            }

            // Get updated meta tags for the current page
            const metaKey = 'for_all_of_us'; // default to home page
            const metaTags = getMetaTags(metaKey);

            // Update meta tags
            document.title = metaTags.title;
            
            const metaDescription = document.querySelector('meta[name="description"]');
            if (metaDescription) {
                metaDescription.setAttribute('content', metaTags.description);
            }

            const metaKeywords = document.querySelector('meta[name="keywords"]');
            if (metaKeywords && metaTags.keywords.length > 0) {
                metaKeywords.setAttribute('content', metaTags.keywords.join(', '));
            }

            // Update OpenGraph meta tags if they exist
            const ogTitle = document.querySelector('meta[property="og:title"]');
            if (ogTitle) {
                ogTitle.setAttribute('content', metaTags.title);
            }

            const ogDescription = document.querySelector('meta[property="og:description"]');
            if (ogDescription) {
                ogDescription.setAttribute('content', metaTags.description);
            }

            const ogLocale = document.querySelector('meta[property="og:locale"]');
            if (ogLocale) {
                ogLocale.setAttribute('content', `${newLocale}_${newLocale.toUpperCase()}`);
            }

            // Update breadcrumbs with new translations
            updateNavigationAndBreadcrumbs();

            // Force re-render of components
            setTimeout(() => {
                // Dispatch event to inform parent components that language has changed
                dispatch('languageChanged', { 
                    locale: newLocale,
                    languageName: currentLanguageObj.name
                });
                
                // Dispatch global events to trigger UI updates
                window.dispatchEvent(new CustomEvent('language-changed'));
                
                // Dispatch another event after a short delay to ensure all components have updated
                setTimeout(() => {
                    window.dispatchEvent(new CustomEvent('language-changed-complete'));
                }, 50);
            }, 0);

            // --- Call API to save preference (Moved to the end of the try block) ---
            try {
                const response = await fetch(getApiUrl() + apiEndpoints.settings.user.language, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'Accept': 'application/json',
                    },
                    body: JSON.stringify({ language: newLocale }),
                    credentials: 'include' // Important for sending auth cookies
                });
                if (!response.ok) {
                    console.error('Failed to update language setting on server:', response.statusText);
                    // Optional: Add user feedback about the failure
                } else {
                    console.debug('Language preference saved to server successfully.');
                }
            } catch (apiError) {
                console.error('Error sending language setting to server:', apiError);
                // Optional: Add user feedback about the failure
            }
            // --- End API Call ---

        } catch (error) {
            console.error('Error changing language:', error);
            // Revert to previous language on error
            if (currentLanguage !== newLocale) {
                currentLanguage = newLocale;
                locale.set(currentLanguage);
            }
        }
    };

    // Special function to ensure breadcrumbs and navigation elements update
    function updateNavigationAndBreadcrumbs() {
        // Update settings navigation breadcrumbs using the current translations
        updateBreadcrumbsWithLanguage($text);
        
        // Force text store subscribers to update by dispatching a custom event
        window.dispatchEvent(new CustomEvent('language-changed'));
        
        // Force a re-render of all text elements
        const textElements = document.querySelectorAll('[data-i18n]');
        textElements.forEach(el => {
            // This triggers a re-render of the element
            el.classList.add('lang-refresh');
            setTimeout(() => el.classList.remove('lang-refresh'), 10);
        });
    }

    // Initialize on component mount
    onMount(() => {
        initializeLocale();
    });
</script>

<div class="settings-language-container">
    {#each sortedLanguages as language}
        <SettingsItem 
            type="quickaction"
            icon="subsetting_icon subsetting_icon_language"
            title={language.name}
            hasToggle={true}
            checked={currentLanguage === language.code}
            onClick={() => handleLanguageChange(language.code)}
        >
            <span slot="icon" class="language-code-overlay">
                {language.shortCode}
            </span>
        </SettingsItem>
    {/each}
</div>

<style>
    .settings-language-container {
        display: flex;
        flex-direction: column;
        gap: 5px;
    }
    
    .language-code-overlay {
        position: absolute;
        top: 50%;
        left: 50%;
        transform: translate(-50%, -50%);
        font-size: 16px;
        font-weight: 600;
        color: var(--color-grey-90);
        pointer-events: none;
        z-index: 2;
    }

    /* Ensures proper positioning of the language code over the icon */
    :global(.settings-language-container .subsetting_icon) {
        position: relative;
    }
</style>