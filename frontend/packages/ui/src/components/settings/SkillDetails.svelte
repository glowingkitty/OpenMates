<!-- frontend/packages/ui/src/components/settings/SkillDetails.svelte
     Component for displaying details of a specific skill, including description, providers, and pricing.
     
     This component is used for the app_store/{app_id}/skill/{skill_id} nested route.
     
     **Multi-model skills** (e.g. images.generate, images.generate_draft, audio.transcribe):
     When the modelsMetadata contains models tagged with `for_app_skill === "{appId}.{skillId}"`,
     the Providers and Pricing sections are replaced by a clickable model list — the same UI
     pattern used by the AI Ask skill. Clicking a model navigates to:
       app_store/{app_id}/skill/{skill_id}/model/{model_id}
     which renders AppSkillModelDetails.svelte.
     
     **Single-pricing skills** (no models in modelsMetadata):
     Keeps the original flat Providers + Pricing display.
     
     **Backend Implementation**:
     - Data source: Static appsMetadata.ts and modelsMetadata.ts (generated at build time)
     - Store: frontend/packages/ui/src/stores/appSkillsStore.ts
     - Types: frontend/packages/ui/src/types/apps.ts
-->

<script lang="ts">
    import { appSkillsStore } from '../../stores/appSkillsStore';
    import { modelsMetadata, type AIModelMetadata } from '../../data/modelsMetadata';
    import { findProviderByName } from '../../data/providersMetadata';
    import { getProviderIconUrl } from '../../data/providerIcons';
    import { SettingsSectionHeading } from './elements';
    import SkillExamplesSection from './SkillExamplesSection.svelte';
    import type { AppMetadata, SkillMetadata, SkillPricing } from '../../types/apps';
    import { createEventDispatcher } from 'svelte';
    import { text } from '@repo/ui';
    import { setAppStoreNavList, clearAppStoreNav } from '../../stores/appStoreNavigationStore';
    import { onDestroy } from 'svelte';
    import { pendingMentionStore } from '../../stores/pendingMentionStore';
    import { panelState } from '../../stores/panelStateStore';
    
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
     * Look up all models whose `for_app_skill` matches "{appId}.{skillId}".
     * When this list is non-empty the skill supports multiple distinct models,
     * so we render a clickable model list instead of the flat pricing text.
     */
    let skillModels = $derived<AIModelMetadata[]>(
        modelsMetadata.filter(m => m.for_app_skill === `${appId}.${skillId}`)
    );
    
    /** Whether this skill has models to show in a list. */
    let hasModels = $derived(skillModels.length > 0);
    
    /**
     * Format pricing information for display.
     * Returns an array of strings for token pricing (to display on separate lines),
     * or a single string for other pricing types.
     *
     * Valid pricing types:
     *   - fixed → "{N} credits / request" (default)
     *   - per_minute → "{N} credits / minute"
     *   - tokens.input → "{N} tokens / credit (input)"
     *   - tokens.output → "{N} tokens / credit (output)"
     *
     * Only used when hasModels is false.
     */
    function formatPricing(pricing: SkillPricing | undefined): string | string[] {
        // Never show "Free" - if no pricing provided, default to 1 credit per request
        // This should not happen in practice since metadata generation always sets pricing
        if (!pricing) {
            return `1 ${$text('common.credits')} / request`;
        }
        
        // Token-based pricing - return array for separate lines
        // per_credit_unit means "tokens per credit" (e.g., 700 means 700 tokens per 1 credit)
        if (pricing.tokens) {
            const tokenParts: string[] = [];
            if (pricing.tokens.input) {
                tokenParts.push(`${pricing.tokens.input.per_credit_unit} ${$text('settings.app_store.skills.pricing.token')} / ${$text('common.credits')} (${$text('settings.app_store.skills.pricing.input')})`);
            }
            if (pricing.tokens.output) {
                tokenParts.push(`${pricing.tokens.output.per_credit_unit} ${$text('settings.app_store.skills.pricing.token')} / ${$text('common.credits')} (${$text('settings.app_store.skills.pricing.output')})`);
            }
            if (tokenParts.length > 0) {
                return tokenParts;
            }
        }
        
        // Other pricing types - return single string
        const parts: string[] = [];
        
        // Fixed pricing → "N credits / request"
        if (pricing.fixed !== undefined) {
            parts.push(`${pricing.fixed} ${$text('common.credits')} / request`);
        }
        
        // Per-unit pricing: use the unit_name provided (e.g., "image", "page") as the denominator.
        // Falls back to "request" when unit_name is absent to avoid the non-descriptive "/ unit" label.
        if (pricing.per_unit) {
            const unitName = pricing.per_unit.unit_name || 'request';
            parts.push(`${pricing.per_unit.credits} ${$text('common.credits')} / ${unitName}`);
        }
        
        // Per minute pricing → "N credits / minute"
        if (pricing.per_minute !== undefined) {
            parts.push(`${pricing.per_minute} ${$text('common.credits')} / ${$text('settings.app_store.skills.pricing.minute')}`);
        }
        
        return parts.length > 0 ? parts.join(', ') : `1 ${$text('common.credits')} / request`;
    }
    
    /**
     * Get formatted pricing for display.
     * Returns either a string or array of strings (for token pricing).
     * Only relevant when hasModels is false.
     */
    let formattedPricing = $derived(formatPricing(skill?.pricing));
    
    /**
     * Build the @mention display name for this skill.
     * Matches the format used in mentionSearchService: "AppName-SkillName"
     * e.g., appId="audio", skillId="generate_transcript" → "Audio-Generate-Transcript"
     */
    function capitalizeHyphenated(str: string): string {
        return str.split('-').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join('-');
    }

    let skillMentionDisplayName = $derived(
        `${capitalizeHyphenated(appId)}-${capitalizeHyphenated(skillId.replace(/_/g, '-'))}`
    );

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
            // Only add if translation exists (not a missing-key placeholder)
            if (translated && translated !== key && !translated.startsWith('[T:')) {
                examples.push(translated);
            }
        }
        return examples;
    });

    /**
     * Parse **word** markdown syntax into HTML with highlighted spans.
     * Words wrapped in double asterisks (**word**) are rendered as
     * <span class="highlight-word"> elements styled with the app's gradient color.
     * The text is escaped first to prevent XSS.
     *
     * @param text - Raw how-to-use text possibly containing **word** syntax
     * @returns HTML string safe to use with {@html}
     */
    function parseHighlightedText(rawText: string): string {
        // Escape HTML to prevent XSS before inserting spans
        const escaped = rawText
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
        // Replace **word** with highlighted span; use the scoped CSS class
        return escaped.replace(/\*\*(.+?)\*\*/g, '<span class="highlight-word">$1</span>');
    }
    
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
        // Handle special case: heart.svg -> health (since the app ID is "health" but icon file is heart.svg)
        // This ensures the correct CSS variable --color-app-health is used instead of --color-app-heart
        if (iconName === 'heart') {
            iconName = 'health';
        }
        return iconName;
    }
    
    /**
     * Register sibling skills for prev/next navigation in AppDetailsHeader.
     * Re-runs whenever app or skillId changes (deep link changes the current skill).
     * Clears the navigation state when this component is destroyed.
     *
     * The navigate callback dispatches the same openSettings event as clicking a
     * SkillCard — allowing AppDetailsHeader arrows to advance through all of the
     * app's skills in order.
     */
    $effect(() => {
        const skills = app?.skills ?? [];
        if (skills.length > 1) {
            setAppStoreNavList(
                skills.map(s => ({
                    id: s.id,
                    name: s.name_translation_key ? $text(s.name_translation_key) : s.id,
                })),
                skillId,
                (targetSkillId) => {
                    dispatch('openSettings', {
                        settingsPath: `app_store/${appId}/skill/${targetSkillId}`,
                        direction: 'forward',
                        icon: getIconName(app?.icon_image),
                        title: app?.name_translation_key ? $text(app.name_translation_key) : appId,
                    });
                },
            );
        } else {
            // Single skill app — no siblings to navigate to
            clearAppStoreNav();
        }
    });

    onDestroy(() => {
        clearAppStoreNav();
    });

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
    
    /**
     * Navigate to a specific model's detail page.
     * Used when this skill has multiple models (hasModels === true).
     */
    function handleModelClick(model: AIModelMetadata) {
        dispatch('openSettings', {
            settingsPath: `app_store/${appId}/skill/${skillId}/model/${model.id}`,
            direction: 'forward',
            icon: getIconName(app?.icon_image),
            title: model.name
        });
    }

    /**
     * Navigate to a provider's detail page.
     * Looks up the provider by display name to get its id for the route.
     * Used for providers in the single-pricing (no models) section.
     *
     * @param providerName - Display name string from skill.providers (e.g. "Brave Search")
     */
    function handleProviderClick(providerName: string) {
        const providerMeta = findProviderByName(providerName);
        if (!providerMeta) return; // Provider not in metadata — not navigable
        dispatch('openSettings', {
            settingsPath: `app_store/${appId}/skill/${skillId}/provider/${providerMeta.id}`,
            direction: 'forward',
            icon: getIconName(app?.icon_image),
            title: providerMeta.name,
        });
    }

    /**
     * Insert the skill @mention into the message input and close settings.
     * Uses pendingMentionStore with "@skill:{appId}:{skillId}" syntax.
     * MessageInput.svelte watches this store and renders it as a styled mention chip.
     */
    function insertSkillMention() {
        pendingMentionStore.set(`@skill:${appId}:${skillId}`);
        panelState.closeSettings();
    }
</script>

<div class="skill-details">
    {#if !app || !skill}
        <div class="error">
            <p>{$text('settings.app_store.skill_not_found')}</p>
            <button class="back-button" onclick={goBack}>← {$text('settings.app_store.back_to_app')}</button>
        </div>
    {:else}
        {#if hasModels}
            <!-- 
                Multi-model skill: show a clickable model list instead of flat Providers + Pricing.
                Each model row navigates to its detail page with pricing breakdown.
                This matches the UI pattern used by the AI Ask skill.
                Pricing section shown first (at top), then How to Use, then Models list.
            -->

            <!-- Pricing section first — always visible at top -->
            <div class="section">
                <SettingsSectionHeading title={$text('common.pricing')} icon="coins" />
                <div class="content">
                    {#if Array.isArray(formattedPricing)}
                        {#each formattedPricing as pricingLine}
                            <p class="pricing">{pricingLine}</p>
                        {/each}
                    {:else}
                        <p class="pricing">{formattedPricing}</p>
                    {/if}
                </div>
            </div>

            <!-- Examples section (real embed previews from curated skill runs) — above How to Use -->
            <SkillExamplesSection {appId} {skillId} />

            <!-- How to use section (after examples) -->
            {#if howToUseExamples.length > 0}
                <div class="section how-to-use-section">
                    <SettingsSectionHeading title={$text('settings.app_store.skills.how_to_use')} icon="skill" />
                    <p class="how-to-use-prefix">{$text('settings.app_store.skills.how_to_use_prefix')}</p>
                    <div class="how-to-use-scroll-container">
                        <div class="how-to-use-scroll">
                            {#each howToUseExamples as example}
                                <div
                                    class="how-to-use-card"
                                    style="--highlight-color: var(--color-app-{appId}-start, var(--color-primary-start))"
                                >
                                    <svg class="quote-icon quote-open" width="20" height="20" viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                                        <path d="M15 3a6 6 0 016 6v17.997c0 9.389-4.95 15.577-14.271 17.908a3.001 3.001 0 01-3.717-3.35 3 3 0 012.259-2.47C11.952 37.416 15 33.606 15 26.998v-3H6a6 6 0 01-5.985-5.549L0 17.998V9A5.999 5.999 0 016 3h9zm27 0a6 6 0 016 6v17.997c0 9.389-4.95 15.577-14.271 17.908a3.001 3.001 0 01-3.716-3.35 2.998 2.998 0 012.258-2.47C38.952 37.416 42 33.606 42 26.998v-3h-9a6 6 0 01-5.985-5.549l-.015-.45V9A5.999 5.999 0 0133 3h9z" fill="currentColor"/>
                                    </svg>
                                    <!-- eslint-disable-next-line svelte/no-at-html-tags -->
                                    <p class="how-to-use-text">{@html parseHighlightedText(example)}</p>
                                    <svg class="quote-icon quote-close" width="20" height="20" viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                                        <path d="M15 3a6 6 0 016 6v17.997c0 9.389-4.95 15.577-14.271 17.908a3.001 3.001 0 01-3.716-3.35 2.998 2.998 0 012.258-2.47C38.952 37.416 42 33.606 42 26.998v-3h-9a6 6 0 01-5.985-5.549l-.015-.45V9A5.999 5.999 0 0133 3h9z" fill="currentColor"/>
                                    </svg>
                                </div>
                            {/each}
                        </div>
                    </div>
                    <p class="how-to-use-mention">
                        {$text('settings.app_store.skills.how_to_use_mention').split('{skillname}')[0]}<button type="button" class="mention-name" onclick={insertSkillMention}>@{skillMentionDisplayName}</button>{$text('settings.app_store.skills.how_to_use_mention').split('{skillname}')[1]}
                    </p>
                </div>
            {/if}

            <!-- Models list (below pricing, examples and how-to-use) -->
            <div class="section">
                <SettingsSectionHeading title={$text('settings.app_store.skills.models')} icon="skill" />
                <div class="models-list">
                    {#each skillModels as model (model.id)}
                        <div
                            class="model-item"
                            data-testid="model-item"
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
                            <!-- Chevron to indicate clickability -->
                            <span class="model-chevron">›</span>
                        </div>
                    {/each}
                </div>
            </div>
        {:else}
            <!-- 
                Single-pricing skill: Pricing first, then How to Use, then Providers.
            -->

            <!-- Pricing section - always show first, even if free -->
            <div class="section">
                <SettingsSectionHeading title={$text('common.pricing')} icon="coins" />
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

            <!-- Examples section (real embed previews from curated skill runs) — above How to Use -->
            <SkillExamplesSection {appId} {skillId} />

            <!-- How to use section (after examples) - horizontal scrollable example instructions -->
            {#if howToUseExamples.length > 0}
                <div class="section how-to-use-section">
                    <SettingsSectionHeading title={$text('settings.app_store.skills.how_to_use')} icon="skill" />
                    <!-- "Just ask your mates something like:" prefix -->
                    <p class="how-to-use-prefix">{$text('settings.app_store.skills.how_to_use_prefix')}</p>
                    <div class="how-to-use-scroll-container">
                        <div class="how-to-use-scroll">
                            {#each howToUseExamples as example}
                                <div
                                    class="how-to-use-card"
                                    style="--highlight-color: var(--color-app-{appId}-start, var(--color-primary-start))"
                                >
                                    <!-- Opening quote — top-right corner -->
                                    <svg class="quote-icon quote-open" width="20" height="20" viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                                        <path d="M15 3a6 6 0 016 6v17.997c0 9.389-4.95 15.577-14.271 17.908a3.001 3.001 0 01-3.717-3.35 3 3 0 012.259-2.47C11.952 37.416 15 33.606 15 26.998v-3H6a6 6 0 01-5.985-5.549L0 17.998V9A5.999 5.999 0 016 3h9zm27 0a6 6 0 016 6v17.997c0 9.389-4.95 15.577-14.271 17.908a3.001 3.001 0 01-3.716-3.35 2.998 2.998 0 012.258-2.47C38.952 37.416 42 33.606 42 26.998v-3h-9a6 6 0 01-5.985-5.549l-.015-.45V9A5.999 5.999 0 0133 3h9z" fill="currentColor"/>
                                    </svg>

                                    <!-- How-to-use text with **word** highlight support -->
                                    <!-- eslint-disable-next-line svelte/no-at-html-tags -->
                                    <p class="how-to-use-text">{@html parseHighlightedText(example)}</p>

                                    <!-- Closing quote — bottom-left corner (flipped 180°) -->
                                    <svg class="quote-icon quote-close" width="20" height="20" viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                                        <path d="M15 3a6 6 0 016 6v17.997c0 9.389-4.95 15.577-14.271 17.908a3.001 3.001 0 01-3.716-3.35 2.998 2.998 0 012.258-2.47C38.952 37.416 42 33.606 42 26.998v-3h-9a6 6 0 01-5.985-5.549l-.015-.45V9A5.999 5.999 0 0133 3h9z" fill="currentColor"/>
                                    </svg>
                                </div>
                            {/each}
                        </div>
                    </div>
                    <!-- "Or mention @SkillName in your message..." footer -->
                    <!-- Clicking the @mention inserts it into the message input (same as "Chat with this mate") -->
                    <p class="how-to-use-mention">
                        {$text('settings.app_store.skills.how_to_use_mention').split('{skillname}')[0]}<button type="button" class="mention-name" onclick={insertSkillMention}>@{skillMentionDisplayName}</button>{$text('settings.app_store.skills.how_to_use_mention').split('{skillname}')[1]}
                    </p>
                </div>
            {/if}

            <!-- Providers section (below pricing, examples and how-to-use) -->
            {#if skill.providers && skill.providers.length > 0}
                <div class="section">
                    <SettingsSectionHeading title={$text('settings.app_store.skills.providers')} icon="provider" />
                    <div class="providers-list">
                        {#each skill.providers as providerName}
                            {@const providerMeta = findProviderByName(providerName)}
                            {#if providerMeta}
                                <!-- Provider is in metadata — render as clickable row with provider logo -->
                                <div
                                    class="provider-item provider-item--clickable"
                                    role="button"
                                    tabindex="0"
                                    onclick={() => handleProviderClick(providerName)}
                                    onkeydown={(e) => e.key === 'Enter' && handleProviderClick(providerName)}
                                >
                                    <div class="provider-icon">
                                        <img
                                            src={getProviderIconUrl(providerMeta.logo_svg)}
                                            alt={providerMeta.name}
                                            class="provider-logo"
                                        />
                                    </div>
                                    <div class="provider-info">
                                        <span class="provider-name">{providerMeta.name}</span>
                                    </div>
                                    <span class="provider-chevron">›</span>
                                </div>
                            {:else}
                                <!-- Provider not in metadata — render as plain non-clickable row with server icon -->
                                <div class="provider-item">
                                    <div class="provider-icon">
                                        <img
                                            src="/icons/server.svg"
                                            alt={providerName}
                                            class="provider-logo provider-logo--server"
                                        />
                                    </div>
                                    <div class="provider-info">
                                        <span class="provider-name">{providerName}</span>
                                    </div>
                                </div>
                            {/if}
                        {/each}
                    </div>
                </div>
            {/if}
        {/if}
    {/if}
</div>

<style>
    .skill-details {
        padding: 14px;
        max-width: 1400px;
        margin: 0 auto;
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
    
    /* Providers list — clickable rows matching the model-item style */
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

    .provider-item--clickable {
        cursor: pointer;
        transition: background var(--duration-fast);
    }

    .provider-item--clickable:hover {
        background: var(--color-grey-10);
    }

    .provider-icon {
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

    .provider-info {
        flex: 1;
        min-width: 0;
    }

    .provider-name {
        font-size: 1rem;
        font-weight: 500;
        color: var(--color-primary-start);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        display: block;
    }

    .provider-chevron {
        flex-shrink: 0;
        font-size: 1.25rem;
        color: var(--color-grey-40);
        line-height: 1;
    }

    /* Server icon for providers not in metadata — apply subtle color tint */
    .provider-logo--server {
        filter: invert(0.4) sepia(1) saturate(3) hue-rotate(200deg);
    }
    
    .pricing {
        font-weight: 500;
        color: var(--color-grey-100);
    }
    
    /* How to use section styles */
    .how-to-use-section {
        margin-top: 1.5rem;
    }

    /* "Just ask your mates something like:" label above example cards */
    .how-to-use-prefix {
        margin: 0.5rem 0 0 0;
        padding: 0;
        font-size: 0.9rem;
        font-weight: 600;
        line-height: 1.5;
        color: var(--color-grey-100);
    }

    /* "Or mention @SkillName in your message..." footer below example cards */
    .how-to-use-mention {
        margin: 0.75rem 0 0 0;
        padding: 0;
        font-size: 0.9rem;
        font-weight: 600;
        line-height: 1.6;
        color: var(--color-grey-100);
        white-space: pre-line;
    }

    /* The @mention name — styled as an inline clickable text link (no underline) */
    .how-to-use-mention .mention-name {
        display: inline;
        padding: 0;
        margin: 0;
        border: none;
        background: none;
        font: inherit;
        font-size: inherit;
        font-weight: 600;
        line-height: inherit;
        color: var(--color-primary-start);
        cursor: pointer;
        text-decoration: none;
    }

    .how-to-use-mention .mention-name:hover {
        text-decoration: none;
        opacity: 0.8;
    }
    
    .how-to-use-scroll-container {
        overflow-x: auto;
        overflow-y: hidden;
        padding-bottom: 0.5rem;
        margin-top: 0.75rem;
        scrollbar-width: thin;
        scrollbar-color: rgba(128, 128, 128, 0.2) transparent;
        transition: scrollbar-color var(--duration-normal) var(--easing-default);
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
        border-radius: var(--radius-1);
        border: 2px solid var(--color-grey-20);
        transition: background-color var(--duration-normal) var(--easing-default);
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
        border-radius: var(--radius-5);
        /* Opening quote top-left, text spans middle, closing quote bottom-right */
        display: grid;
        grid-template-areas:
            "open text"
            ".    close";
        grid-template-columns: auto 1fr;
        grid-template-rows: auto 1fr;
        gap: 0.4rem;
    }

    /* Opening quote — top-LEFT */
    .quote-open {
        grid-area: open;
        align-self: start;
        justify-self: start;
        color: var(--color-grey-40);
        opacity: 0.5;
        flex-shrink: 0;
    }

    /* Closing quote — bottom-RIGHT, rotated 180° to face the other direction */
    .quote-close {
        grid-area: close;
        align-self: end;
        justify-self: end;
        color: var(--color-grey-40);
        opacity: 0.5;
        flex-shrink: 0;
        transform: rotate(180deg);
    }

    .how-to-use-text {
        grid-area: text;
        margin: 0;
        font-size: 0.9rem;
        line-height: 1.5;
        color: var(--color-grey-100);
        word-break: break-word;
        align-self: start;
    }

    /* Highlighted trigger words (from **word** syntax in i18n) */
    .how-to-use-text :global(.highlight-word) {
        color: var(--highlight-color, var(--color-primary-start));
        font-weight: 600;
    }

    /* Models list (multi-model skill) — matches AiAskSkillSettings.svelte style */
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
    
    .model-chevron {
        flex-shrink: 0;
        font-size: 1.25rem;
        color: var(--color-grey-40);
        line-height: 1;
    }
    
    .error {
        padding: 3rem;
        text-align: center;
        color: var(--error-color, #dc3545);
    }
    
    .back-button {
        background: var(--button-background, #f0f0f0);
        border: 1px solid var(--border-color, #e0e0e0);
        border-radius: var(--radius-2);
        padding: 0.5rem 1rem;
        margin-top: 1rem;
        cursor: pointer;
        font-size: 0.9rem;
        color: var(--text-primary, #000000);
        transition: background var(--duration-normal) var(--easing-default);
    }
    
    .back-button:hover {
        background: var(--button-hover-background, #e0e0e0);
    }
    
    /* Dark mode */
    :global(.dark) .model-item:hover {
        background: var(--color-grey-15);
    }

    :global(.dark) .provider-item--clickable:hover {
        background: var(--color-grey-15);
    }
    
    :global(.dark) .provider-logo {
        background: var(--color-grey-20);
    }
</style>
