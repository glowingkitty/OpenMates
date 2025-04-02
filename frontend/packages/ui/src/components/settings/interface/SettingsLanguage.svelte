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

    // Define supported languages with added shortCode property
    const baseLanguages: Language[] = [
        { code: 'en', name: 'English', shortCode: 'EN' },
        { code: 'de', name: 'Deutsch', shortCode: 'DE' },
        { code: 'es', name: 'Español', shortCode: 'ES' },
        { code: 'fr', name: 'Français', shortCode: 'FR' },
        { code: 'zh', name: '中文', shortCode: 'ZH' },
        { code: 'ja', name: '日本語', shortCode: 'JA' }
    ];

    // Current language state
    let currentLanguage = 'en';
    
    // Browser's default language (set only once)
    let browserLanguage = 'en';

    // Sort languages with browser language at top, but don't reorder when selecting
    // This is done once during initialization
    let sortedLanguages: Language[] = [];

    // Find the current language object
    $: currentLanguageObj = baseLanguages.find(lang => lang.code === currentLanguage) || baseLanguages[0];

    // Initialize locale from browser language and sort languages
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
            
            // Sort languages with browser language first, then alphabetically
            sortedLanguages = [...baseLanguages].sort((a, b) => {
                if (a.code === browserLanguage) return -1;
                if (b.code === browserLanguage) return 1;
                return a.name.localeCompare(b.name);
            });
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
            icon="language"
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