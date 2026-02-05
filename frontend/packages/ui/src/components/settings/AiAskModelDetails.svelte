<!-- frontend/packages/ui/src/components/settings/AiAskModelDetails.svelte
     
     Model details page for a specific AI model within the AI Ask skill.
     Shows:
     - Model name and provider
     - Description
     - Release date
     - Supported input/output types
     - Available servers with region information
     - Pricing details
     - Toggle to enable/disable the model
     
     **Data Flow**:
     - Model metadata from modelsMetadata.ts (generated at build time)
     - User preferences from userProfile store (disabled_ai_models, disabled_ai_servers)
     - Changes auto-save by updating userProfile store
-->

<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import { text } from '@repo/ui';
    import { authStore } from '../../stores/authStore';
    import { userProfile, updateProfile } from '../../stores/userProfile';
    import { modelsMetadata, type AIModelMetadata } from '../../data/modelsMetadata';
    import { getProviderIconUrl } from '../../data/providerIcons';
    import SettingsItem from '../SettingsItem.svelte';
    import Toggle from '../Toggle.svelte';
    import Icon from '../Icon.svelte';
    
    const dispatch = createEventDispatcher();
    
    // --- Auth state ---
    let isAuthenticated = $derived($authStore.isAuthenticated);
    
    interface Props {
        modelId: string;
    }
    
    let { modelId }: Props = $props();
    
    // Get model metadata
    let model = $derived<AIModelMetadata | undefined>(
        modelsMetadata.find(m => m.id === modelId)
    );
    
    // Get user's disabled models and servers
    let disabledModels = $derived($userProfile.disabled_ai_models || []);
    let disabledServers = $derived($userProfile.disabled_ai_servers || {});
    
    // Check if model is enabled
    let isModelEnabled = $derived(!disabledModels.includes(modelId));
    
    // Format release date for display
    let formattedReleaseDate = $derived.by(() => {
        if (!model?.release_date) return null;
        try {
            const date = new Date(model.release_date);
            return date.toLocaleDateString(undefined, { 
                year: 'numeric', 
                month: 'long', 
                day: 'numeric' 
            });
        } catch {
            return model.release_date;
        }
    });
    
    // Get tier display label
    let tierLabel = $derived.by(() => {
        if (!model) return '';
        switch (model.tier) {
            case 'economy': return $text('settings.ai_ask.ai_ask_model_details.tier_economy.text');
            case 'standard': return $text('settings.ai_ask.ai_ask_model_details.tier_standard.text');
            case 'premium': return $text('settings.ai_ask.ai_ask_model_details.tier_premium.text');
            default: return model.tier;
        }
    });
    
    // Get tier CSS class for styling
    let tierClass = $derived(model?.tier || 'standard');
    
    // Format input types for display
    let inputTypesDisplay = $derived.by(() => {
        if (!model?.input_types) return '';
        return model.input_types.map(type => {
            switch (type) {
                case 'text': return $text('settings.ai_ask.ai_ask_model_details.input_type_text.text');
                case 'image': return $text('settings.ai_ask.ai_ask_model_details.input_type_image.text');
                case 'video': return $text('settings.ai_ask.ai_ask_model_details.input_type_video.text');
                case 'audio': return $text('settings.ai_ask.ai_ask_model_details.input_type_audio.text');
                default: return type;
            }
        }).join(', ');
    });
    
    // Format output types for display
    let outputTypesDisplay = $derived.by(() => {
        if (!model?.output_types) return '';
        return model.output_types.map(type => {
            switch (type) {
                case 'text': return $text('settings.ai_ask.ai_ask_model_details.output_type_text.text');
                case 'image': return $text('settings.ai_ask.ai_ask_model_details.output_type_image.text');
                default: return type;
            }
        }).join(', ');
    });
    
    // --- Functions ---
    
    function isServerEnabled(serverId: string): boolean {
        // Check if this server is disabled for this model
        const modelDisabledServers = disabledServers[modelId] || [];
        return !modelDisabledServers.includes(serverId);
    }
    
    function handleModelToggle() {
        const currentDisabled = [...disabledModels];
        
        let newDisabled: string[];
        if (isModelEnabled) {
            // Disable the model
            newDisabled = [...currentDisabled, modelId];
        } else {
            // Enable the model
            newDisabled = currentDisabled.filter(id => id !== modelId);
        }
        
        // Auto-save: update cache first, then Directus via store
        updateProfile({ disabled_ai_models: newDisabled });
    }
    
    function handleServerToggle(serverId: string) {
        // Get current disabled servers for this model
        const currentModelDisabled = disabledServers[modelId] || [];
        const isCurrentlyEnabled = isServerEnabled(serverId);
        
        let newModelDisabled: string[];
        if (isCurrentlyEnabled) {
            // Disable the server
            newModelDisabled = [...currentModelDisabled, serverId];
        } else {
            // Enable the server
            newModelDisabled = currentModelDisabled.filter(id => id !== serverId);
        }
        
        // Update the full disabled servers record
        const newDisabledServers = { ...disabledServers };
        if (newModelDisabled.length > 0) {
            newDisabledServers[modelId] = newModelDisabled;
        } else {
            // Remove the model key if no servers are disabled
            delete newDisabledServers[modelId];
        }
        
        // Auto-save: update cache first, then Directus via store
        updateProfile({ disabled_ai_servers: newDisabledServers });
    }
    
    function goBack() {
        // Navigate back to AI Ask skill settings page
        dispatch('openSettings', {
            settingsPath: 'app_store/ai/skill/ask',
            direction: 'back',
            icon: 'ai',
            title: 'Ask' // Simple title - the breadcrumb will show the full path
        });
    }
    
    // Get flag emoji for country code
    function getCountryFlag(countryCode: string): string {
        if (!countryCode || countryCode.length !== 2) return '';
        const codePoints = countryCode
            .toUpperCase()
            .split('')
            .map(char => 127397 + char.charCodeAt(0));
        return String.fromCodePoint(...codePoints);
    }
    
    // Get region display with flag
    function getRegionDisplay(region: 'EU' | 'US' | 'APAC'): string {
        switch (region) {
            case 'EU': return '🇪🇺 EU';
            case 'US': return '🇺🇸 US';
            case 'APAC': return '🌏 APAC';
            default: return region;
        }
    }
    
    // Get provider icon name from server ID
    function getProviderIconName(serverId: string): string {
        // Map server IDs to icon names
        const serverIconMap: Record<string, string> = {
            'google': 'google',
            'google_ai_studio': 'google',
            'aws_bedrock': 'amazon',
            'anthropic': 'anthropic',
            'openai': 'openai',
            'mistral': 'mistral',
            'openrouter': 'openrouter',
            'cerebras': 'cerebras',
            'groq': 'groq',
            'fal': 'fal'
        };
        return serverIconMap[serverId] || 'server';
    }
</script>

<div class="model-details">
    {#if !model}
        <div class="error">
            <p>{$text('settings.ai_ask.ai_ask_model_details.model_not_found.text')}</p>
            <button class="back-button" onclick={goBack}>← {$text('settings.ai_ask.ai_ask_model_details.back_to_models.text')}</button>
        </div>
    {:else}
        <!-- Model header with logo, name, and main toggle -->
        <div class="model-header">
            <div class="model-icon">
                <img 
                    src={getProviderIconUrl(model.logo_svg)} 
                    alt={model.provider_name}
                    class="provider-logo"
                />
            </div>
            <div class="model-title-section">
                <h1 class="model-name">{model.name}</h1>
                <span class="model-provider">{$text('enter_message.mention_dropdown.from_provider.text').replace('{provider}', model.provider_name)}</span>
            </div>
            {#if isAuthenticated}
                <div 
                    class="model-toggle"
                    onclick={handleModelToggle}
                    onkeydown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); handleModelToggle(); } }}
                    role="button"
                    tabindex="0"
                >
                    <Toggle 
                        checked={isModelEnabled}
                        ariaLabel={`${isModelEnabled ? 'Disable' : 'Enable'} ${model.name}`}
                    />
                </div>
            {/if}
        </div>
        
        <!-- Description -->
        <div class="description-section">
            <p class="model-description">{model.description}</p>
        </div>
        
        <!-- Model info section -->
        <div class="section">
            <SettingsItem 
                type="heading"
                icon="icon_info"
                title={$text('settings.ai_ask.ai_ask_model_details.model_info.text')}
            />
            <div class="info-content">
                <!-- Origin -->
                <div class="info-row">
                    <span class="info-label">{$text('settings.ai_ask.ai_ask_model_details.origin.text')}</span>
                    <span class="info-value">
                        <span class="country-flag">{getCountryFlag(model.country_origin)}</span>
                        {model.provider_name}
                    </span>
                </div>
                
                <!-- Release date -->
                {#if formattedReleaseDate}
                    <div class="info-row">
                        <span class="info-label">{$text('settings.ai_ask.ai_ask_model_details.release_date.text')}</span>
                        <span class="info-value">{formattedReleaseDate}</span>
                    </div>
                {/if}
                
                <!-- Tier -->
                <div class="info-row">
                    <span class="info-label">{$text('settings.ai_ask.ai_ask_model_details.tier.text')}</span>
                    <span class="info-value">
                        <span class="tier-badge tier-{tierClass}">{tierLabel}</span>
                    </span>
                </div>
                
                <!-- Reasoning model badge -->
                {#if model.reasoning}
                    <div class="info-row">
                        <span class="info-label">{$text('settings.ai_ask.ai_ask_model_details.type.text')}</span>
                        <span class="info-value">
                            <span class="reasoning-badge">{$text('settings.ai_ask.ai_ask_model_details.reasoning_model.text')}</span>
                        </span>
                    </div>
                {/if}
                
                <!-- Input types -->
                <div class="info-row">
                    <span class="info-label">{$text('settings.ai_ask.ai_ask_model_details.input_types.text')}</span>
                    <span class="info-value">{inputTypesDisplay}</span>
                </div>
                
                <!-- Output types -->
                <div class="info-row">
                    <span class="info-label">{$text('settings.ai_ask.ai_ask_model_details.output_types.text')}</span>
                    <span class="info-value">{outputTypesDisplay}</span>
                </div>
            </div>
        </div>
        
        <!-- Pricing section -->
        {#if model.pricing}
            <div class="section">
                <SettingsItem 
                    type="heading"
                    icon="credits"
                    title={$text('settings.ai_ask.ai_ask_model_details.pricing.text')}
                />
                <div class="pricing-content">
                    {#if model.pricing.input_tokens_per_credit}
                        <div class="pricing-row">
                            <Icon name="credits" type="subsetting" size="24px" noAnimation={true} />
                            <span class="pricing-type">{$text('settings.ai_ask.ai_ask_model_details.text_input.text')}</span>
                            <span class="pricing-value">
                                1 <Icon name="coins" type="default" size="16px" className="credits-icon-inline" noAnimation={true} /> {$text('settings.ai_ask.ai_ask_settings.per.text')} {model.pricing.input_tokens_per_credit} {$text('settings.ai_ask.ai_ask_settings.tokens.text')}
                            </span>
                        </div>
                    {/if}
                    {#if model.pricing.output_tokens_per_credit}
                        <div class="pricing-row">
                            <Icon name="credits" type="subsetting" size="24px" noAnimation={true} />
                            <span class="pricing-type">{$text('settings.ai_ask.ai_ask_model_details.text_output.text')}</span>
                            <span class="pricing-value">
                                1 <Icon name="coins" type="default" size="16px" className="credits-icon-inline" noAnimation={true} /> {$text('settings.ai_ask.ai_ask_settings.per.text')} {model.pricing.output_tokens_per_credit} {$text('settings.ai_ask.ai_ask_settings.tokens.text')}
                            </span>
                        </div>
                    {/if}
                </div>
            </div>
        {/if}
        
        <!-- Provider section -->
        {#if model.servers && model.servers.length > 0}
            <div class="section">
                <SettingsItem 
                    type="heading"
                    icon="server"
                    title={$text('settings.ai_ask.ai_ask_model_details.provider.text')}
                />
                
                <div class="provider-list">
                    {#each model.servers as server (server.id)}
                        {@const serverEnabled = isServerEnabled(server.id)}
                        <div 
                            class="provider-item"
                            class:disabled={!serverEnabled}
                        >
                            <div class="provider-icon-wrapper">
                                <Icon name={getProviderIconName(server.id)} type="provider" size="32px" noAnimation={true} />
                            </div>
                            <div class="provider-info">
                                <span class="provider-name">{server.name}</span>
                                <span class="provider-region">{getRegionDisplay(server.region)} {$text('settings.ai_ask.ai_ask_model_details.servers.text').toLowerCase()}</span>
                            </div>
                            {#if isAuthenticated}
                                <div 
                                    class="provider-toggle"
                                    onclick={() => handleServerToggle(server.id)}
                                    onkeydown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); handleServerToggle(server.id); } }}
                                    role="button"
                                    tabindex="0"
                                >
                                    <Toggle 
                                        checked={serverEnabled}
                                        ariaLabel={`${serverEnabled ? 'Disable' : 'Enable'} ${server.name}`}
                                    />
                                </div>
                            {/if}
                        </div>
                    {/each}
                </div>
            </div>
        {/if}
    {/if}
</div>

<style>
    .model-details {
        padding: 14px;
        max-width: 1400px;
        margin: 0 auto;
    }
    
    /* Model header */
    .model-header {
        display: flex;
        align-items: center;
        gap: 16px;
        padding-bottom: 1.5rem;
        border-bottom: 1px solid var(--color-grey-20);
    }
    
    .model-icon {
        flex-shrink: 0;
        width: 64px;
        height: 64px;
        display: flex;
        align-items: center;
        justify-content: center;
    }
    
    .provider-logo {
        width: 56px;
        height: 56px;
        border-radius: 12px;
        object-fit: contain;
        background: var(--color-grey-10);
        padding: 8px;
    }
    
    .model-title-section {
        flex: 1;
        min-width: 0;
    }
    
    .model-name {
        margin: 0;
        font-size: 1.5rem;
        font-weight: 600;
        color: var(--color-primary-start);
        line-height: 1.2;
    }
    
    .model-provider {
        font-size: 0.9rem;
        color: var(--color-grey-60);
    }
    
    .model-toggle {
        flex-shrink: 0;
    }
    
    /* Description */
    .description-section {
        margin: 1.5rem 0;
    }
    
    .model-description {
        margin: 0;
        color: var(--color-grey-100);
        font-size: 1rem;
        line-height: 1.6;
    }
    
    /* Sections */
    .section {
        margin-top: 2rem;
    }
    
    /* Info content */
    .info-content {
        padding: 1rem 0 1rem 10px;
    }
    
    .info-row {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 0.75rem 0;
        border-bottom: 1px solid var(--color-grey-15);
    }
    
    .info-row:last-child {
        border-bottom: none;
    }
    
    .info-label {
        color: var(--color-grey-60);
        font-size: 0.9rem;
    }
    
    .info-value {
        color: var(--color-grey-100);
        font-size: 0.9rem;
        font-weight: 500;
        display: flex;
        align-items: center;
        gap: 0.5rem;
    }
    
    .country-flag {
        font-size: 1.25rem;
    }
    
    /* Tier badge */
    .tier-badge {
        display: inline-block;
        padding: 0.25rem 0.75rem;
        border-radius: 12px;
        font-size: 0.8rem;
        font-weight: 500;
        text-transform: capitalize;
    }
    
    .tier-economy {
        background: var(--color-green-10, #e8f5e9);
        color: var(--color-green-80, #2e7d32);
    }
    
    .tier-standard {
        background: var(--color-blue-10, #e3f2fd);
        color: var(--color-blue-80, #1565c0);
    }
    
    .tier-premium {
        background: var(--color-purple-10, #f3e5f5);
        color: var(--color-purple-80, #7b1fa2);
    }
    
    /* Reasoning badge */
    .reasoning-badge {
        display: inline-block;
        padding: 0.25rem 0.75rem;
        border-radius: 12px;
        font-size: 0.8rem;
        font-weight: 500;
        background: var(--color-orange-10, #fff3e0);
        color: var(--color-orange-80, #e65100);
    }
    
    /* Pricing content */
    .pricing-content {
        padding: 1rem 0 1rem 10px;
    }
    
    .pricing-row {
        display: flex;
        align-items: center;
        gap: 0.5rem;
        padding: 0.5rem 0;
    }
    
    .pricing-type {
        color: var(--color-grey-60);
        font-size: 0.9rem;
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
    
    /* Provider section */
    .provider-list {
        display: flex;
        flex-direction: column;
        gap: 0;
        margin-left: 10px;
    }
    
    .provider-item {
        display: flex;
        align-items: center;
        gap: 12px;
        padding: 12px 16px;
        border-radius: 8px;
        transition: background 0.15s;
    }
    
    .provider-item:hover {
        background: var(--color-grey-10);
    }
    
    .provider-item.disabled {
        opacity: 0.5;
    }
    
    .provider-icon-wrapper {
        flex-shrink: 0;
        width: 32px;
        height: 32px;
        display: flex;
        align-items: center;
        justify-content: center;
    }
    
    .provider-info {
        flex: 1;
        min-width: 0;
        display: flex;
        flex-direction: column;
        gap: 2px;
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
    
    /* Error state */
    .error {
        padding: 3rem;
        text-align: center;
        color: var(--error-color, #dc3545);
    }
    
    .back-button {
        background: var(--button-background, #f0f0f0);
        border: 1px solid var(--border-color, #e0e0e0);
        border-radius: 6px;
        padding: 0.5rem 1rem;
        margin-top: 1rem;
        cursor: pointer;
        font-size: 0.9rem;
        color: var(--text-primary, #000000);
        transition: background 0.2s ease;
    }
    
    .back-button:hover {
        background: var(--button-hover-background, #e0e0e0);
    }
    
    /* Dark mode */
    :global(.dark) .provider-logo {
        background: var(--color-grey-20);
    }
    
    :global(.dark) .provider-item:hover {
        background: var(--color-grey-15);
    }
    
    :global(.dark) .tier-economy {
        background: var(--color-green-20, #1b5e20);
        color: var(--color-green-90, #a5d6a7);
    }
    
    :global(.dark) .tier-standard {
        background: var(--color-blue-20, #0d47a1);
        color: var(--color-blue-90, #90caf9);
    }
    
    :global(.dark) .tier-premium {
        background: var(--color-purple-20, #4a148c);
        color: var(--color-purple-90, #ce93d8);
    }
    
    :global(.dark) .reasoning-badge {
        background: var(--color-orange-20, #bf360c);
        color: var(--color-orange-90, #ffcc80);
    }
    
    /* Responsive */
    @media (max-width: 600px) {
        .model-header {
            flex-wrap: wrap;
        }
        
        .model-title-section {
            flex: 1 1 calc(100% - 96px);
        }
        
        .model-toggle {
            margin-left: auto;
        }
        
        .info-row {
            flex-direction: column;
            align-items: flex-start;
            gap: 0.25rem;
        }
        
        .pricing-row {
            flex-direction: column;
            align-items: flex-start;
            gap: 0.25rem;
        }
        
        .pricing-type {
            min-width: auto;
        }
    }
</style>
