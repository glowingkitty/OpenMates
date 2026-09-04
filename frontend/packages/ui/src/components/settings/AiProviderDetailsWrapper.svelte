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
    import { SettingsInfoBox, SettingsItem, SettingsPageContainer } from './elements';

    interface Props {
        activeSettingsView?: string;
    }

    let { activeSettingsView = '' }: Props = $props();
    const dispatch = createEventDispatcher();
    const providerId = $derived(activeSettingsView.replace('ai/provider/', ''));
    const providerModels = $derived(
        modelsMetadata
            .filter((model) => model.for_app_skill === 'ai.ask' && model.provider_id === providerId)
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
    <div class="ai-provider-body">
        {#if providerModels[0]}
            <section class="provider-identity" data-testid="ai-provider-identity">
                <span class="provider-icon-tile" aria-hidden="true">
                    <img src={getProviderIconUrl(providerModels[0].logo_svg)} alt="" />
                </span>
                <h3>{providerDisplay.brandName}</h3>
                {#if providerDisplay.brandName !== providerDisplay.companyName}
                    <p>{$text('enter_message.mention_dropdown.from_provider').replace('{provider}', providerDisplay.companyName)}</p>
                {/if}
            </section>
        {/if}

        <SettingsInfoBox type="info" plain={true} tone="muted" data-testid="ai-provider-guidance">
            {$text('settings.ai_ask.ai_ask_settings.provider_models_instruction')}
        </SettingsInfoBox>

        <section class="ai-section" data-testid="ai-provider-details">
            <h3 class="ai-section-title">{$text('settings.ai.provider_models_heading').replace('{provider}', providerDisplay.brandName)}</h3>
            <div class="ai-row-list">
                {#each providerModels as model (model.id)}
                    <SettingsItem
                        type="ai-row"
                        icon={model.provider_id}
                        iconSrc={getProviderIconUrl(model.logo_svg)}
                        iconAlt=""
                        title={model.name}
                        subtitleBottom={`${capabilityLabel(model)} · ${model.description}`}
                        hasToggle={isAuthenticated}
                        checked={isModelEnabled(model.id)}
                        data-testid="provider-model-item"
                        onClick={() => openModel(model)}
                        onToggleClick={() => toggleModel(model.id)}
                    />
                {/each}
            </div>
        </section>
    </div>
</SettingsPageContainer>

<style>
    .ai-provider-body {
        display: flex;
        flex-direction: column;
        gap: 1.25rem;
        width: min(100%, 20.1875rem);
        margin: 0 auto;
    }

    .provider-identity {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: var(--spacing-3);
        text-align: center;
    }

    .provider-icon-tile {
        display: flex;
        align-items: center;
        justify-content: center;
        width: 2.73125rem;
        height: 2.73125rem;
        padding: 0.5625rem;
        border-radius: 0.559rem;
        background: linear-gradient(135deg, var(--color-ai-icon-tile-start, var(--color-grey-10)) 9.04%, var(--color-ai-icon-tile-end, var(--color-grey-20)) 90.06%);
        box-shadow: 0.063rem 0.063rem 0.127rem rgba(0, 0, 0, 0.25);
        box-sizing: border-box;
    }

    .provider-icon-tile img {
        width: 100%;
        height: 100%;
        object-fit: contain;
    }

    .provider-identity h3,
    .provider-identity p {
        margin: 0;
    }

    .provider-identity h3 {
        color: var(--color-font-primary);
        font-size: var(--font-size-p);
        font-weight: 700;
        line-height: 1.25;
    }

    .provider-identity p {
        color: var(--color-ai-settings-muted, var(--color-font-secondary));
        font-size: var(--font-size-small);
        font-weight: 700;
        line-height: 1.25;
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
