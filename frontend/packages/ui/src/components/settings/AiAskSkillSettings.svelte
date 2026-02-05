<!-- frontend/packages/ui/src/components/settings/AiAskSkillSettings.svelte
     
     AI Ask skill settings page for configuring available models.
     Shows:
     - Description of the skill
     - Pricing (starting at cheapest model)
     - Auto-select toggle (disabled/greyed out - feature coming later)
     - Available models list with search and sort
     
     **Data Flow**:
     - Model metadata from modelsMetadata.ts (generated at build time)
     - User preferences from userProfile store (disabled_ai_models, disabled_ai_servers)
     - Changes auto-save by updating userProfile store
-->

<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import { text } from '@repo/ui';
    import { userProfile, updateProfile } from '../../stores/userProfile';
    import { modelsMetadata, type AIModelMetadata } from '../../data/modelsMetadata';
    import { getProviderIconUrl } from '../../data/providerIcons';
    import SettingsItem from '../SettingsItem.svelte';
    import Toggle from '../Toggle.svelte';
    
    const dispatch = createEventDispatcher();
    
    // --- State ---
    let searchQuery = $state('');
    let sortBy = $state<'price' | 'performance' | 'new'>('performance');
    let showSortDropdown = $state(false);
    
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
    
    function handleSortChange(newSort: 'price' | 'performance' | 'new') {
        sortBy = newSort;
        showSortDropdown = false;
    }
    
    function toggleSortDropdown() {
        showSortDropdown = !showSortDropdown;
    }
    
    function closeSortDropdown() {
        showSortDropdown = false;
    }
    
    // Get sort label for current sort
    let sortLabel = $derived({
        price: $text('ai_ask_settings.sort_by_price.text'),
        performance: $text('ai_ask_settings.sort_by_performance.text'),
        new: $text('ai_ask_settings.sort_by_new.text')
    }[sortBy]);
</script>

<div class="ai-ask-settings">
    <!-- Description section -->
    <div class="description-section">
        <p class="skill-description">{$text('ai.ask.description.text')}</p>
    </div>
    
    <!-- Pricing section -->
    <div class="section">
        <SettingsItem 
            type="heading"
            icon="icon_credits"
            title={$text('ai_ask_settings.pricing.text')}
        />
        <div class="pricing-content">
            <p class="pricing-label">{$text('ai_ask_settings.pricing_starting_at.text')}</p>
            <div class="pricing-details">
                <div class="pricing-row">
                    <span class="pricing-type">{$text('ai_ask_settings.input_text.text')}</span>
                    <span class="pricing-value">
                        1 <span class="icon icon_credits credits-icon"></span> {$text('ai_ask_settings.per.text')} {cheapestPricing.input} {$text('ai_ask_settings.tokens.text')}
                    </span>
                </div>
                <div class="pricing-row">
                    <span class="pricing-type">{$text('ai_ask_settings.output_text.text')}</span>
                    <span class="pricing-value">
                        1 <span class="icon icon_credits credits-icon"></span> {$text('ai_ask_settings.per.text')} {cheapestPricing.output} {$text('ai_ask_settings.tokens.text')}
                    </span>
                </div>
            </div>
            <p class="pricing-note">{$text('ai_ask_settings.pricing_note.text')}</p>
        </div>
    </div>
    
    <!-- Settings section -->
    <div class="section">
        <SettingsItem 
            type="heading"
            icon="icon_settings"
            title={$text('ai_ask_settings.settings.text')}
        />
        <div class="settings-content">
            <div class="setting-row">
                <div class="setting-left">
                    <span class="icon icon_search setting-icon"></span>
                    <span class="setting-label">{$text('ai_ask_settings.auto_select_model.text')}</span>
                </div>
                <div class="setting-right">
                    <Toggle 
                        checked={true}
                        disabled={true}
                        ariaLabel={$text('ai_ask_settings.auto_select_model.text')}
                    />
                </div>
            </div>
            <p class="setting-description">
                <strong>{$text('ai_ask_settings.auto_select_model.text')}</strong><br/>
                {$text('ai_ask_settings.auto_select_description.text')}
            </p>
            <p class="setting-note">
                {$text('ai_ask_settings.manual_select_note.text')}
            </p>
        </div>
    </div>
    
    <!-- Available models section -->
    <div class="section">
        <SettingsItem 
            type="heading"
            icon="icon_search"
            title={$text('ai_ask_settings.available_models.text')}
        />
        <p class="models-description">{$text('ai_ask_settings.models_description.text')}</p>
        
        <!-- Search and sort controls -->
        <div class="models-controls">
            <div class="search-container">
                <span class="icon icon_search search-icon"></span>
                <input 
                    type="text" 
                    class="search-input"
                    placeholder={$text('ai_ask_settings.search_placeholder.text')}
                    bind:value={searchQuery}
                />
            </div>
            <div class="sort-container">
                <button 
                    class="sort-button"
                    onclick={toggleSortDropdown}
                    aria-expanded={showSortDropdown}
                >
                    <span class="icon icon_sort sort-icon"></span>
                    <span class="sort-label">{sortLabel}</span>
                </button>
                {#if showSortDropdown}
                    <div class="sort-dropdown" role="menu">
                        <button 
                            class="sort-option" 
                            class:active={sortBy === 'price'}
                            onclick={() => handleSortChange('price')}
                            role="menuitem"
                        >
                            {$text('ai_ask_settings.sort_by_price.text')}
                        </button>
                        <button 
                            class="sort-option"
                            class:active={sortBy === 'performance'}
                            onclick={() => handleSortChange('performance')}
                            role="menuitem"
                        >
                            {$text('ai_ask_settings.sort_by_performance.text')}
                        </button>
                        <button 
                            class="sort-option"
                            class:active={sortBy === 'new'}
                            onclick={() => handleSortChange('new')}
                            role="menuitem"
                        >
                            {$text('ai_ask_settings.sort_by_new.text')}
                        </button>
                    </div>
                    <!-- Backdrop to close dropdown when clicking outside -->
                    <button 
                        class="sort-backdrop" 
                        onclick={closeSortDropdown}
                        aria-label="Close sort menu"
                    ></button>
                {/if}
            </div>
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
                        <span class="model-provider">{$text('enter_message.mention_dropdown.from_provider.text').replace('{provider}', model.provider_name)}</span>
                    </div>
                    <div 
                        class="model-toggle"
                        onclick={(e) => { e.stopPropagation(); handleModelToggle(model.id); }}
                        onkeydown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.stopPropagation(); e.preventDefault(); handleModelToggle(model.id); } }}
                        role="button"
                        tabindex="0"
                    >
                        <Toggle 
                            checked={enabled}
                            ariaLabel={`${enabled ? 'Disable' : 'Enable'} ${model.name}`}
                        />
                    </div>
                </div>
            {/each}
            
            {#if filteredModels.length === 0}
                <div class="no-results">
                    <p>{$text('ai_ask_settings.no_models_found.text')}</p>
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
        gap: 0.5rem;
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
    
    .credits-icon {
        width: 16px;
        height: 16px;
        display: inline-block;
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
    
    /* Models section */
    .models-description {
        margin: 0.5rem 0 1rem 10px;
        color: var(--color-grey-60);
        font-size: 0.875rem;
    }
    
    .models-controls {
        display: flex;
        gap: 1rem;
        margin: 0 0 1rem 10px;
    }
    
    .search-container {
        flex: 1;
        position: relative;
        display: flex;
        align-items: center;
    }
    
    .search-icon {
        position: absolute;
        left: 12px;
        width: 18px;
        height: 18px;
        color: var(--color-grey-50);
        pointer-events: none;
    }
    
    .search-input {
        width: 100%;
        padding: 0.625rem 0.75rem 0.625rem 40px;
        font-size: 0.875rem;
        border: 1px solid var(--color-grey-20);
        border-radius: 8px;
        background: var(--color-grey-10);
        color: var(--color-grey-100);
        transition: border-color 0.2s, background 0.2s;
    }
    
    .search-input:focus {
        outline: none;
        border-color: var(--color-primary);
        background: var(--color-background);
    }
    
    .search-input::placeholder {
        color: var(--color-grey-50);
    }
    
    .sort-container {
        position: relative;
    }
    
    .sort-button {
        display: flex;
        align-items: center;
        gap: 0.5rem;
        padding: 0.625rem 1rem;
        font-size: 0.875rem;
        border: 1px solid var(--color-grey-20);
        border-radius: 8px;
        background: var(--color-grey-10);
        color: var(--color-grey-80);
        cursor: pointer;
        transition: border-color 0.2s, background 0.2s;
    }
    
    .sort-button:hover {
        border-color: var(--color-grey-40);
        background: var(--color-grey-15);
    }
    
    .sort-icon {
        width: 16px;
        height: 16px;
    }
    
    .sort-dropdown {
        position: absolute;
        top: 100%;
        right: 0;
        margin-top: 4px;
        min-width: 150px;
        background: var(--color-grey-blue);
        border: 1px solid var(--color-grey-20);
        border-radius: 8px;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
        z-index: 100;
        overflow: hidden;
    }
    
    .sort-option {
        display: block;
        width: 100%;
        padding: 0.75rem 1rem;
        font-size: 0.875rem;
        text-align: left;
        background: transparent;
        border: none;
        color: var(--color-grey-80);
        cursor: pointer;
        transition: background 0.15s;
    }
    
    .sort-option:hover {
        background: var(--color-grey-15);
    }
    
    .sort-option.active {
        color: var(--color-primary);
        font-weight: 500;
    }
    
    .sort-backdrop {
        position: fixed;
        inset: 0;
        background: transparent;
        border: none;
        cursor: default;
        z-index: 99;
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
    
    /* Dark mode */
    :global(.dark) .search-input {
        background: var(--color-grey-15);
        border-color: var(--color-grey-30);
    }
    
    :global(.dark) .search-input:focus {
        background: var(--color-grey-10);
    }
    
    :global(.dark) .sort-button {
        background: var(--color-grey-15);
        border-color: var(--color-grey-30);
    }
    
    :global(.dark) .sort-dropdown {
        background: var(--color-grey-10);
        border-color: var(--color-grey-30);
    }
    
    :global(.dark) .model-item:hover {
        background: var(--color-grey-15);
    }
    
    :global(.dark) .provider-logo {
        background: var(--color-grey-20);
    }
    
    /* Responsive */
    @media (max-width: 600px) {
        .models-controls {
            flex-direction: column;
        }
        
        .sort-dropdown {
            right: auto;
            left: 0;
        }
    }
</style>
