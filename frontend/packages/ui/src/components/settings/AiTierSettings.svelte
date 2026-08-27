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
    import { isProviderHealthy } from '../../stores/appHealthStore';
    import { updateProfile, userProfile } from '../../stores/userProfile';
    import { compareAiProviders, getAiProviderDisplay, getModelCapabilityLevel, getRecommendedModelForTier, getTierCapabilityLevel } from '../../utils/aiModelDisplay';
    import { aiModelSelectionValue } from '../../utils/aiModelSelection';
    import {
        SettingsInfoBox,
        SettingsItem,
        SettingsPageContainer,
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
    const aiModels = $derived(modelsMetadata.filter((model) =>
        model.for_app_skill === 'ai.ask'
        && !$userProfile.disabled_ai_models?.includes(model.id)
        && !!model.servers?.some((server) =>
            !$userProfile.disabled_ai_servers?.[model.id]?.includes(server.id)
            && $isProviderHealthy(server.id)
        )
    ));
    const providerModels = $derived(providerId ? aiModels.filter((model) => model.provider_id === providerId) : []);
    const recommendedModelId = $derived(getRecommendedModelForTier(providerModels, tier)?.id ?? null);
    const preferenceField = $derived<PreferenceField>(
        tier === 'simple'
            ? 'default_ai_model_simple'
            : tier === 'complex'
                ? 'default_ai_model_complex'
                : 'default_ai_model_most_demanding'
    );
    const currentSelection = $derived($userProfile[preferenceField] ?? null);
    const tierCapability = $derived(getTierCapabilityLevel(tier));
    const tierCapabilityLabel = $derived($text(`settings.ai_ask.ai_ask_settings.capability_${tierCapability}`));
    const providers = $derived.by(() => {
        const result = new Map<string, AIModelMetadata>();
        for (const model of aiModels) {
            if (!result.has(model.provider_id)) result.set(model.provider_id, model);
        }
        return [...result.values()].sort(compareAiProviders);
    });

    function modelSubtitle(model: AIModelMetadata): string {
        const recommendation = model.id === recommendedModelId
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
        const display = getAiProviderDisplay(model.provider_id, model.provider_name);
        dispatch('openSettings', {
            settingsPath: `ai/tier/${tier}/provider/${model.provider_id}`,
            direction: 'forward',
            icon: 'ai',
            title: display.brandName,
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

    function capabilityLabel(level: ReturnType<typeof getModelCapabilityLevel>): string {
        return $text(`settings.ai_ask.ai_ask_settings.capability_${level}`);
    }
</script>

<SettingsPageContainer maxWidth="wide">
    <div class="ai-tier-body">
        <SettingsInfoBox type="info" plain={true} tone="muted" data-testid="ai-tier-routing-note">
            {providerId
                ? $text('settings.ai_ask.ai_ask_settings.choose_exact_model')
                : $text('settings.ai_ask.ai_ask_settings.choose_tier_provider')}
        </SettingsInfoBox>

        <section class="ai-section" data-testid="ai-tier-provider-catalog">
            <h3 class="ai-section-title">{$text('settings.ai_ask.ai_ask_settings.default_models')}</h3>
            <div class="ai-row-list">
                <SettingsItem
                    type="ai-row"
                    capability={tierCapability}
                    capabilityLabel={tierCapabilityLabel}
                    title={$text('settings.ai_ask.ai_ask_settings.model_auto')}
                    subtitleBottom={$text('settings.ai_ask.ai_ask_settings.auto_description')}
                    hasToggle={true}
                    checked={currentSelection === null}
                    data-testid="ai-model-option-auto"
                    onClick={() => saveSelection(null)}
                />
            </div>

            <h3 class="ai-section-title">{providerId ? getAiProviderDisplay(providerId, providerModels[0]?.provider_name ?? providerId).brandName : $text('settings.ai_ask.ai_ask_settings.models_and_accounts')}</h3>
            <div class="ai-row-list">
                {#if providerId}
                    {#each providerModels as model (model.id)}
                        <SettingsItem
                            type="ai-row"
                            icon={model.provider_id}
                            iconSrc={getProviderIconUrl(model.logo_svg)}
                            iconAlt=""
                            title={model.name}
                            subtitleBottom={`${modelSubtitle(model)} · ${capabilityLabel(getModelCapabilityLevel(model))}`}
                            hasToggle={true}
                            checked={currentSelection === aiModelSelectionValue(model)}
                            data-testid="ai-model-option-exact"
                            onClick={() => openModel(model)}
                            onToggleClick={() => saveSelection(aiModelSelectionValue(model))}
                        />
                    {/each}
                {:else}
                    {#each providers as model (model.provider_id)}
                        {@const display = getAiProviderDisplay(model.provider_id, model.provider_name)}
                        <SettingsItem
                            type="ai-row"
                            icon={model.provider_id}
                            iconSrc={getProviderIconUrl(model.logo_svg)}
                            iconAlt=""
                            title={display.brandName}
                            subtitleBottom={display.brandName !== display.companyName ? $text('enter_message.mention_dropdown.from_provider').replace('{provider}', display.companyName) : $text('settings.ai_ask.ai_ask_settings.view_provider_models')}
                            data-testid="ai-provider-family-card"
                            onClick={() => openProvider(model)}
                        />
                    {/each}
                {/if}
            </div>
        </section>
    </div>
</SettingsPageContainer>

<style>
    .ai-tier-body {
        display: flex;
        flex-direction: column;
        gap: 1.25rem;
        width: min(100%, 20.1875rem);
        margin: 0 auto;
    }

    .ai-section,
    .ai-row-list {
        display: flex;
        flex-direction: column;
    }

    .ai-section {
        gap: var(--spacing-5);
    }

    .ai-row-list {
        gap: var(--spacing-4);
    }

    .ai-section-title {
        margin: 0 var(--spacing-10);
        color: var(--color-font-primary);
        font-size: var(--font-size-p);
        font-weight: 700;
        line-height: 1.25;
    }
</style>
