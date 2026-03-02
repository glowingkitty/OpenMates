<!-- frontend/packages/ui/src/components/settings/AiAskSkillSettings.svelte
     
     AI Ask skill settings page for configuring available models.
     Shows:
     - Description of the skill
     - Pricing (starting at cheapest model)
     - Default Models section: auto-select toggle + optional simple/complex model dropdowns
     - Available models list with search and sort
     
     **Default Models section**:
     - Auto-select toggle ON (default): both default model preferences are null → auto-selection runs.
     - Toggle OFF: two dropdowns appear ("Simple requests" and "Complex requests").
     - Dropdown options: "Auto" first, then models sorted by tier.
       Simple: economy first, then standard, then premium.
       Complex: premium first, then standard, then economy.
     - Selecting a model: (1) optimistic local update via updateProfile() → IndexedDB,
       (2) server save via POST /v1/settings/ai-model-defaults → Directus + Redis cache.
       On server failure, notify the user via notificationStore.error().
     - Priority: @mention override > user default model > ModelSelector auto-selection.
     
     **Data Flow**:
     - Model metadata from modelsMetadata.ts (generated at build time)
     - User preferences from userProfile store (disabled_ai_models, disabled_ai_servers,
       default_ai_model_simple, default_ai_model_complex)
     - Changes auto-save by updating userProfile store + backend via REST
-->

<script lang="ts">
    import { createEventDispatcher, onDestroy } from 'svelte';
    import { text } from '@repo/ui';
    import { authStore } from '../../stores/authStore';
    import { userProfile, updateProfile } from '../../stores/userProfile';
    import { modelsMetadata, type AIModelMetadata } from '../../data/modelsMetadata';
    import { getProviderIconUrl } from '../../data/providerIcons';
    import SettingsItem from '../SettingsItem.svelte';
    import Toggle from '../Toggle.svelte';
    import Icon from '../Icon.svelte';
    import SearchSortBar from './SearchSortBar.svelte';
    import { setAppStoreNavList, clearAppStoreNav } from '../../stores/appStoreNavigationStore';
    import { appSkillsStore } from '../../stores/appSkillsStore';
    import { notificationStore } from '../../stores/notificationStore';
    import { getApiUrl, apiEndpoints } from '../../config/api';
    
    const dispatch = createEventDispatcher();
    
    // --- Auth state ---
    let isAuthenticated = $derived($authStore.isAuthenticated);

    // ─── Sibling skill navigation ─────────────────────────────────────────────
    //
    // Register the AI app's full skill list so AppDetailsHeader can show prev/next
    // arrows when the user opens the AI Ask skill page (app_store/ai/skill/ask).
    // The navigate callback uses the special 'ai/ask' route for this skill and the
    // standard skill route for all other AI skills.
    $effect(() => {
        const aiApp = appSkillsStore.getState().apps['ai'];
        const skills = aiApp?.skills ?? [];
        if (skills.length > 1) {
            setAppStoreNavList(
                skills.map(s => ({
                    id: s.id,
                    name: s.name_translation_key ? $text(s.name_translation_key) : s.id,
                })),
                'ask',
                (targetSkillId) => {
                    // The AI Ask skill has its own special route; all other AI skills use the generic route
                    const path =
                        targetSkillId === 'ask'
                            ? 'app_store/ai/skill/ask'
                            : `app_store/ai/skill/${targetSkillId}`;
                    dispatch('openSettings', {
                        settingsPath: path,
                        direction: 'forward',
                        icon: 'ai',
                        title: aiApp?.name_translation_key ? $text(aiApp.name_translation_key) : 'ai',
                    });
                },
            );
        } else {
            clearAppStoreNav();
        }
    });

    onDestroy(() => {
        clearAppStoreNav();
    });

    // --- State ---
    let searchQuery = $state('');
    let sortBy = $state<'price' | 'performance' | 'new'>('performance');

    // ─── Default Models section ──────────────────────────────────────────────
    //
    // "Auto-select" is ON when both default preferences are null/undefined.
    // When toggled OFF, the two dropdowns become visible and each defaults to "Auto" (null).
    // The format stored/sent is "provider/model_id" (e.g., "anthropic/claude-haiku-4-5-20251001").

    // Read current defaults from profile — null/undefined both mean "Auto"
    let defaultSimple = $derived($userProfile.default_ai_model_simple ?? null);
    let defaultComplex = $derived($userProfile.default_ai_model_complex ?? null);

    // Auto-select is ON when BOTH defaults are null (no overrides set)
    let autoSelectEnabled = $derived(defaultSimple === null && defaultComplex === null);

    // Ordered lists of ai.ask models for each dropdown
    // Simple dropdown: economy first, then standard, then premium (cheapest models first)
    let simpleDropdownModels = $derived.by(() => {
        const tierOrder: Record<string, number> = { economy: 1, standard: 2, premium: 3 };
        return modelsMetadata
            .filter(m => m.for_app_skill === 'ai.ask')
            .sort((a, b) => (tierOrder[a.tier] ?? 2) - (tierOrder[b.tier] ?? 2) || a.name.localeCompare(b.name));
    });

    // Complex dropdown: premium first, then standard, then economy (best models first)
    let complexDropdownModels = $derived.by(() => {
        const tierOrder: Record<string, number> = { premium: 1, standard: 2, economy: 3 };
        return modelsMetadata
            .filter(m => m.for_app_skill === 'ai.ask')
            .sort((a, b) => (tierOrder[a.tier] ?? 2) - (tierOrder[b.tier] ?? 2) || a.name.localeCompare(b.name));
    });

    /**
     * Build the "provider/model_id" string for a model entry.
     * The provider_id in modelsMetadata corresponds to the backend provider identifier.
     */
    function modelToValue(model: AIModelMetadata): string {
        return `${model.provider_id}/${model.id}`;
    }

    /**
     * Save default model preferences to IndexedDB (optimistic) + backend (async).
     * On backend failure: show error notification — no rollback (local is already saved).
     */
    async function saveDefaultModels(
        newSimple: string | null,
        newComplex: string | null
    ): Promise<void> {
        // Optimistic local update
        updateProfile({
            default_ai_model_simple: newSimple,
            default_ai_model_complex: newComplex,
        });

        // Persist to server for cross-device sync
        try {
            const response = await fetch(getApiUrl() + apiEndpoints.settings.aiModelDefaults, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Accept': 'application/json',
                },
                body: JSON.stringify({
                    default_ai_model_simple: newSimple,
                    default_ai_model_complex: newComplex,
                }),
                credentials: 'include',
            });

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                console.error(
                    `[AiAskSettings] Failed to save default models: ` +
                    `${response.status} – ${errorData?.detail ?? 'unknown error'}`
                );
                notificationStore.error($text('settings.ai_ask.ai_ask_settings.default_models_save_error'));
            } else {
                console.debug('[AiAskSettings] Default models saved successfully.');
            }
        } catch (err) {
            console.error('[AiAskSettings] Network error while saving default models:', err);
            notificationStore.error($text('settings.ai_ask.ai_ask_settings.default_models_save_error'));
        }
    }

    /** Toggle the "Auto-select model" switch. */
    async function handleAutoSelectToggle(): Promise<void> {
        if (autoSelectEnabled) {
            // Turning OFF auto-select: both dropdowns now show, both start at "Auto" (null)
            // No-op: defaults are already null and the toggle UI will flip to show dropdowns.
            // We do want to persist null→null explicitly so other devices reflect the intent.
            await saveDefaultModels(null, null);
        } else {
            // Turning ON auto-select: reset both defaults to null
            await saveDefaultModels(null, null);
        }
    }

    /** Called when the Simple Requests dropdown changes. */
    async function handleSimpleChange(event: Event): Promise<void> {
        const select = event.target as HTMLSelectElement;
        const value = select.value === '' ? null : select.value;
        await saveDefaultModels(value, defaultComplex);
    }

    /** Called when the Complex Requests dropdown changes. */
    async function handleComplexChange(event: Event): Promise<void> {
        const select = event.target as HTMLSelectElement;
        const value = select.value === '' ? null : select.value;
        await saveDefaultModels(defaultSimple, value);
    }

    // Get AI Ask models only
    let aiAskModels = $derived(
        modelsMetadata.filter(model => model.for_app_skill === 'ai.ask')
    );
    
    // Get user's disabled models
    let disabledModels = $derived($userProfile.disabled_ai_models || []);
    
    // Filtered and sorted models
    let filteredModels = $derived.by(() => {
        let models = [...aiAskModels];
        
        // Filter by search query
        if (searchQuery.trim()) {
            const query = searchQuery.toLowerCase();
            models = models.filter(model => 
                model.name.toLowerCase().includes(query) ||
                model.provider_name.toLowerCase().includes(query) ||
                model.description.toLowerCase().includes(query)
            );
        }
        
        // Sort models
        models.sort((a, b) => {
            switch (sortBy) {
                case 'price': {
                    // Sort by cheapest (highest tokens per credit = cheapest)
                    const aPriceScore = (a.pricing?.input_tokens_per_credit || 0) + (a.pricing?.output_tokens_per_credit || 0);
                    const bPriceScore = (b.pricing?.input_tokens_per_credit || 0) + (b.pricing?.output_tokens_per_credit || 0);
                    return bPriceScore - aPriceScore; // Higher is cheaper
                }
                case 'performance': {
                    // Sort by tier (premium > standard > economy) and name
                    const tierOrder = { premium: 3, standard: 2, economy: 1 };
                    const tierDiff = tierOrder[b.tier] - tierOrder[a.tier];
                    if (tierDiff !== 0) return tierDiff;
                    return a.name.localeCompare(b.name);
                }
                case 'new': {
                    // Sort by release date (newest first)
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
    
    // Calculate cheapest pricing for "Starting at" display
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
        
        return {
            input: maxInputTokens,
            output: maxOutputTokens
        };
    });
    
    // --- Functions ---
    
    function isModelEnabled(modelId: string): boolean {
        return !disabledModels.includes(modelId);
    }
    
    function handleModelToggle(modelId: string) {
        const currentDisabled = [...disabledModels];
        const isCurrentlyEnabled = isModelEnabled(modelId);
        
        let newDisabled: string[];
        if (isCurrentlyEnabled) {
            // Disable the model
            newDisabled = [...currentDisabled, modelId];
        } else {
            // Enable the model
            newDisabled = currentDisabled.filter(id => id !== modelId);
        }
        
        // Auto-save: update cache first, then Directus via store
        updateProfile({ disabled_ai_models: newDisabled });
    }
    
    function handleModelClick(model: AIModelMetadata) {
        // Navigate to model details page
        dispatch('openSettings', {
            settingsPath: `app_store/ai/skill/ask/model/${model.id}`,
            direction: 'forward',
            icon: 'ai',
            title: model.name
        });
    }
    
    // --- Derived sort options (reactive to language changes) ---
    let sortOptions = $derived([
        { value: 'performance', label: $text('settings.ai_ask.ai_ask_settings.sort_by_performance') },
        { value: 'price',       label: $text('settings.ai_ask.ai_ask_settings.sort_by_price') },
        { value: 'new',         label: $text('settings.ai_ask.ai_ask_settings.sort_by_new') },
    ]);
</script>

<div class="ai-ask-settings">
    <!-- Description section -->
    <div class="description-section">
        <p class="skill-description">{$text('settings.ai_ask.ai_ask_settings.description')}</p>
    </div>
    
    <!-- Pricing section -->
    <div class="section">
        <SettingsItem 
            type="heading"
            icon="coins"
            title={$text('settings.ai_ask.ai_ask_settings.pricing')}
        />
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
    
    <!-- Default Models section - only for authenticated users -->
    {#if isAuthenticated}
        <div class="section">
            <SettingsItem 
                type="heading"
                icon="icon_settings"
                title={$text('settings.ai_ask.ai_ask_settings.default_models')}
            />
            <div class="settings-content">
                <!-- Auto-select toggle -->
                <div class="setting-row">
                    <div class="setting-left">
                        <span class="icon icon_search setting-icon"></span>
                        <span class="setting-label">{$text('settings.ai_ask.ai_ask_settings.auto_select_model')}</span>
                    </div>
                    <div class="setting-right">
                        <!-- pointer-events:none wrapper prevents double-toggle on click -->
                        <div
                            onclick={handleAutoSelectToggle}
                            onkeydown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); handleAutoSelectToggle(); } }}
                            role="button"
                            tabindex="0"
                            style="cursor: pointer;"
                        >
                            <div style="pointer-events: none;">
                                <Toggle 
                                    checked={autoSelectEnabled}
                                    ariaLabel={$text('settings.ai_ask.ai_ask_settings.auto_select_model')}
                                />
                            </div>
                        </div>
                    </div>
                </div>
                <p class="setting-description">
                    {$text('settings.ai_ask.ai_ask_settings.auto_select_description')}
                </p>

                <!-- Default model dropdowns — shown only when auto-select is OFF -->
                {#if !autoSelectEnabled}
                    <div class="default-model-dropdowns">
                        <!-- Simple requests dropdown -->
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

                        <!-- Complex requests dropdown -->
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
    
    <!-- Available models section -->
    <div class="section">
        <SettingsItem 
            type="heading"
            icon="skill"
            title={$text('settings.ai_ask.ai_ask_settings.available_models')}
        />
        <p class="models-description">{$text('settings.ai_ask.ai_ask_settings.models_description')}</p>
        
        <!-- Search and sort controls — shared SearchSortBar component -->
        <div class="models-controls">
            <SearchSortBar
                bind:searchQuery
                bind:sortBy
                searchPlaceholder={$text('settings.ai_ask.ai_ask_settings.search_placeholder')}
                {sortOptions}
            />
        </div>
        
        <!-- Models list -->
        <div class="models-list">
            {#each filteredModels as model (model.id)}
                {@const enabled = isModelEnabled(model.id)}
                <div 
                    class="model-item"
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
                        <span class="model-name">{model.name}</span>
                        <span class="model-provider">{$text('enter_message.mention_dropdown.from_provider').replace('{provider}', model.provider_name)}</span>
                    </div>
                    {#if isAuthenticated}
                        <div 
                            class="model-toggle"
                            onclick={(e) => { e.stopPropagation(); handleModelToggle(model.id); }}
                            onkeydown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.stopPropagation(); e.preventDefault(); handleModelToggle(model.id); } }}
                            role="button"
                            tabindex="0"
                        >
                            <!-- pointer-events:none prevents the checkbox from independently toggling 
                                 via bind:checked when clicked — the wrapper div handles the toggle logic 
                                 through handleModelToggle() to avoid a double-toggle (no visual change) bug -->
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
    .ai-ask-settings {
        padding: 14px;
        max-width: 1400px;
        margin: 0 auto;
    }
    
    .description-section {
        margin-bottom: 2rem;
    }
    
    .skill-description {
        margin: 0;
        color: var(--color-grey-100);
        font-size: 1rem;
        line-height: 1.6;
    }
    
    .section {
        margin-top: 2rem;
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
    
    /* Inline credits icon for pricing display */
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
        border-radius: 8px;
        padding: 0.625rem 2rem 0.625rem 0.875rem;
        font-size: 0.9375rem;
        color: var(--color-grey-100);
        cursor: pointer;
        width: 100%;
        background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'%3E%3Cpath fill='%23888' d='M6 8L1 3h10z'/%3E%3C/svg%3E");
        background-repeat: no-repeat;
        background-position: right 0.75rem center;
        transition: border-color 0.15s, background-color 0.15s;
    }

    .model-select:hover {
        border-color: var(--color-grey-40);
    }

    .model-select:focus {
        outline: none;
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
    
    /* SearchSortBar is a self-contained component — its styles live in SearchSortBar.svelte */
    .models-controls {
        margin: 0 0 1rem 10px;
    }

    /* Models list */
    .models-list {
        display: flex;
        flex-direction: column;
        gap: 0;
        margin-left: 10px;
    }
    
    .model-item {
        display: flex;
        align-items: center;
        gap: 12px;
        padding: 12px 16px;
        border-radius: 8px;
        cursor: pointer;
        transition: background 0.15s;
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
        border-radius: 8px;
        object-fit: contain;
        background: var(--color-grey-10);
        padding: 4px;
    }
    
    .model-info {
        flex: 1;
        min-width: 0;
        display: flex;
        flex-direction: column;
        gap: 2px;
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
    
    /* Dark mode overrides for model list items */
    :global(.dark) .model-item:hover {
        background: var(--color-grey-15);
    }
    
    :global(.dark) .provider-logo {
        background: var(--color-grey-20);
    }
</style>
