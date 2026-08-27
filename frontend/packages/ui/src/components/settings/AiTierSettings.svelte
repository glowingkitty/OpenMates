<!-- frontend/packages/ui/src/components/settings/AiTierSettings.svelte -->
<!-- Contextual model selection page for one AI request tier. -->
<!-- Shows Auto first, then provider families or exact provider models. -->
<!-- Persists one exclusive model preference through the settings API. -->
<!-- Design reference: Figma node 4406:53279. -->

<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import { text } from '@repo/ui';
    import { getApiUrl, apiEndpoints } from '../../config/api';
    import { getProviderIconUrl } from '../../data/providerIcons';
    import { modelsMetadata, type AIModelMetadata } from '../../data/modelsMetadata';
    import { notificationStore } from '../../stores/notificationStore';
    import { updateProfile, userProfile } from '../../stores/userProfile';
    import { simplifyProviderName } from '../../utils/providerDisplay';
    import {
        SettingsInfoBox,
        SettingsItem,
        SettingsPageContainer,
        SettingsSectionHeading,
    } from './elements';

    interface Props {
        activeSettingsView?: string;
    }

    type Tier = 'simple' | 'complex' | 'most-demanding';
    type PreferenceField =
        | 'default_ai_model_simple'
        | 'default_ai_model_complex'
        | 'default_ai_model_most_demanding';

    let { activeSettingsView = 'ai/tier/simple' }: Props = $props();
    const dispatch = createEventDispatcher();
    const pathParts = $derived(activeSettingsView.split('/'));
    const tier = $derived((pathParts[2] ?? 'simple') as Tier);
    const providerId = $derived(pathParts[3] === 'provider' ? pathParts[4] : null);
    const aiModels = $derived(modelsMetadata.filter((model) => model.for_app_skill === 'ai.ask'));
    const providerModels = $derived(providerId ? aiModels.filter((model) => model.provider_id === providerId) : []);
    const preferenceField = $derived<PreferenceField>(
        tier === 'simple'
            ? 'default_ai_model_simple'
            : tier === 'complex'
                ? 'default_ai_model_complex'
                : 'default_ai_model_most_demanding'
    );
    const currentSelection = $derived($userProfile[preferenceField] ?? null);
    const providers = $derived.by(() => {
        const result = new Map<string, AIModelMetadata>();
        for (const model of aiModels) {
            if (!result.has(model.provider_id)) result.set(model.provider_id, model);
        }
        return [...result.values()].sort((a, b) =>
            simplifyProviderName(a.provider_name).localeCompare(simplifyProviderName(b.provider_name))
        );
    });

    function modelValue(model: AIModelMetadata): string {
        return `${model.provider_id}/${model.id}`;
    }

    function tierTitle(): string {
        if (tier === 'simple') return $text('settings.ai_ask.ai_ask_settings.simple_requests');
        if (tier === 'complex') return $text('settings.ai_ask.ai_ask_settings.complex_requests');
        return $text('settings.ai_ask.ai_ask_settings.most_demanding_requests');
    }

    function modelSubtitle(model: AIModelMetadata, index: number): string {
        const recommendation = index === 0
            ? `${$text('settings.ai_ask.ai_ask_settings.recommended')} · `
            : '';
        return `${recommendation}${model.tier} · ${model.description}`;
    }

    async function saveSelection(selection: string | null): Promise<void> {
        if (selection === currentSelection) return;
        const previous = currentSelection;
        updateProfile({ [preferenceField]: selection });
        try {
            const response = await fetch(getApiUrl() + apiEndpoints.settings.aiModelDefaults, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
                body: JSON.stringify({ [preferenceField]: selection }),
                credentials: 'include',
            });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
        } catch (error) {
            console.error('[AiTierSettings] Failed to save tier model selection:', error);
            updateProfile({ [preferenceField]: previous });
            notificationStore.error($text('settings.ai_ask.ai_ask_settings.default_models_save_error'));
        }
    }

    function openProvider(model: AIModelMetadata): void {
        dispatch('openSettings', {
            settingsPath: `ai/tier/${tier}/provider/${model.provider_id}`,
            direction: 'forward',
            icon: 'ai',
            title: simplifyProviderName(model.provider_name),
        });
    }
</script>

<SettingsPageContainer maxWidth="wide">
    <SettingsInfoBox type="info">
        {providerId
            ? $text('settings.ai_ask.ai_ask_settings.choose_exact_model')
            : $text('settings.ai_ask.ai_ask_settings.choose_tier_provider')}
    </SettingsInfoBox>

    <section data-testid="ai-tier-provider-catalog">
        <SettingsSectionHeading
            title={providerId ? simplifyProviderName(providerModels[0]?.provider_name ?? providerId) : tierTitle()}
            icon="ai"
        />
        <SettingsItem
            type="toggle"
            icon="ai"
            title={$text('settings.ai_ask.ai_ask_settings.model_auto')}
            subtitleTop={$text('settings.ai_ask.ai_ask_settings.auto_description')}
            hasToggle={true}
            checked={currentSelection === null}
            data-testid="ai-model-option-auto"
            onClick={() => saveSelection(null)}
        />

        {#if providerId}
            {#each providerModels as model, index (model.id)}
                <SettingsItem
                    type="toggle"
                    iconSrc={getProviderIconUrl(model.logo_svg)}
                    iconAlt=""
                    title={model.name}
                    subtitleTop={modelSubtitle(model, index)}
                    hasToggle={true}
                    checked={currentSelection === modelValue(model)}
                    data-testid="ai-model-option-exact"
                    onClick={() => saveSelection(modelValue(model))}
                />
            {/each}
        {:else}
            {#each providers as model (model.provider_id)}
                <SettingsItem
                    type="submenu"
                    iconSrc={getProviderIconUrl(model.logo_svg)}
                    iconAlt=""
                    title={simplifyProviderName(model.provider_name)}
                    subtitleTop={$text('settings.ai_ask.ai_ask_settings.view_provider_models')}
                    data-testid="ai-provider-family-card"
                    onClick={() => openProvider(model)}
                />
            {/each}
        {/if}
    </section>
</SettingsPageContainer>
