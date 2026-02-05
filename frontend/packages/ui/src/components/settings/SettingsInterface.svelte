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
    import { createEventDispatcher, onMount } from 'svelte';
    import SettingsItem from '../SettingsItem.svelte';
    import SettingsLanguage from './interface/SettingsLanguage.svelte';
    import { locale, waitLocale } from 'svelte-i18n';
    import { browser } from '$app/environment';
    import { get } from 'svelte/store';

    const dispatch = createEventDispatcher();
    
    // Track current view within this component
    let currentView = $state('main');
    let childComponent = $state(null);

    // Language data
    type Language = {
        code: string;
        name: string;
        shortCode: string;
    };

    // Import supported languages from single source of truth
    const supportedLanguages: Language[] = SUPPORTED_LANGUAGES;

    // Make currentLanguage reactive to the locale store from svelte-i18n
    // This ensures it updates when language changes via SettingsLanguage component or ?lang= parameter
    // $locale is the reactive way to access the locale store in Svelte 5
    let currentLanguage = $derived($locale || 'en');
    
    // Find the current language object reactively based on the current locale
    let currentLanguageObj = $derived(
        supportedLanguages.find(lang => lang.code === currentLanguage) || supportedLanguages[0]
    );

    // Handle ?lang= URL parameter on mount
    // This ensures the language is set correctly when the component loads with a URL parameter
    onMount(() => {
        if (browser) {
            // Check for ?lang= URL parameter
            const urlParams = new URLSearchParams(window.location.search);
            const langParam = urlParams.get('lang');
            
            if (langParam && supportedLanguages.some(lang => lang.code === langParam)) {
                // If URL parameter exists and is valid, set the locale
                // This will automatically update currentLanguage via $derived
                locale.set(langParam);
                waitLocale().then(() => {
                    // Store preference in localStorage and cookies
                    localStorage.setItem('preferredLanguage', langParam);
                    document.cookie = `preferredLanguage=${langParam}; path=/; max-age=31536000; SameSite=Lax`;
                    
                    // Update HTML lang attribute
                    document.documentElement.setAttribute('lang', langParam);
                    
                    console.debug('[SettingsInterface] Language set from URL parameter:', langParam);
                });
            }
            
            // Also listen to global language-changed events as a backup
            // This ensures we react to language changes even if the locale store doesn't update immediately
            // Note: The $derived($locale) will automatically update, but we listen to events for debugging
            const handleLanguageChangedEvent = () => {
                // The $locale derived value will automatically update
                // We can read the current locale for logging purposes
                const currentLocale = get(locale);
                console.debug('[SettingsInterface] Language changed event received, current locale:', currentLocale);
            };
            
            window.addEventListener('language-changed', handleLanguageChangedEvent);
            window.addEventListener('language-changed-complete', handleLanguageChangedEvent);
            
            // Cleanup event listeners on component destroy
            return () => {
                window.removeEventListener('language-changed', handleLanguageChangedEvent);
                window.removeEventListener('language-changed-complete', handleLanguageChangedEvent);
            };
        }
    });

    // This function will properly dispatch the event to the parent Settings.svelte component
    function showLanguageSettings(event = null) {
        // Stop propagation to prevent the event from bubbling up to document
        if (event) event.stopPropagation();
        
        currentView = 'language';
        childComponent = SettingsLanguage;
        
        dispatch('openSettings', {
            settingsPath: 'interface/language', 
            direction: 'forward',
            icon: 'language',
            title: $text('settings.interface.language.text'),
            translationKey: 'settings.interface.language'
        });
        
        // Find settings content element and scroll to top
        const settingsContent = document.querySelector('.settings-content-wrapper');
        if (settingsContent) {
            settingsContent.scrollTo({
                top: 0,
                behavior: 'smooth'
            });
        }
    }

    // Handle language change event from SettingsLanguage component
    // Note: We don't need to manually update currentLanguage here because it's now
    // derived from the $locale store, which is automatically updated by SettingsLanguage
    function handleLanguageChanged(event) {
        // The locale store has already been updated by SettingsLanguage component
        // currentLanguage will automatically update via $derived($locale)
        console.debug('[SettingsInterface] Language changed event received:', event.detail.locale);
        
        // Go back to main view after selection
        currentView = 'main';
        childComponent = null;
        
        // Let parent Settings component know we want to go back to interface main view
        dispatch('navigateBack');
    }


</script>

{#if currentView === 'main'}
    <SettingsItem 
        type="subsubmenu"
        icon="subsetting_icon subsetting_icon_language"
        subtitle={$text('settings.interface.language.text')}
        title={currentLanguageObj.name}
        onClick={() => showLanguageSettings()}
    />
{:else if currentView === 'language' && childComponent}
    {@const Component = childComponent}
    <Component 
        on:languageChanged={handleLanguageChanged} 
    />
{/if}