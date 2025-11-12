<!-- frontend/packages/ui/src/components/settings/SkillCard.svelte
     Component for displaying individual skill information.
     
     **Backend Implementation**:
     - API endpoint: `backend/core/api/app/routes/apps.py:get_apps_metadata()`
     - Types: `frontend/packages/ui/src/types/apps.ts`
-->

<script lang="ts">
    import type { SkillMetadata } from '../../types/apps';
    
    /**
     * Props for SkillCard component.
     */
    interface Props {
        skill: SkillMetadata;
        appId: string;
    }
    
    let { skill, appId }: Props = $props();
    
    /**
     * Format pricing information for display.
     */
    function formatPricing(pricing: SkillMetadata['pricing']): string {
        if (!pricing) {
            return 'Free';
        }
        
        if (pricing.fixed !== undefined) {
            return `${pricing.fixed} credits`;
        }
        
        if (pricing.per_unit) {
            const unitName = pricing.per_unit.unit_name || 'unit';
            return `${pricing.per_unit.credits} credits per ${unitName}`;
        }
        
        if (pricing.tokens) {
            const parts: string[] = [];
            if (pricing.tokens.input) {
                parts.push(`${pricing.tokens.input.per_credit_unit} input tokens/credit`);
            }
            if (pricing.tokens.output) {
                parts.push(`${pricing.tokens.output.per_credit_unit} output tokens/credit`);
            }
            return parts.join(', ') || 'Token-based pricing';
        }
        
        if (pricing.per_minute !== undefined) {
            return `${pricing.per_minute} credits per minute`;
        }
        
        return 'Pricing available';
    }
    
    let pricingText = $derived(formatPricing(skill.pricing));
</script>

<div class="skill-card">
    <div class="skill-header">
        <h3 class="skill-name">{skill.name}</h3>
        {#if skill.pricing}
            <span class="skill-pricing">{pricingText}</span>
        {/if}
    </div>
    
    <p class="skill-description">{skill.description}</p>
    
    <div class="skill-footer">
        <span class="skill-id">{appId}.{skill.id}</span>
    </div>
</div>

<style>
    .skill-card {
        background: var(--card-background, #ffffff);
        border: 1px solid var(--border-color, #e0e0e0);
        border-radius: 12px;
        padding: 1.5rem;
        transition: all 0.2s ease;
    }
    
    .skill-card:hover {
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
        transform: translateY(-2px);
    }
    
    .skill-header {
        display: flex;
        justify-content: space-between;
        align-items: flex-start;
        gap: 1rem;
        margin-bottom: 0.75rem;
    }
    
    .skill-name {
        margin: 0;
        font-size: 1.1rem;
        font-weight: 600;
        color: var(--text-primary, #000000);
        flex: 1;
    }
    
    .skill-pricing {
        font-size: 0.85rem;
        color: var(--text-secondary, #666666);
        background: var(--tag-background, #f5f5f5);
        padding: 0.25rem 0.5rem;
        border-radius: 4px;
        white-space: nowrap;
    }
    
    .skill-description {
        margin: 0 0 1rem 0;
        color: var(--text-secondary, #666666);
        font-size: 0.9rem;
        line-height: 1.5;
    }
    
    .skill-footer {
        padding-top: 1rem;
        border-top: 1px solid var(--border-color, #e0e0e0);
    }
    
    .skill-id {
        font-size: 0.75rem;
        color: var(--text-tertiary, #999999);
        font-family: monospace;
    }
</style>
