<script lang="ts">
    import { text, SUPPORTED_LANGUAGES } from '@repo/ui';
    import { createEventDispatcher } from 'svelte';
    import { locale } from 'svelte-i18n';
    import SettingsItem from '../../SettingsItem.svelte';
    import { SettingsPageContainer, SettingsInfoBox } from '../elements';
    import { setAppLanguagePreference, languagePreferenceMode } from '../../../i18n/setup';
    import { updateBreadcrumbsWithLanguage } from '../../../stores/settingsNavigationStore';
    import { getApiUrl, apiEndpoints } from '../../../config/api';
    import { contentCache } from '../../../utils/contentCache';
    import { authStore } from '../../../stores/authStore';
    import { loadMetaTags, getMetaTags } from '../../../config/meta';
    import { updateProfile } from '../../../stores/userProfile';

    const dispatch = createEventDispatcher();
    let saving = $state(false);
    let saveError = $state(false);
    let activeLanguage = $derived(SUPPORTED_LANGUAGES.find(language => language.code === $locale)?.name ?? $locale ?? 'English');

    async function handleLanguageChange(choice: string): Promise<void> {
        if (saving) return;
        saving = true;
        saveError = false;
        try {
            const language = await setAppLanguagePreference(choice);
            updateBreadcrumbsWithLanguage($text);
            contentCache.clear();
            if ($authStore.isAuthenticated && choice !== 'auto') updateProfile({ language });
            dispatch('languageChanged', { locale: language, languageName: activeLanguage });
            try {
                await loadMetaTags();
                document.title = getMetaTags('for_all_of_us').title;
            } catch (error) { console.warn('[SettingsLanguage] Metadata refresh failed:', error); }
            if ($authStore.isAuthenticated && choice !== 'auto') {
                const response = await fetch(getApiUrl() + apiEndpoints.settings.user.language, {
                    method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
                    body: JSON.stringify({ language }), credentials: 'include',
                });
                if (!response.ok) saveError = true;
            }
        } catch (error) {
            saveError = true;
            console.warn('[SettingsLanguage] Could not save language preference:', error);
        } finally { saving = false; }
    }
</script>

<SettingsPageContainer>
    {#if saveError}
        <SettingsInfoBox type="warning" data-testid="language-save-error">{$text('settings.language.account_save_error')}</SettingsInfoBox>
    {/if}
    <SettingsItem
        type="quickaction" icon="subsetting_icon language"
        title={$text('settings.language.automatic')} subtitle={activeLanguage}
        hasToggle={true} checked={$languagePreferenceMode === 'auto'} disabled={saving}
        data-testid="language-option-auto" onClick={() => handleLanguageChange('auto')}
    />
    {#each SUPPORTED_LANGUAGES as language (language.code)}
        <SettingsItem
            type="quickaction" icon="subsetting_icon language" title={language.name}
            hasToggle={true} checked={$languagePreferenceMode !== 'auto' && $locale === language.code}
            disabled={saving} data-testid={`language-option-${language.code}`}
            onClick={() => handleLanguageChange(language.code)}
        />
    {/each}
</SettingsPageContainer>
