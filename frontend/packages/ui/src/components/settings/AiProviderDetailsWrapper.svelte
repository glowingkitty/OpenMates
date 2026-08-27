<!--
    AI provider-family detail page for the top-level AI settings flow.
    Lists product-family models rather than unrelated hosting servers.
    Model rows open details while their toggles control model availability.
    Design reference: Figma node 5815:60825.
-->
<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import { text } from '@repo/ui';
    import { authStore } from '../../stores/authStore';
    import { getProviderIconUrl } from '../../data/providerIcons';
    import { modelsMetadata, type AIModelMetadata } from '../../data/modelsMetadata';
    import { updateProfile, userProfile } from '../../stores/userProfile';
    import { getAiProviderDisplay, getModelCapabilityLevel } from '../../utils/aiModelDisplay';
    import { SettingsInfoBox, SettingsItem, SettingsPageContainer, SettingsSectionHeading } from './elements';

    interface Props {
        activeSettingsView?: string;
    }

    let { activeSettingsView = '' }: Props = $props();
    const dispatch = createEventDispatcher();
    const providerId = $derived(activeSettingsView.replace('ai/provider/', ''));
    const providerModels = $derived(
        modelsMetadata
            .filter((model) => model.for_app_skill === 'ai.ask' && model.provider_id === providerId)
            .sort((a, b) => a.name.localeCompare(b.name))
    );
    const providerDisplay = $derived(
        getAiProviderDisplay(providerId, providerModels[0]?.provider_name ?? providerId)
    );
    const disabledModels = $derived($userProfile.disabled_ai_models ?? []);
    const isAuthenticated = $derived($authStore.isAuthenticated);

    function isModelEnabled(modelId: string): boolean {
        return !disabledModels.includes(modelId);
    }

    function toggleModel(modelId: string): void {
        updateProfile({
            disabled_ai_models: isModelEnabled(modelId)
                ? [...disabledModels, modelId]
                : disabledModels.filter((id) => id !== modelId),
        });
    }

    function openModel(model: AIModelMetadata): void {
        dispatch('openSettings', {
            settingsPath: `ai/model/${model.id}`,
            direction: 'forward',
            icon: 'ai',
            title: model.name,
            cameFrom: activeSettingsView,
        });
    }

    function capabilityLabel(model: AIModelMetadata): string {
        return $text(`settings.ai_ask.ai_ask_settings.capability_${getModelCapabilityLevel(model)}`);
    }
</script>

<SettingsPageContainer maxWidth="wide">
    <SettingsInfoBox type="info">
        {$text('settings.ai_ask.ai_ask_settings.provider_models_instruction')}
    </SettingsInfoBox>

    <section data-testid="ai-provider-details">
        <SettingsSectionHeading
            title={$text('settings.ai.provider_models_heading').replace('{provider}', providerDisplay.brandName)}
            icon="ai"
        />
        {#each providerModels as model (model.id)}
            <SettingsItem
                type="submenu"
                icon={model.provider_id}
                iconSrc={getProviderIconUrl(model.logo_svg)}
                iconAlt=""
                title={model.name}
                subtitleBottom={capabilityLabel(model)}
                hasToggle={isAuthenticated}
                checked={isModelEnabled(model.id)}
                data-testid="provider-model-item"
                onClick={() => openModel(model)}
                onToggleClick={() => toggleModel(model.id)}
            />
        {/each}
    </section>
</SettingsPageContainer>
