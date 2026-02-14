<!-- frontend/packages/ui/src/components/settings/SkillDetails.svelte
     Component for displaying details of a specific skill, including description, providers, and pricing.
     
     This component is used for the app_store/{app_id}/skill/{skill_id} nested route.
     
     **Backend Implementation**:
     - Data source: Static appsMetadata.ts (generated at build time)
     - Store: frontend/packages/ui/src/stores/appSkillsStore.ts
     - Types: frontend/packages/ui/src/types/apps.ts
-->

<script lang="ts">
    import { appSkillsStore } from '../../stores/appSkillsStore';
    import SettingsItem from '../SettingsItem.svelte';
    import type { AppMetadata, SkillMetadata, SkillPricing } from '../../types/apps';
    import { createEventDispatcher } from 'svelte';
    import { text } from '@repo/ui';
    
    // Create event dispatcher for navigation
    const dispatch = createEventDispatcher();
    
    interface Props {
        appId: string;
        skillId: string;
    }
    
    let { appId, skillId }: Props = $props();
    
    // Get store state reactively (Svelte 5)
    let storeState = $state(appSkillsStore.getState());
    
    // Get app and skill metadata from store
    let app = $derived<AppMetadata | undefined>(storeState.apps[appId]);
    let skill = $derived<SkillMetadata | undefined>(
        app?.skills.find(s => s.id === skillId)
    );
    
    /**
     * Get the translated skill description.
     */
    let skillDescription = $derived(
        skill?.description_translation_key 
            ? $text(skill.description_translation_key)
            : ''
    );
    
    /**
     * Format pricing information for display.
     * Returns an array of strings for token pricing (to display on separate lines),
     * or a single string for other pricing types.
     */
    function formatPricing(pricing: SkillPricing | undefined): string | string[] {
        // Never show "Free" - if no pricing provided, default to 1 credit minimum
        // This should not happen in practice since metadata generation always sets pricing
        if (!pricing) {
            return `1 ${$text('settings.app_store.skills.pricing.credits')} per request`;
        }
        
        // Token-based pricing - return array for separate lines
        // per_credit_unit means "tokens per credit" (e.g., 700 means 700 tokens per 1 credit)
        if (pricing.tokens) {
            const tokenParts: string[] = [];
            if (pricing.tokens.input) {
                tokenParts.push(`${pricing.tokens.input.per_credit_unit} ${$text('settings.app_store.skills.pricing.token')} per ${$text('settings.app_store.skills.pricing.credits')} (${$text('settings.app_store.skills.pricing.input')})`);
            }
            if (pricing.tokens.output) {
                tokenParts.push(`${pricing.tokens.output.per_credit_unit} ${$text('settings.app_store.skills.pricing.token')} per ${$text('settings.app_store.skills.pricing.credits')} (${$text('settings.app_store.skills.pricing.output')})`);
            }
            if (tokenParts.length > 0) {
                return tokenParts;
            }
        }
        
        // Other pricing types - return single string
        const parts: string[] = [];
        
        // Fixed pricing - default to "per request" if no unit specified
        if (pricing.fixed !== undefined) {
            parts.push(`${pricing.fixed} ${$text('settings.app_store.skills.pricing.credits')} per request`);
        }
        
        // Per unit pricing
        if (pricing.per_unit) {
            const unitName = pricing.per_unit.unit_name || $text('settings.app_store.skills.pricing.unit');
            parts.push(`${pricing.per_unit.credits} ${$text('settings.app_store.skills.pricing.credits')} / ${unitName}`);
        }
        
        // Per minute pricing
        if (pricing.per_minute !== undefined) {
            parts.push(`${pricing.per_minute} ${$text('settings.app_store.skills.pricing.credits')} / ${$text('settings.app_store.skills.pricing.minute')}`);
        }
        
        return parts.length > 0 ? parts.join(', ') : $text('settings.app_store.skills.pricing.free');
    }
    
    /**
     * Get formatted pricing for display.
     * Returns either a string or array of strings (for token pricing).
     */
    let formattedPricing = $derived(formatPricing(skill?.pricing));
    
    /**
     * Get "How to use" example instructions for this skill.
     * Derives translation keys from the skill's name_translation_key by appending .how_to_use.{1|2|3}.
     * Only includes examples where a translation exists (key doesn't resolve to itself).
     */
    let howToUseExamples = $derived.by(() => {
        if (!skill?.name_translation_key) return [];
        const examples: string[] = [];
        for (let i = 1; i <= 3; i++) {
            const key = `${skill.name_translation_key}.how_to_use.${i}`;
            const translated = $text(key);
            // Only add if translation exists (not returning the key itself)
            if (translated && translated !== key) {
                examples.push(translated);
            }
        }
        return examples;
    });
    
    /**
     * Get icon name from icon_image filename.
     * Maps icon_image like "ai.svg" to icon name "ai" for the Icon component.
     * Also handles special cases:
     * - "coding.svg" -> "code" (since the app ID is "code" but icon file is coding.svg)
     */
    function getIconName(iconImage: string | undefined): string {
        if (!iconImage) return appId;
        let iconName = iconImage.replace(/\.svg$/, '');
        // Handle special case: coding.svg -> code (since the app ID is "code" but icon file is coding.svg)
        // This ensures the correct CSS variable --color-app-code is used instead of --color-app-coding
        if (iconName === 'coding') {
            iconName = 'code';
        }
        return iconName;
    }
    
    /**
     * Navigate back to app details.
     */
    function goBack() {
        dispatch('openSettings', {
            settingsPath: `app_store/${appId}`,
            direction: 'back',
            icon: getIconName(app?.icon_image),
            title: app?.name_translation_key ? $text(app.name_translation_key) : appId
        });
    }
</script>

<div class="skill-details">
    {#if !app || !skill}
        <div class="error">
            <p>{$text('settings.app_store.skill_not_found')}</p>
            <button class="back-button" onclick={goBack}>← {$text('settings.app_store.back_to_app')}</button>
        </div>
    {:else}
        <!-- Description section - no header, just show description directly -->
        {#if skillDescription}
            <div class="description-section">
                <p class="skill-description">{skillDescription}</p>
            </div>
        {/if}
        
        <!-- How to use section - horizontal scrollable example instructions -->
        {#if howToUseExamples.length > 0}
            <div class="section how-to-use-section">
                <SettingsItem 
                    type="heading"
                    icon="skill"
                    title={$text('settings.app_store.skills.how_to_use')}
                />
                <div class="how-to-use-scroll-container">
                    <div class="how-to-use-scroll">
                        {#each howToUseExamples as example}
                            <div class="how-to-use-card">
                                <svg class="quote-icon" width="20" height="20" viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
                                    <path d="M15 3a6 6 0 016 6v17.997c0 9.389-4.95 15.577-14.271 17.908a3.001 3.001 0 01-3.717-3.35 3 3 0 012.259-2.47C11.952 37.416 15 33.606 15 26.998v-3H6a6 6 0 01-5.985-5.549L0 17.998V9A5.999 5.999 0 016 3h9zm27 0a6 6 0 016 6v17.997c0 9.389-4.95 15.577-14.271 17.908a3.001 3.001 0 01-3.716-3.35 2.998 2.998 0 012.258-2.47C38.952 37.416 42 33.606 42 26.998v-3h-9a6 6 0 01-5.985-5.549l-.015-.45V9A5.999 5.999 0 0133 3h9z" fill="currentColor"/>
                                </svg>
                                <p class="how-to-use-text">{example}</p>
                            </div>
                        {/each}
                    </div>
                </div>
            </div>
        {/if}
        
        <!-- Providers section -->
        {#if skill.providers && skill.providers.length > 0}
            <div class="section">
                <SettingsItem 
                    type="heading"
                    icon="provider"
                    title={$text('settings.app_store.skills.providers')}
                />
                <div class="content">
                    <ul class="providers-list">
                        {#each skill.providers as provider}
                            <li>{provider}</li>
                        {/each}
                    </ul>
                </div>
            </div>
        {/if}
        
        <!-- Pricing section - always show, even if free -->
        <div class="section">
            <SettingsItem 
                type="heading"
                icon="credits"
                title={$text('settings.app_store.skills.pricing')}
            />
            <div class="content">
                {#if Array.isArray(formattedPricing)}
                    <!-- Token pricing: display each line separately -->
                    {#each formattedPricing as pricingLine}
                        <p class="pricing">{pricingLine}</p>
                    {/each}
                {:else}
                    <!-- Other pricing types: single line -->
                    <p class="pricing">{formattedPricing}</p>
                {/if}
            </div>
        </div>
    {/if}
</div>

<style>
    .skill-details {
        padding: 14px;
        max-width: 1400px;
        margin: 0 auto;
    }
    
    /* Description section - no header, just description text */
    .description-section {
        margin-bottom: 2rem;
        padding-left: 0;
    }
    
    .skill-description {
        margin: 0;
        color: var(--color-grey-100);
        font-size: 1rem;
        line-height: 1.6;
        text-align: left;
    }
    
    .section {
        margin-top: 2rem;
    }
    
    .content {
        padding: 1rem 0 1rem 10px;
        color: var(--color-grey-100);
        font-size: 1rem;
        line-height: 1.6;
    }
    
    .providers-list {
        list-style: none;
        padding: 0;
        margin: 0;
    }
    
    .providers-list li {
        padding: 0.5rem 0;
        border-bottom: 1px solid var(--color-grey-20);
    }
    
    .providers-list li:last-child {
        border-bottom: none;
    }
    
    .pricing {
        font-weight: 500;
        color: var(--color-grey-100);
    }
    
    /* How to use section styles */
    .how-to-use-section {
        margin-top: 1.5rem;
    }
    
    .how-to-use-scroll-container {
        overflow-x: auto;
        overflow-y: hidden;
        padding-bottom: 0.5rem;
        margin-top: 0.75rem;
        scrollbar-width: thin;
        scrollbar-color: rgba(128, 128, 128, 0.2) transparent;
        transition: scrollbar-color 0.2s ease;
    }
    
    .how-to-use-scroll-container:hover {
        scrollbar-color: rgba(128, 128, 128, 0.5) transparent;
    }
    
    .how-to-use-scroll-container::-webkit-scrollbar {
        height: 8px;
    }
    
    .how-to-use-scroll-container::-webkit-scrollbar-track {
        background: transparent;
    }
    
    .how-to-use-scroll-container::-webkit-scrollbar-thumb {
        background-color: rgba(128, 128, 128, 0.2);
        border-radius: 4px;
        border: 2px solid var(--color-grey-20);
        transition: background-color 0.2s ease;
    }
    
    .how-to-use-scroll-container:hover::-webkit-scrollbar-thumb {
        background-color: rgba(128, 128, 128, 0.5);
    }
    
    .how-to-use-scroll-container::-webkit-scrollbar-thumb:hover {
        background-color: rgba(128, 128, 128, 0.7);
    }
    
    .how-to-use-scroll {
        display: flex;
        gap: 0.75rem;
        padding-right: 1rem;
        min-width: min-content;
    }
    
    .how-to-use-card {
        flex: 0 0 auto;
        width: 260px;
        padding: 1rem;
        background: var(--color-grey-10);
        border: 1px solid var(--color-grey-20);
        border-radius: 12px;
        display: flex;
        flex-direction: column;
        gap: 0.6rem;
    }
    
    .quote-icon {
        flex-shrink: 0;
        color: var(--color-grey-50);
        opacity: 0.6;
    }
    
    .how-to-use-text {
        margin: 0;
        font-size: 0.9rem;
        line-height: 1.5;
        color: var(--color-grey-100);
        word-break: break-word;
    }

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
</style>

