<!-- frontend/packages/ui/src/components/settings/SettingsAI.svelte -->
<!-- Top-level AI settings page for routing defaults and model providers. -->
<!-- Uses the canonical settings element system for consistent layout. -->
<!-- Persists response behavior through the authenticated settings endpoint. -->
<!-- Design reference: Figma node 4406:53279. -->

<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import { text } from '@repo/ui';
    import { authStore } from '../../stores/authStore';
    import { getApiUrl, apiEndpoints } from '../../config/api';
    import { getProviderIconUrl } from '../../data/providerIcons';
    import { modelsMetadata, type AIModelMetadata } from '../../data/modelsMetadata';
    import { notificationStore } from '../../stores/notificationStore';
    import { updateProfile, userProfile } from '../../stores/userProfile';
    import { compareAiProviders, getAiProviderDisplay, getTierCapabilityLevel } from '../../utils/aiModelDisplay';
    import { aiModelSelectionValue } from '../../utils/aiModelSelection';
    import {
        SettingsInfoBox,
        SettingsItem,
        SettingsModelPreferenceItem,
        SettingsPageContainer,
        SettingsSectionHeading,
    } from './elements';

    const dispatch = createEventDispatcher();
    const isAuthenticated = $derived($authStore.isAuthenticated);
    const defaultSimple = $derived($userProfile.default_ai_model_simple ?? null);
    const defaultComplex = $derived($userProfile.default_ai_model_complex ?? null);
    const defaultMostDemanding = $derived($userProfile.default_ai_model_most_demanding ?? null);
    const followUpSuggestionsEnabled = $derived($userProfile.follow_up_suggestions_enabled !== false);
    const quickTipsEnabled = $derived($userProfile.quick_tips_enabled !== false);
    const aiModels = $derived(modelsMetadata.filter((model) => model.for_app_skill === 'ai.ask'));
    const providerFamilies = $derived.by(() => {
        const providers = new Map<string, AIModelMetadata>();
        for (const model of aiModels) {
            if (!providers.has(model.provider_id)) providers.set(model.provider_id, model);
        }
        return [...providers.values()].sort(compareAiProviders);
    });

    function modelLabel(value: string | null): string {
        if (value === null) return $text('settings.ai_ask.ai_ask_settings.model_auto');
        return modelsMetadata.find((model) => aiModelSelectionValue(model) === value)?.name ?? value;
    }

    function openTier(tier: 'simple' | 'complex' | 'most-demanding'): void {
        const title = tier === 'simple'
            ? $text('settings.ai_ask.ai_ask_settings.simple_requests')
            : tier === 'complex'
                ? $text('settings.ai_ask.ai_ask_settings.complex_requests')
                : $text('settings.ai_ask.ai_ask_settings.most_demanding_requests');
        dispatch('openSettings', { settingsPath: `ai/tier/${tier}`, direction: 'forward', icon: 'ai', title });
    }

    function openProvider(model: AIModelMetadata): void {
        const display = getAiProviderDisplay(model.provider_id, model.provider_name);
        dispatch('openSettings', {
            settingsPath: `ai/provider/${model.provider_id}`,
            direction: 'forward',
            icon: 'ai',
            title: display.brandName,
        });
    }

    async function saveResponseSetting(
        field: 'follow_up_suggestions_enabled' | 'quick_tips_enabled',
        nextValue: boolean,
    ): Promise<void> {
        updateProfile({ [field]: nextValue });
        try {
            const response = await fetch(getApiUrl() + apiEndpoints.settings.aiModelDefaults, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
                body: JSON.stringify({ [field]: nextValue }),
                credentials: 'include',
            });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
        } catch (error) {
            console.error(`[SettingsAI] Failed to save ${field}:`, error);
            updateProfile({ [field]: !nextValue });
            notificationStore.error($text('settings.ai_ask.ai_ask_settings.default_models_save_error'));
        }
    }
</script>

<div data-testid="ai-settings">
    <SettingsPageContainer maxWidth="wide">
        <SettingsInfoBox type="info" ariaLabel={$text('common.pricing')}>
            <strong>{$text('common.pricing')}:</strong>
            {$text('settings.ai_ask.ai_ask_settings.pricing_note')}
        </SettingsInfoBox>

        {#if isAuthenticated}
            <section data-testid="ai-default-models-group">
                <SettingsSectionHeading title={$text('settings.ai_ask.ai_ask_settings.default_models')} icon="ai" />
                <SettingsModelPreferenceItem title={$text('settings.ai_ask.ai_ask_settings.simple_requests')} value={modelLabel(defaultSimple)} capability={getTierCapabilityLevel('simple')} capabilityLabel={$text('settings.ai_ask.ai_ask_settings.capability_low')} data-testid="ai-tier-row-simple" onEdit={() => openTier('simple')} />
                <SettingsModelPreferenceItem title={$text('settings.ai_ask.ai_ask_settings.complex_requests')} value={modelLabel(defaultComplex)} capability={getTierCapabilityLevel('complex')} capabilityLabel={$text('settings.ai_ask.ai_ask_settings.capability_high')} data-testid="ai-tier-row-complex" onEdit={() => openTier('complex')} />
                <SettingsModelPreferenceItem title={$text('settings.ai_ask.ai_ask_settings.most_demanding_requests')} value={modelLabel(defaultMostDemanding)} capability={getTierCapabilityLevel('most-demanding')} capabilityLabel={$text('settings.ai_ask.ai_ask_settings.capability_max')} data-testid="ai-tier-row-most-demanding" onEdit={() => openTier('most-demanding')} />
            </section>
        {/if}

        <section data-testid="ai-models-accounts-group">
            <SettingsSectionHeading title={$text('settings.ai_ask.ai_ask_settings.models_and_accounts')} icon="search" />
            {#each providerFamilies as model (model.provider_id)}
                {@const display = getAiProviderDisplay(model.provider_id, model.provider_name)}
                <SettingsItem
                    type="submenu"
                    icon={model.provider_id}
                    iconSrc={getProviderIconUrl(model.logo_svg)}
                    iconAlt=""
                    title={display.brandName}
                    subtitleBottom={display.brandName !== display.companyName ? $text('enter_message.mention_dropdown.from_provider').replace('{provider}', display.companyName) : undefined}
                    data-testid="ai-provider-family-card"
                    onClick={() => openProvider(model)}
                />
            {/each}
        </section>

        {#if isAuthenticated}
            <section data-testid="ai-response-settings-group">
                <SettingsSectionHeading title={$text('settings.ai_ask.ai_ask_settings.response_settings')} icon="settings" />
                <SettingsItem type="submenu" icon="chat" title={$text('settings.ai_ask.ai_ask_settings.follow_up_suggestions')} subtitleBottom={$text('settings.ai_ask.ai_ask_settings.follow_up_suggestions_description')} hasToggle={true} checked={followUpSuggestionsEnabled} data-testid="ai-response-feature-follow-up-suggestions" onClick={() => saveResponseSetting('follow_up_suggestions_enabled', !followUpSuggestionsEnabled)} />
                <SettingsItem type="submenu" icon="insight" title={$text('settings.ai_ask.ai_ask_settings.quick_tips')} subtitleBottom={$text('settings.ai_ask.ai_ask_settings.quick_tips_description')} hasToggle={true} checked={quickTipsEnabled} data-testid="ai-response-feature-quick-tips" onClick={() => saveResponseSetting('quick_tips_enabled', !quickTipsEnabled)} />
            </section>
        {/if}
    </SettingsPageContainer>
</div>
