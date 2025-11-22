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
     * Get the translated skill name.
     */
    let skillName = $derived(
        skill?.name_translation_key 
            ? $text(skill.name_translation_key)
            : skillId
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
     */
    function formatPricing(pricing: SkillPricing | undefined): string {
        if (!pricing) {
            return $text('settings.app_store.skills.pricing.free.text');
        }
        
        const parts: string[] = [];
        
        // Fixed pricing
        if (pricing.fixed !== undefined) {
            parts.push(`${pricing.fixed} ${$text('settings.app_store.skills.pricing.credits.text')}`);
        }
        
        // Per unit pricing
        if (pricing.per_unit) {
            const unitName = pricing.per_unit.unit_name || $text('settings.app_store.skills.pricing.unit.text');
            parts.push(`${pricing.per_unit.credits} ${$text('settings.app_store.skills.pricing.credits.text')} / ${unitName}`);
        }
        
        // Per minute pricing
        if (pricing.per_minute !== undefined) {
            parts.push(`${pricing.per_minute} ${$text('settings.app_store.skills.pricing.credits.text')} / ${$text('settings.app_store.skills.pricing.minute.text')}`);
        }
        
        // Token-based pricing
        if (pricing.tokens) {
            if (pricing.tokens.input) {
                parts.push(`${pricing.tokens.input.per_credit_unit} ${$text('settings.app_store.skills.pricing.credits.text')} / ${$text('settings.app_store.skills.pricing.token.text')} (${$text('settings.app_store.skills.pricing.input.text')})`);
            }
            if (pricing.tokens.output) {
                parts.push(`${pricing.tokens.output.per_credit_unit} ${$text('settings.app_store.skills.pricing.credits.text')} / ${$text('settings.app_store.skills.pricing.token.text')} (${$text('settings.app_store.skills.pricing.output.text')})`);
            }
        }
        
        return parts.length > 0 ? parts.join(', ') : $text('settings.app_store.skills.pricing.free.text');
    }
    
    /**
     * Get icon name from icon_image filename.
     */
    function getIconName(iconImage: string | undefined): string {
        if (!iconImage) return appId;
        return iconImage.replace(/\.svg$/, '');
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
            <p>{$text('settings.app_store.skill_not_found.text')}</p>
            <button class="back-button" onclick={goBack}>← {$text('settings.app_store.back_to_app.text')}</button>
        </div>
    {:else}
        <!-- Description section - no header, just show description directly -->
        {#if skillDescription}
            <div class="description-section">
                <p class="skill-description">{skillDescription}</p>
            </div>
        {/if}
        
        <!-- Providers section -->
        {#if skill.providers && skill.providers.length > 0}
            <div class="section">
                <SettingsItem 
                    type="heading"
                    icon="provider"
                    title={$text('settings.app_store.skills.providers.text')}
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
        
        <!-- Pricing section -->
        {#if skill.pricing}
            <div class="section">
                <SettingsItem 
                    type="heading"
                    icon="credits"
                    title={$text('settings.app_store.skills.pricing.text')}
                />
                <div class="content">
                    <p class="pricing">{formatPricing(skill.pricing)}</p>
                </div>
            </div>
        {/if}
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
        color: var(--text-primary, #000000);
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

