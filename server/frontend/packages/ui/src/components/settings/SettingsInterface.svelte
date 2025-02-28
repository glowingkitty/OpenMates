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
    import { createEventDispatcher, onMount } from 'svelte';
    import SettingsItem from '../SettingsItem.svelte';
    import SettingsLanguage from './interface/SettingsLanguage.svelte';
    import { locale } from 'svelte-i18n';
    import { browser } from '$app/environment';

    const dispatch = createEventDispatcher();
    
    // Track current view within this component
    let currentView = 'main';
    let childComponent = null;

    // Language data
    type Language = {
        code: string;
        name: string;
        shortCode: string;
    };

    const supportedLanguages: Language[] = [
        { code: 'en', name: 'English', shortCode: 'EN' },
        { code: 'de', name: 'Deutsch', shortCode: 'DE' },
        { code: 'es', name: 'Español', shortCode: 'ES' },
        { code: 'fr', name: 'Français', shortCode: 'FR' },
        { code: 'zh', name: '中文', shortCode: 'ZH' },
        { code: 'ja', name: '日本語', shortCode: 'JA' }
    ];

    let currentLanguage = 'en';
    $: currentLanguageObj = supportedLanguages.find(lang => lang.code === currentLanguage) || supportedLanguages[0];

    // Initialize current language
    onMount(() => {
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
    });

    // This function will properly dispatch the event to the parent Settings.svelte component
    function showLanguageSettings() {
        currentView = 'language';
        childComponent = SettingsLanguage;
        
        dispatch('openSettings', {
            settingsPath: 'interface/language', 
            direction: 'forward',
            icon: 'language',
            title: $text('settings.language.text'),
            translationKey: 'settings.language'
        });
    }

    // Handle language change event from SettingsLanguage component
    function handleLanguageChanged(event) {
        currentLanguage = event.detail.locale;
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
        subtitle={$text('settings.language.text')}
        title={currentLanguageObj.name}
        onClick={showLanguageSettings}
    />
{:else if currentView === 'language' && childComponent}
    <svelte:component 
        this={childComponent} 
        on:languageChanged={handleLanguageChanged} 
    />
{/if}