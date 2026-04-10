<!-- frontend/packages/ui/src/components/settings/SettingsAI.svelte
     Top-level AI settings page consolidating model selection, pricing,
     and settings & memories that previously lived under the AI app in the
     app store. Replaces the old "Chat" settings sidebar entry.

     Sections (order matches Figma design):
     1. Pricing
     2. Default models
     3. Settings & Memories
     4. Available providers (server provider toggles)
     5. Available models
-->

<script lang="ts">
    import { createEventDispatcher, onMount } from 'svelte';
    import { text } from '@repo/ui';
    import { authStore } from '../../stores/authStore';
    import { userProfile, updateProfile } from '../../stores/userProfile';
    import { modelsMetadata, type AIModelMetadata } from '../../data/modelsMetadata';
    import { getProviderIconUrl } from '../../data/providerIcons';
    import { providersMetadata } from '../../data/providersMetadata';
    import { appSkillsStore } from '../../stores/appSkillsStore';
    import { appSettingsMemoriesStore } from '../../stores/appSettingsMemoriesStore';
    import { notificationStore } from '../../stores/notificationStore';
    import { getApiUrl, apiEndpoints } from '../../config/api';
    import { SettingsSectionHeading } from './elements';
    import Toggle from '../Toggle.svelte';
    import Icon from '../Icon.svelte';
    import SearchSortBar from './SearchSortBar.svelte';
    import AppStoreCard from './AppStoreCard.svelte';
    import type { AppMetadata } from '../../types/apps';

    const dispatch = createEventDispatcher();

    // --- Auth state ---
    let isAuthenticated = $derived($authStore.isAuthenticated);

    // ─── Model settings (from AiAskSkillSettings) ────────────────────────

    let searchQuery = $state('');
    let sortBy = $state<'price' | 'performance' | 'new'>('performance');

    // Default model preferences
    let defaultSimple = $derived($userProfile.default_ai_model_simple ?? null);
    let defaultComplex = $derived($userProfile.default_ai_model_complex ?? null);

    let autoSelectEnabled = $derived(defaultSimple === null && defaultComplex === null);
    let manualModeEnabled = $state(false);
    let isAutoSelectOn = $derived(autoSelectEnabled && !manualModeEnabled);

    // Ordered model lists for dropdowns
    let simpleDropdownModels = $derived.by(() => {
        const tierOrder: Record<string, number> = { economy: 1, standard: 2, premium: 3 };
        return modelsMetadata
            .filter(m => m.for_app_skill === 'ai.ask')
            .sort((a, b) => (tierOrder[a.tier] ?? 2) - (tierOrder[b.tier] ?? 2) || a.name.localeCompare(b.name));
    });

    let complexDropdownModels = $derived.by(() => {
        const tierOrder: Record<string, number> = { premium: 1, standard: 2, economy: 3 };
        return modelsMetadata
            .filter(m => m.for_app_skill === 'ai.ask')
            .sort((a, b) => (tierOrder[a.tier] ?? 2) - (tierOrder[b.tier] ?? 2) || a.name.localeCompare(b.name));
    });

    function modelToValue(model: AIModelMetadata): string {
        return `${model.provider_id}/${model.id}`;
    }

    function getModelDisplayLabel(value: string | null | undefined): string {
        if (value === null || value === undefined) {
            return $text('settings.ai_ask.ai_ask_settings.model_auto');
        }
        const model = modelsMetadata.find((m) => modelToValue(m) === value);
        return model?.name ?? value;
    }

    function buildDefaultModelChangeMessage(
        previousSimple: string | null,
        previousComplex: string | null,
        nextSimple: string | null,
        nextComplex: string | null,
    ): string | null {
        const messages: string[] = [];
        if (previousSimple !== nextSimple) {
            messages.push(
                `Changed model for ${$text('settings.ai_ask.ai_ask_settings.simple_requests')} ` +
                `from '${getModelDisplayLabel(previousSimple)}' to '${getModelDisplayLabel(nextSimple)}'`
            );
        }
        if (previousComplex !== nextComplex) {
            messages.push(
                `Changed model for ${$text('settings.ai_ask.ai_ask_settings.complex_requests')} ` +
                `from '${getModelDisplayLabel(previousComplex)}' to '${getModelDisplayLabel(nextComplex)}'`
            );
        }
        return messages.length === 0 ? null : messages.join('. ') + '.';
    }

    async function saveDefaultModels(newSimple: string | null, newComplex: string | null): Promise<void> {
        const previousSimple = defaultSimple;
        const previousComplex = defaultComplex;
        if (previousSimple === newSimple && previousComplex === newComplex) return;

        const successMessage = buildDefaultModelChangeMessage(previousSimple, previousComplex, newSimple, newComplex);

        updateProfile({
            default_ai_model_simple: newSimple,
            default_ai_model_complex: newComplex,
        });

        try {
            const response = await fetch(getApiUrl() + apiEndpoints.settings.aiModelDefaults, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
                body: JSON.stringify({ default_ai_model_simple: newSimple, default_ai_model_complex: newComplex }),
                credentials: 'include',
            });
            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                console.error(`[SettingsAI] Failed to save default models: ${response.status} – ${errorData?.detail ?? 'unknown error'}`);
                notificationStore.error($text('settings.ai_ask.ai_ask_settings.default_models_save_error'));
            } else if (successMessage) {
                notificationStore.success(successMessage);
            }
        } catch (err) {
            console.error('[SettingsAI] Network error while saving default models:', err);
            notificationStore.error($text('settings.ai_ask.ai_ask_settings.default_models_save_error'));
        }
    }

    async function handleAutoSelectToggle(): Promise<void> {
        if (isAutoSelectOn) {
            manualModeEnabled = true;
        } else {
            manualModeEnabled = false;
            await saveDefaultModels(null, null);
        }
    }

    async function handleSimpleChange(event: Event): Promise<void> {
        const select = event.target as HTMLSelectElement;
        const value = select.value === '' ? null : select.value;
        await saveDefaultModels(value, defaultComplex);
    }

    async function handleComplexChange(event: Event): Promise<void> {
        const select = event.target as HTMLSelectElement;
        const value = select.value === '' ? null : select.value;
        await saveDefaultModels(defaultSimple, value);
    }

    let aiAskModels = $derived(modelsMetadata.filter(model => model.for_app_skill === 'ai.ask'));
    let disabledModels = $derived($userProfile.disabled_ai_models || []);

    let filteredModels = $derived.by(() => {
        let models = [...aiAskModels];
        if (searchQuery.trim()) {
            const query = searchQuery.toLowerCase();
            models = models.filter(model =>
                model.name.toLowerCase().includes(query) ||
                model.provider_name.toLowerCase().includes(query) ||
                model.description.toLowerCase().includes(query)
            );
        }
        models.sort((a, b) => {
            switch (sortBy) {
                case 'price': {
                    const aPriceScore = (a.pricing?.input_tokens_per_credit || 0) + (a.pricing?.output_tokens_per_credit || 0);
                    const bPriceScore = (b.pricing?.input_tokens_per_credit || 0) + (b.pricing?.output_tokens_per_credit || 0);
                    return bPriceScore - aPriceScore;
                }
                case 'performance': {
                    const tierOrder = { premium: 3, standard: 2, economy: 1 };
                    const tierDiff = tierOrder[b.tier] - tierOrder[a.tier];
                    if (tierDiff !== 0) return tierDiff;
                    return a.name.localeCompare(b.name);
                }
                case 'new': {
                    const aDate = a.release_date ? new Date(a.release_date).getTime() : 0;
                    const bDate = b.release_date ? new Date(b.release_date).getTime() : 0;
                    return bDate - aDate;
                }
                default:
                    return 0;
            }
        });
        return models;
    });

    let cheapestPricing = $derived.by(() => {
        let maxInputTokens = 0;
        let maxOutputTokens = 0;
        for (const model of aiAskModels) {
            if (model.pricing) {
                if (model.pricing.input_tokens_per_credit && model.pricing.input_tokens_per_credit > maxInputTokens) {
                    maxInputTokens = model.pricing.input_tokens_per_credit;
                }
                if (model.pricing.output_tokens_per_credit && model.pricing.output_tokens_per_credit > maxOutputTokens) {
                    maxOutputTokens = model.pricing.output_tokens_per_credit;
                }
            }
        }
        return { input: maxInputTokens, output: maxOutputTokens };
    });

    function isModelEnabled(modelId: string): boolean {
        return !disabledModels.includes(modelId);
    }

    function handleModelToggle(modelId: string) {
        const currentDisabled = [...disabledModels];
        const isCurrentlyEnabled = isModelEnabled(modelId);
        const newDisabled = isCurrentlyEnabled
            ? [...currentDisabled, modelId]
            : currentDisabled.filter(id => id !== modelId);
        updateProfile({ disabled_ai_models: newDisabled });
    }

    function handleModelClick(model: AIModelMetadata) {
        dispatch('openSettings', {
            settingsPath: `ai/model/${model.id}`,
            direction: 'forward',
            icon: 'ai',
            title: model.name
        });
    }

    let sortOptions = $derived([
        { value: 'performance', label: $text('settings.ai_ask.ai_ask_settings.sort_by_performance') },
        { value: 'price',       label: $text('settings.ai_ask.ai_ask_settings.sort_by_price') },
        { value: 'new',         label: $text('settings.ai_ask.ai_ask_settings.sort_by_new') },
    ]);

    // ─── Settings & Memories section ─────────────────────────────────────

    let storeState = $state(appSkillsStore.getState());
    let aiApp = $derived<AppMetadata | undefined>(storeState.apps['ai']);
    let memoryFields = $derived(aiApp?.settings_and_memories || []);

    onMount(async () => {
        if (!isAuthenticated) return;
        try {
            await appSettingsMemoriesStore.loadEntriesForApp('ai');
        } catch (err) {
            console.error('[SettingsAI] Error loading AI memories:', err);
        }
    });

    // ─── Available providers section ─────────────────────────────────────
    // Collect unique server providers from all AI Ask models.
    // Each server entry has: id, name, region (EU/US/global).

    interface ServerProvider {
        id: string;
        name: string;
        region: string;
        logoSvg: string;
    }

    let serverProviders = $derived.by((): ServerProvider[] => {
        const seen = new Set<string>();
        const providers: ServerProvider[] = [];
        for (const model of aiAskModels) {
            for (const server of model.servers ?? []) {
                if (seen.has(server.id)) continue;
                seen.add(server.id);
                // Try to find a logo for this server provider in providersMetadata
                const providerMeta = providersMetadata[server.id];
                providers.push({
                    id: server.id,
                    name: server.name,
                    region: server.region,
                    logoSvg: providerMeta?.logo_svg ?? '',
                });
            }
        }
        // Sort EU providers first, then alphabetically
        providers.sort((a, b) => {
            if (a.region === 'EU' && b.region !== 'EU') return -1;
            if (a.region !== 'EU' && b.region === 'EU') return 1;
            return a.name.localeCompare(b.name);
        });
        return providers;
    });

    /** User's globally disabled server provider IDs */
    let disabledProviders = $derived<string[]>($userProfile.disabled_ai_providers || []);

    function isProviderEnabled(providerId: string): boolean {
        return !disabledProviders.includes(providerId);
    }

    function handleProviderToggle(providerId: string) {
        const isCurrentlyEnabled = isProviderEnabled(providerId);
        const newDisabled = isCurrentlyEnabled
            ? [...disabledProviders, providerId]
            : disabledProviders.filter(id => id !== providerId);
        updateProfile({ disabled_ai_providers: newDisabled });
    }

    /** Display-friendly region label */
    function getRegionLabel(region: string): string {
        switch (region) {
            case 'EU': return 'EU Server';
            case 'US': return 'US Server';
            case 'global': return 'Global';
            default: return region;
        }
    }

    function handleMemoryCategorySelect(categoryId: string) {
        dispatch('openSettings', {
            settingsPath: `app_store/ai/settings_memories/${categoryId}`,
            direction: 'forward',
            icon: 'ai',
            title: $text(memoryFields.find(c => c.id === categoryId)?.name_translation_key || categoryId)
        });
    }
</script>

<div class="ai-settings" data-testid="ai-settings">
    <!-- 1. Pricing section -->
    <div class="section">
        <SettingsSectionHeading title={$text('common.pricing')} icon="coins" />
        <div class="pricing-content">
            <p class="pricing-label">{$text('settings.ai_ask.ai_ask_settings.pricing_starting_at')}</p>
            <div class="pricing-details">
                <div class="pricing-row">
                    <Icon name="download" type="subsetting" size="24px" noAnimation={true} />
                    <span class="pricing-type">{$text('settings.ai_ask.ai_ask_settings.input_text')}</span>
                    <span class="pricing-value">
                        1 <Icon name="coins" type="default" size="16px" className="credits-icon-inline" noAnimation={true} /> {$text('settings.ai_ask.ai_ask_settings.per')} {cheapestPricing.input} {$text('settings.ai_ask.ai_ask_settings.tokens')}
                    </span>
                </div>
                <div class="pricing-row">
                    <Icon name="coins" type="subsetting" size="24px" noAnimation={true} />
                    <span class="pricing-type">{$text('settings.ai_ask.ai_ask_settings.output_text')}</span>
                    <span class="pricing-value">
                        1 <Icon name="coins" type="default" size="16px" className="credits-icon-inline" noAnimation={true} /> {$text('settings.ai_ask.ai_ask_settings.per')} {cheapestPricing.output} {$text('settings.ai_ask.ai_ask_settings.tokens')}
                    </span>
                </div>
            </div>
            <p class="pricing-note">{$text('settings.ai_ask.ai_ask_settings.pricing_note')}</p>
        </div>
    </div>

    <!-- 2. Default Models section - only for authenticated users -->
    {#if isAuthenticated}
        <div class="section">
            <SettingsSectionHeading title={$text('settings.ai_ask.ai_ask_settings.default_models')} icon="settings" />
            <div class="settings-content">
                <div class="setting-row" data-testid="setting-row">
                    <div class="setting-left">
                        <span class="icon icon_search setting-icon"></span>
                        <span class="setting-label">{$text('settings.ai_ask.ai_ask_settings.auto_select_model')}</span>
                    </div>
                    <div class="setting-right">
                        <div
                            onclick={handleAutoSelectToggle}
                            onkeydown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); handleAutoSelectToggle(); } }}
                            role="button"
                            tabindex="0"
                            style="cursor: pointer;"
                        >
                            <div style="pointer-events: none;">
                                <Toggle
                                    checked={isAutoSelectOn}
                                    ariaLabel={$text('settings.ai_ask.ai_ask_settings.auto_select_model')}
                                />
                            </div>
                        </div>
                    </div>
                </div>
                <p class="setting-description">
                    {$text('settings.ai_ask.ai_ask_settings.auto_select_description')}
                </p>

                {#if !isAutoSelectOn}
                    <div class="default-model-dropdowns">
                        <div class="model-dropdown-row">
                            <label class="model-dropdown-label" for="default-simple-select">
                                {$text('settings.ai_ask.ai_ask_settings.simple_requests')}
                            </label>
                            <select
                                id="default-simple-select"
                                class="model-select"
                                value={defaultSimple ?? ''}
                                onchange={handleSimpleChange}
                            >
                                <option value="">{$text('settings.ai_ask.ai_ask_settings.model_auto')}</option>
                                {#each simpleDropdownModels as model (model.id)}
                                    <option value={modelToValue(model)}>{model.name}</option>
                                {/each}
                            </select>
                        </div>
                        <div class="model-dropdown-row">
                            <label class="model-dropdown-label" for="default-complex-select">
                                {$text('settings.ai_ask.ai_ask_settings.complex_requests')}
                            </label>
                            <select
                                id="default-complex-select"
                                class="model-select"
                                value={defaultComplex ?? ''}
                                onchange={handleComplexChange}
                            >
                                <option value="">{$text('settings.ai_ask.ai_ask_settings.model_auto')}</option>
                                {#each complexDropdownModels as model (model.id)}
                                    <option value={modelToValue(model)}>{model.name}</option>
                                {/each}
                            </select>
                        </div>
                    </div>
                {/if}

                <p class="setting-note">
                    {$text('settings.ai_ask.ai_ask_settings.manual_select_note')}
                </p>
            </div>
        </div>
    {/if}

    <!-- 3. Settings & Memories section - only for authenticated users with AI memories -->
    {#if isAuthenticated && memoryFields.length > 0}
        <div class="section">
            <SettingsSectionHeading title={$text('settings.app_store.settings_memories.title')} icon="settings" />
            <p class="memories-description">{$text('settings.app_store.settings_memories.section_description')}</p>
            <div class="items-scroll-container">
                <div class="items-scroll">
                    {#each memoryFields as category (category.id)}
                        {@const categoryApp: AppMetadata = {
                            id: 'ai',
                            name_translation_key: category.name_translation_key,
                            description_translation_key: category.description_translation_key,
                            icon_image: category.icon_image || aiApp?.icon_image,
                            icon_colorgradient: aiApp?.icon_colorgradient,
                            providers: [],
                            skills: [],
                            focus_modes: [],
                            settings_and_memories: []
                        }}
                        <AppStoreCard
                            app={categoryApp}
                            cardIconType="memory"
                            onSelect={() => handleMemoryCategorySelect(category.id)}
                        />
                    {/each}
                </div>
            </div>
        </div>
    {/if}

    <!-- 4. Available providers section - visible to all, toggles only for authenticated -->
    {#if serverProviders.length > 0}
        <div class="section">
            <SettingsSectionHeading title={$text('settings.ai.available_providers')} icon="server" />
            <p class="providers-description">{$text('settings.ai.available_providers_description')}</p>

            <div class="providers-list">
                {#each serverProviders as provider (provider.id)}
                    {@const enabled = isProviderEnabled(provider.id)}
                    <div class="provider-item" data-testid="provider-item">
                        <div class="provider-icon">
                            {#if provider.logoSvg}
                                <img
                                    src={getProviderIconUrl(provider.logoSvg)}
                                    alt={provider.name}
                                    class="provider-logo"
                                />
                            {:else}
                                <div class="provider-logo-placeholder">
                                    <Icon name="server" type="subsetting" size="24px" noAnimation={true} />
                                </div>
                            {/if}
                        </div>
                        <div class="provider-info">
                            <span class="provider-name">{provider.name}</span>
                            <span class="provider-region">{getRegionLabel(provider.region)}</span>
                        </div>
                        {#if isAuthenticated}
                            <div
                                class="provider-toggle"
                                data-testid="provider-toggle"
                                onclick={() => handleProviderToggle(provider.id)}
                                onkeydown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); handleProviderToggle(provider.id); } }}
                                role="button"
                                tabindex="0"
                            >
                                <div style="pointer-events: none;">
                                    <Toggle
                                        checked={enabled}
                                        ariaLabel={`${enabled ? 'Disable' : 'Enable'} ${provider.name}`}
                                    />
                                </div>
                            </div>
                        {/if}
                    </div>
                {/each}
            </div>
        </div>
    {/if}

    <!-- 5. Available models section -->
    <div class="section">
        <SettingsSectionHeading title={$text('settings.ai_ask.ai_ask_settings.available_models')} icon="ai" />
        <p class="models-description">{$text('settings.ai_ask.ai_ask_settings.models_description')}</p>

        <div class="models-controls">
            <SearchSortBar
                bind:searchQuery
                bind:sortBy
                searchPlaceholder={$text('settings.ai_ask.ai_ask_settings.search_placeholder')}
                {sortOptions}
            />
        </div>

        <div class="models-list">
            {#each filteredModels as model (model.id)}
                {@const enabled = isModelEnabled(model.id)}
                <div
                    class="model-item"
                    data-testid="model-item"
                    class:disabled={!enabled}
                    role="button"
                    tabindex="0"
                    onclick={() => handleModelClick(model)}
                    onkeydown={(e) => e.key === 'Enter' && handleModelClick(model)}
                >
                    <div class="model-icon">
                        <img
                            src={getProviderIconUrl(model.logo_svg)}
                            alt={model.provider_name}
                            class="provider-logo"
                        />
                    </div>
                    <div class="model-info">
                        <span class="model-name" data-testid="model-name">{model.name}</span>
                        <span class="model-provider">{$text('enter_message.mention_dropdown.from_provider').replace('{provider}', model.provider_name)}</span>
                    </div>
                    {#if isAuthenticated}
                        <div
                            class="model-toggle"
                            data-testid="model-toggle"
                            onclick={(e) => { e.stopPropagation(); handleModelToggle(model.id); }}
                            onkeydown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.stopPropagation(); e.preventDefault(); handleModelToggle(model.id); } }}
                            role="button"
                            tabindex="0"
                        >
                            <div style="pointer-events: none;">
                                <Toggle
                                    checked={enabled}
                                    ariaLabel={`${enabled ? 'Disable' : 'Enable'} ${model.name}`}
                                />
                            </div>
                        </div>
                    {/if}
                </div>
            {/each}

            {#if filteredModels.length === 0}
                <div class="no-results">
                    <p>{$text('settings.ai_ask.ai_ask_settings.no_models_found')}</p>
                </div>
            {/if}
        </div>
    </div>
</div>

<style>
    .ai-settings {
        padding: 14px;
        max-width: 1400px;
        margin: 0 auto;
    }

    .section {
        margin-top: 0.5rem;
    }

    /* Pricing section */
    .pricing-content {
        padding: 1rem 0 1rem 10px;
    }

    .pricing-label {
        margin: 0 0 0.5rem 0;
        color: var(--color-grey-60);
        font-size: 0.875rem;
    }

    .pricing-details {
        display: flex;
        flex-direction: column;
        gap: 0.5rem;
        margin-bottom: 1rem;
    }

    .pricing-row {
        display: flex;
        align-items: center;
        gap: 0.75rem;
        padding: 0.5rem 0;
    }

    .pricing-type {
        color: var(--color-grey-60);
        font-size: 0.875rem;
        min-width: 80px;
    }

    .pricing-value {
        display: flex;
        align-items: center;
        gap: 0.25rem;
        color: var(--color-grey-100);
        font-size: 1rem;
        font-weight: 500;
    }

    :global(.credits-icon-inline) {
        display: inline-flex !important;
        vertical-align: middle;
        margin: 0 2px;
    }

    .pricing-note {
        margin: 0;
        color: var(--color-grey-50);
        font-size: 0.875rem;
        font-style: italic;
    }

    /* Settings section */
    .settings-content {
        padding: 1rem 0 1rem 10px;
    }

    .setting-row {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 0.75rem 0;
    }

    .setting-left {
        display: flex;
        align-items: center;
        gap: 0.75rem;
    }

    .setting-icon {
        width: 24px;
        height: 24px;
        color: var(--color-grey-60);
    }

    .setting-label {
        color: var(--color-grey-100);
        font-size: 1rem;
        font-weight: 500;
    }

    .setting-description {
        margin: 0.5rem 0 1rem 0;
        color: var(--color-grey-80);
        font-size: 0.875rem;
        line-height: 1.5;
    }

    .setting-note {
        margin: 0;
        color: var(--color-grey-50);
        font-size: 0.875rem;
        font-style: italic;
    }

    /* Default model dropdowns */
    .default-model-dropdowns {
        display: flex;
        flex-direction: column;
        gap: 1rem;
        margin: 0.75rem 0 0.5rem 0;
    }

    .model-dropdown-row {
        display: flex;
        flex-direction: column;
        gap: 0.375rem;
    }

    .model-dropdown-label {
        font-size: 0.875rem;
        color: var(--color-grey-60);
        font-weight: 500;
    }

    .model-select {
        appearance: none;
        -webkit-appearance: none;
        background-color: var(--color-grey-10);
        border: 1px solid var(--color-grey-20);
        border-radius: var(--radius-3);
        padding: 0.625rem 2rem 0.625rem 0.875rem;
        font-size: 0.9375rem;
        color: var(--color-grey-100);
        cursor: pointer;
        width: 100%;
        background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'%3E%3Cpath fill='%23888' d='M6 8L1 3h10z'/%3E%3C/svg%3E");
        background-repeat: no-repeat;
        background-position: right 0.75rem center;
        transition: border-color var(--duration-fast), background-color var(--duration-fast);
    }

    .model-select:hover {
        border-color: var(--color-grey-40);
    }

    .model-select:focus {
        border-color: var(--color-primary-start);
    }

    :global(.dark) .model-select {
        background-color: var(--color-grey-15);
        border-color: var(--color-grey-25);
        color: var(--color-grey-90);
    }

    :global(.dark) .model-select:hover {
        border-color: var(--color-grey-50);
    }

    /* Models section */
    .models-description {
        margin: 0.5rem 0 1rem 10px;
        color: var(--color-grey-60);
        font-size: 0.875rem;
    }

    .models-controls {
        margin: 0 0 1rem 10px;
    }

    .models-list {
        display: flex;
        flex-direction: column;
        gap: 0;
        margin-left: var(--spacing-5);
    }

    .model-item {
        display: flex;
        align-items: center;
        gap: var(--spacing-6);
        padding: var(--spacing-6) var(--spacing-8);
        border-radius: var(--radius-3);
        cursor: pointer;
        transition: background var(--duration-fast);
    }

    .model-item:hover {
        background: var(--color-grey-10);
    }

    .model-item.disabled {
        opacity: 0.5;
    }

    .model-icon {
        flex-shrink: 0;
        width: 40px;
        height: 40px;
        display: flex;
        align-items: center;
        justify-content: center;
    }

    .provider-logo {
        width: 36px;
        height: 36px;
        border-radius: var(--radius-3);
        object-fit: contain;
        background: var(--color-grey-10);
        padding: var(--spacing-2);
    }

    .model-info {
        flex: 1;
        min-width: 0;
        display: flex;
        flex-direction: column;
        gap: var(--spacing-1);
    }

    .model-name {
        font-size: 1rem;
        font-weight: 500;
        color: var(--color-primary-start);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }

    .model-provider {
        font-size: 0.875rem;
        color: var(--color-grey-60);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }

    .model-toggle {
        flex-shrink: 0;
    }

    .no-results {
        padding: 2rem;
        text-align: center;
    }

    .no-results p {
        margin: 0;
        color: var(--color-grey-50);
        font-size: 0.875rem;
    }

    /* Available providers section */
    .providers-description {
        margin: 0.35rem 0 1rem 0;
        padding: 0;
        font-size: 0.875rem;
        line-height: 1.5;
        color: var(--color-grey-60);
    }

    .providers-list {
        display: flex;
        flex-direction: column;
        gap: 0;
        margin-left: var(--spacing-5);
    }

    .provider-item {
        display: flex;
        align-items: center;
        gap: var(--spacing-6);
        padding: var(--spacing-6) var(--spacing-8);
        border-radius: var(--radius-3);
    }

    .provider-icon {
        flex-shrink: 0;
        width: 40px;
        height: 40px;
        display: flex;
        align-items: center;
        justify-content: center;
    }

    .provider-logo-placeholder {
        width: 36px;
        height: 36px;
        border-radius: var(--radius-3);
        background: var(--color-grey-10);
        display: flex;
        align-items: center;
        justify-content: center;
    }

    .provider-info {
        flex: 1;
        min-width: 0;
        display: flex;
        flex-direction: column;
        gap: var(--spacing-1);
    }

    .provider-name {
        font-size: 1rem;
        font-weight: 500;
        color: var(--color-primary-start);
    }

    .provider-region {
        font-size: 0.875rem;
        color: var(--color-grey-60);
    }

    .provider-toggle {
        flex-shrink: 0;
    }

    /* Settings & Memories section */
    .memories-description {
        margin: 0.35rem 0 0.5rem 0;
        padding: 0;
        font-size: 0.9rem;
        line-height: 1.5;
        color: var(--color-font-secondary);
    }

    .items-scroll-container {
        overflow-x: auto;
        overflow-y: hidden;
        -webkit-overflow-scrolling: touch;
        scrollbar-width: none;
        margin-top: 0.5rem;
    }

    .items-scroll-container::-webkit-scrollbar {
        display: none;
    }

    .items-scroll {
        display: flex;
        gap: var(--spacing-6);
        padding: 4px 0;
    }

    /* Dark mode overrides */
    :global(.dark) .model-item:hover {
        background: var(--color-grey-15);
    }

    :global(.dark) .provider-logo {
        background: var(--color-grey-20);
    }
</style>
