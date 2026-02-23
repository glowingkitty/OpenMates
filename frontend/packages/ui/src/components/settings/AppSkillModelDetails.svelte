<!-- frontend/packages/ui/src/components/settings/AppSkillModelDetails.svelte

     Generic model detail page for app skills that support multiple models
     (e.g., images.generate, images.generate_draft, audio.transcribe).
     
     Shows:
     - Model name, provider logo, and description
     - Release date, tier, input/output types
     - Pricing (per-image, per-megapixel, per-minute, or per-token depending on model)
     - Available servers/providers
     
     **Data Flow**:
     - Model metadata from modelsMetadata.ts (generated at build time)
     - App/skill metadata from appsMetadata.ts (for back-navigation)
     
     **Routing**:
     - app_store/{app_id}/skill/{skill_id}/model/{model_id}
     - Back navigates to app_store/{app_id}/skill/{skill_id}
-->

<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import { text } from '@repo/ui';
    import { modelsMetadata, type AIModelMetadata } from '../../data/modelsMetadata';
    import { appSkillsStore } from '../../stores/appSkillsStore';
    import { getProviderIconUrl } from '../../data/providerIcons';
    import SettingsItem from '../SettingsItem.svelte';
    import Icon from '../Icon.svelte';
    
    const dispatch = createEventDispatcher();
    
    interface Props {
        appId: string;
        skillId: string;
        modelId: string;
    }
    
    let { appId, skillId, modelId }: Props = $props();
    
    // Get app/skill metadata for back navigation title
    let storeState = $state(appSkillsStore.getState());
    let app = $derived(storeState.apps[appId]);
    let skill = $derived(app?.skills.find(s => s.id === skillId));
    
    // Get model metadata
    let model = $derived<AIModelMetadata | undefined>(
        modelsMetadata.find(m => m.id === modelId)
    );
    
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
            case 'economy': return $text('settings.app_store.skills.model_detail.tier_economy');
            case 'standard': return $text('settings.app_store.skills.model_detail.tier_standard');
            case 'premium': return $text('settings.app_store.skills.model_detail.tier_premium');
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
                case 'text': return $text('settings.ai_ask.ai_ask_model_details.input_type_text');
                case 'image': return $text('settings.ai_ask.ai_ask_model_details.input_type_image');
                case 'video': return $text('settings.ai_ask.ai_ask_model_details.input_type_video');
                case 'audio': return $text('settings.ai_ask.ai_ask_model_details.input_type_audio');
                default: return type;
            }
        }).join(', ');
    });
    
    // Format output types for display
    let outputTypesDisplay = $derived.by(() => {
        if (!model?.output_types) return '';
        return model.output_types.map(type => {
            switch (type) {
                case 'text': return $text('settings.ai_ask.ai_ask_model_details.output_type_text');
                case 'image': return $text('settings.ai_ask.ai_ask_model_details.output_type_image');
                default: return type;
            }
        }).join(', ');
    });
    
    /**
     * Get flag emoji for country code (e.g. "US" → "🇺🇸").
     */
    function getCountryFlag(countryCode: string): string {
        if (!countryCode || countryCode.length !== 2) return '';
        const codePoints = countryCode
            .toUpperCase()
            .split('')
            .map(char => 127397 + char.charCodeAt(0));
        return String.fromCodePoint(...codePoints);
    }
    
    /**
     * Get region label with flag emoji for display.
     */
    function getRegionDisplay(region: 'EU' | 'US' | 'APAC'): string {
        switch (region) {
            case 'EU': return '🇪🇺 EU';
            case 'US': return '🇺🇸 US';
            case 'APAC': return '🌏 APAC';
            default: return region;
        }
    }
    
    /**
     * Get provider icon name from server ID for use with the Icon component.
     * Maps known server IDs to icon names; falls back to 'server'.
     */
    function getProviderIconName(serverId: string): string {
        const serverIconMap: Record<string, string> = {
            'google': 'google',
            'google_ai_studio': 'google',
            'google_maas': 'google',
            'aws_bedrock': 'amazon',
            'anthropic': 'anthropic',
            'openai': 'openai',
            'mistral': 'mistral',
            'openrouter': 'openrouter',
            'cerebras': 'cerebras',
            'groq': 'groq',
            'fal': 'fal',
            'recraft': 'recraft',
            'bfl': 'bfl',
            'together': 'together'
        };
        return serverIconMap[serverId] || 'server';
    }
    
    /**
     * Get the icon name from the app's icon_image filename for back-navigation.
     */
    function getIconName(iconImage: string | undefined): string {
        if (!iconImage) return appId;
        let iconName = iconImage.replace(/\.svg$/, '');
        if (iconName === 'coding') iconName = 'code';
        // Handle special case: heart.svg -> health (app ID is "health", icon file is heart.svg)
        if (iconName === 'heart') iconName = 'health';
        return iconName;
    }
    
    /**
     * Navigate back to the skill details page.
     */
    function goBack() {
        dispatch('openSettings', {
            settingsPath: `app_store/${appId}/skill/${skillId}`,
            direction: 'back',
            icon: getIconName(app?.icon_image),
            title: skill?.name_translation_key ? $text(skill.name_translation_key) : skillId
        });
    }
</script>

<div class="model-details">
    {#if !model}
        <div class="error">
            <p>{$text('settings.app_store.skills.model_detail.model_not_found')}</p>
            <button class="back-button" onclick={goBack}>← {$text('settings.app_store.back_to_app')}</button>
        </div>
    {:else}
        <!-- Description -->
        <div class="description-section">
            <p class="model-description">{model.description}</p>
        </div>
        
        <!-- Model info section -->
        <div class="section">
            <SettingsItem
                type="heading"
                icon="icon_info"
                title={$text('settings.app_store.skills.model_detail.model_info')}
            />
            <div class="info-content">
                <!-- Origin -->
                <div class="info-row">
                    <span class="info-label">{$text('settings.app_store.skills.model_detail.origin')}</span>
                    <span class="info-value">
                        <span class="country-flag">{getCountryFlag(model.country_origin)}</span>
                        {model.provider_name}
                    </span>
                </div>
                
                <!-- Release date -->
                {#if formattedReleaseDate}
                    <div class="info-row">
                        <span class="info-label">{$text('settings.app_store.skills.model_detail.release_date')}</span>
                        <span class="info-value">{formattedReleaseDate}</span>
                    </div>
                {/if}
                
                <!-- Tier -->
                <div class="info-row">
                    <span class="info-label">{$text('settings.app_store.skills.model_detail.tier')}</span>
                    <span class="info-value">
                        <span class="tier-badge tier-{tierClass}">{tierLabel}</span>
                    </span>
                </div>
                
                <!-- Input types -->
                {#if inputTypesDisplay}
                    <div class="info-row">
                        <span class="info-label">{$text('settings.app_store.skills.model_detail.input_types')}</span>
                        <span class="info-value">{inputTypesDisplay}</span>
                    </div>
                {/if}
                
                <!-- Output types -->
                {#if outputTypesDisplay}
                    <div class="info-row">
                        <span class="info-label">{$text('settings.app_store.skills.model_detail.output_types')}</span>
                        <span class="info-value">{outputTypesDisplay}</span>
                    </div>
                {/if}
            </div>
        </div>
        
        <!-- Pricing section -->
        <!-- Priority order:
             1. Model-level token pricing (AI text models: input/output tokens per credit)
             2. Model-level unit pricing (image/audio models: per_unit or per_minute from modelsMetadata)
             3. Skill-level pricing fallback (per_unit/per_minute from appsMetadata, for edge cases
                where the model has no pricing data of its own) -->
        {#if model.pricing?.input_tokens_per_credit || model.pricing?.output_tokens_per_credit}
            <!-- Token-based pricing (AI text models) -->
            <div class="section">
                <SettingsItem
                    type="heading"
                    icon="credits"
                    title={$text('settings.app_store.skills.model_detail.pricing')}
                />
                <div class="pricing-content">
                    {#if model.pricing?.input_tokens_per_credit}
                        <div class="pricing-row">
                            <Icon name="credits" type="subsetting" size="24px" noAnimation={true} />
                            <span class="pricing-type">{$text('settings.ai_ask.ai_ask_model_details.text_input')}</span>
                            <span class="pricing-value">
                                1 <Icon name="coins" type="default" size="16px" className="credits-icon-inline" noAnimation={true} /> {$text('settings.ai_ask.ai_ask_settings.per')} {model.pricing.input_tokens_per_credit} {$text('settings.ai_ask.ai_ask_settings.tokens')}
                            </span>
                        </div>
                    {/if}
                    {#if model.pricing?.output_tokens_per_credit}
                        <div class="pricing-row">
                            <Icon name="credits" type="subsetting" size="24px" noAnimation={true} />
                            <span class="pricing-type">{$text('settings.ai_ask.ai_ask_model_details.text_output')}</span>
                            <span class="pricing-value">
                                1 <Icon name="coins" type="default" size="16px" className="credits-icon-inline" noAnimation={true} /> {$text('settings.ai_ask.ai_ask_settings.per')} {model.pricing.output_tokens_per_credit} {$text('settings.ai_ask.ai_ask_settings.tokens')}
                            </span>
                        </div>
                    {/if}
                </div>
            </div>
        {:else if model.pricing?.per_unit || model.pricing?.per_minute !== undefined}
            <!-- Per-unit / per-minute pricing from model metadata (image/audio models) -->
            <div class="section">
                <SettingsItem
                    type="heading"
                    icon="credits"
                    title={$text('settings.app_store.skills.model_detail.pricing')}
                />
                <div class="pricing-content">
                    {#if model.pricing?.per_unit}
                        <div class="pricing-row">
                            <Icon name="credits" type="subsetting" size="24px" noAnimation={true} />
                            <span class="pricing-value">
                                {model.pricing.per_unit.credits} <Icon name="coins" type="default" size="16px" className="credits-icon-inline" noAnimation={true} />
                                {model.pricing.per_unit.unit_name === 'image'
                                    ? $text('settings.app_store.skills.model_detail.per_image')
                                    : model.pricing.per_unit.unit_name === 'megapixel'
                                    ? $text('settings.app_store.skills.model_detail.per_megapixel')
                                    : `/ ${model.pricing.per_unit.unit_name}`}
                            </span>
                        </div>
                    {:else if model.pricing?.per_minute !== undefined}
                        <div class="pricing-row">
                            <Icon name="credits" type="subsetting" size="24px" noAnimation={true} />
                            <span class="pricing-value">
                                {model.pricing.per_minute} <Icon name="coins" type="default" size="16px" className="credits-icon-inline" noAnimation={true} />
                                {$text('settings.app_store.skills.model_detail.per_minute')}
                            </span>
                        </div>
                    {/if}
                </div>
            </div>
        {:else if skill?.pricing}
            <!-- Fallback: skill-level pricing when the model itself has no pricing data -->
            <div class="section">
                <SettingsItem
                    type="heading"
                    icon="credits"
                    title={$text('settings.app_store.skills.model_detail.pricing')}
                />
                <div class="pricing-content">
                    {#if skill.pricing.per_unit}
                        <div class="pricing-row">
                            <Icon name="credits" type="subsetting" size="24px" noAnimation={true} />
                            <span class="pricing-value">
                                {skill.pricing.per_unit.credits} <Icon name="coins" type="default" size="16px" className="credits-icon-inline" noAnimation={true} />
                                {skill.pricing.per_unit.unit_name === 'image'
                                    ? $text('settings.app_store.skills.model_detail.per_image')
                                    : skill.pricing.per_unit.unit_name === 'megapixel'
                                    ? $text('settings.app_store.skills.model_detail.per_megapixel')
                                    : `/ ${skill.pricing.per_unit.unit_name}`}
                            </span>
                        </div>
                    {:else if skill.pricing.per_minute !== undefined}
                        <div class="pricing-row">
                            <Icon name="credits" type="subsetting" size="24px" noAnimation={true} />
                            <span class="pricing-value">
                                {skill.pricing.per_minute} <Icon name="coins" type="default" size="16px" className="credits-icon-inline" noAnimation={true} />
                                {$text('settings.app_store.skills.model_detail.per_minute')}
                            </span>
                        </div>
                    {:else if skill.pricing.fixed !== undefined}
                        <div class="pricing-row">
                            <Icon name="credits" type="subsetting" size="24px" noAnimation={true} />
                            <span class="pricing-value">
                                {skill.pricing.fixed} <Icon name="coins" type="default" size="16px" className="credits-icon-inline" noAnimation={true} /> {$text('settings.app_store.skills.pricing.credits')}
                            </span>
                        </div>
                    {/if}
                </div>
            </div>
        {/if}
        
        <!-- Provider / Servers section -->
        {#if model.servers && model.servers.length > 0}
            <div class="section">
                <SettingsItem
                    type="heading"
                    icon="server"
                    title={$text('settings.app_store.skills.model_detail.provider')}
                />
                <div class="provider-list">
                    {#each model.servers as server (server.id)}
                        <div class="provider-item">
                            <div class="provider-icon-wrapper">
                                <Icon name={getProviderIconName(server.id)} type="provider" size="32px" noAnimation={true} />
                            </div>
                            <div class="provider-info">
                                <span class="provider-name">{server.name}</span>
                                <span class="provider-region">{getRegionDisplay(server.region)} {$text('settings.app_store.skills.model_detail.servers').toLowerCase()}</span>
                            </div>
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
    
    /* Description */
    .description-section {
        margin: 0.5rem 0 1.5rem;
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
    
    /* Tier badges */
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
    
    /* Pricing */
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
    
    /* Inline credits icon for pricing display (global so it works in nested context) */
    :global(.credits-icon-inline) {
        display: inline-flex !important;
        vertical-align: middle;
        margin: 0 2px;
    }
    
    /* Provider / Servers section */
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
    
    /* Responsive */
    @media (max-width: 600px) {
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
