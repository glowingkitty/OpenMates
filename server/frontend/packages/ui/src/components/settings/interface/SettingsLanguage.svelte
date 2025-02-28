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

    const dispatch = createEventDispatcher();

    // Type definition for supported languages
    type Language = {
        code: string;
        name: string;
        shortCode: string; // Two letter code for display
    };

    // Define supported languages with added shortCode property
    const supportedLanguages: Language[] = [
        { code: 'en', name: 'English', shortCode: 'EN' },
        { code: 'de', name: 'Deutsch', shortCode: 'DE' },
        { code: 'es', name: 'Español', shortCode: 'ES' },
        { code: 'fr', name: 'Français', shortCode: 'FR' },
        { code: 'zh', name: '中文', shortCode: 'ZH' },
        { code: 'ja', name: '日本語', shortCode: 'JA' }
    ];

    // Current language state
    let currentLanguage = 'en';

    // Initialize locale from browser language
    const initializeLocale = () => {
        if (browser) {
            const savedLocale = localStorage.getItem('preferredLanguage');
            if (savedLocale && supportedLanguages.some(lang => lang.code === savedLocale)) {
                currentLanguage = savedLocale;
            } else {
                // Use browser language
                const browserLang = navigator.language.split('-')[0];
                if (supportedLanguages.some(lang => lang.code === browserLang)) {
                    currentLanguage = browserLang;
                } else {
                    currentLanguage = 'en';
                }
            }
        }
    };

    // Handle language change
    const handleLanguageChange = async (newLocale: string) => {
        if (!browser) return;
        
        // Skip if already selected
        if (newLocale === currentLanguage) return;
        
        currentLanguage = newLocale;
        console.log('Changing language to:', newLocale);

        // Store preference in localStorage
        localStorage.setItem('preferredLanguage', newLocale);
        
        try {
            // Set new locale and wait for translations to load
            await locale.set(newLocale);
            await waitLocale();

            // Update HTML lang attribute
            document.documentElement.setAttribute('lang', newLocale);

            // Reload meta tags with new language
            await loadMetaTags();

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
            if (metaKeywords) {
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

            // Dispatch event to inform parent components that language has changed
            dispatch('languageChanged', { locale: newLocale });

        } catch (error) {
            console.error('Error changing language:', error);
        }
    };

    // Initialize on component mount
    onMount(() => {
        initializeLocale();
    });
</script>

<div class="settings-language-container">
    {#each supportedLanguages as language}
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