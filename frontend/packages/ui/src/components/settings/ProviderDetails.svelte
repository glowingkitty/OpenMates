<!-- frontend/packages/ui/src/components/settings/ProviderDetails.svelte

     Provider detail page for app skills.

     Shows:
     - About section: provider description + country/location
     - Connected Skills section: all app skills that use this provider (clickable)

     **Routing**:
     - app_store/{app_id}/skill/{skill_id}/provider/{provider_id}
     - Back navigates to app_store/{app_id}/skill/{skill_id}

     **Data sources**:
     - providersMetadata.ts — static provider info (id, name, description, country, logo_svg)
     - appsMetadata.ts — to find all skills connected to this provider
-->

<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import { text } from '@repo/ui';
    import { providersMetadata } from '../../data/providersMetadata';
    import { appsMetadata } from '../../data/appsMetadata';
    import { appSkillsStore } from '../../stores/appSkillsStore';
    import SettingsItem from '../SettingsItem.svelte';
    import Icon from '../Icon.svelte';

    const dispatch = createEventDispatcher();

    interface Props {
        appId: string;
        skillId: string;
        providerId: string;
    }

    let { appId, skillId, providerId }: Props = $props();

    // Get provider metadata
    let provider = $derived(providersMetadata[providerId]);

    // Get app/skill metadata (used for back-navigation title)
    let storeState = $state(appSkillsStore.getState());
    let app = $derived(storeState.apps[appId]);
    let skill = $derived(app?.skills.find(s => s.id === skillId));

    /**
     * Find all app skills connected to this provider.
     * A skill is connected if provider.name appears in skill.providers (case-insensitive).
     */
    interface ConnectedSkill {
        appId: string;
        skillId: string;
        appName: string;
        skillName: string;
        appIconImage: string | undefined;
        appNameKey: string | undefined;
        skillNameKey: string | undefined;
    }

    let connectedSkills = $derived.by((): ConnectedSkill[] => {
        if (!provider) return [];
        const providerNameLower = provider.name.toLowerCase();
        const result: ConnectedSkill[] = [];
        for (const [aId, appMeta] of Object.entries(appsMetadata)) {
            for (const skillMeta of appMeta.skills ?? []) {
                const providers = skillMeta.providers ?? [];
                const matches = providers.some(
                    (p: string) => p.toLowerCase() === providerNameLower
                );
                if (matches) {
                    result.push({
                        appId: aId,
                        skillId: skillMeta.id,
                        appName: appMeta.name_translation_key ?? aId,
                        skillName: skillMeta.name_translation_key ?? skillMeta.id,
                        appIconImage: appMeta.icon_image,
                        appNameKey: appMeta.name_translation_key,
                        skillNameKey: skillMeta.name_translation_key,
                    });
                }
            }
        }
        return result;
    });

    /**
     * Get flag emoji for ISO 3166-1 alpha-2 country code (e.g. "US" → "🇺🇸").
     * Returns empty string for special codes like "EU" that are not alpha-2.
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
     * Get a human-readable country/region name for a code.
     */
    function getCountryName(countryCode: string): string {
        const names: Record<string, string> = {
            US: 'United States',
            FR: 'France',
            CN: 'China',
            DE: 'Germany',
            UK: 'United Kingdom',
            GB: 'United Kingdom',
            JP: 'Japan',
            KR: 'South Korea',
            CA: 'Canada',
            AU: 'Australia',
            IN: 'India',
            EU: 'European Union',
        };
        return names[countryCode.toUpperCase()] ?? countryCode;
    }

    /**
     * Get icon name from icon_image filename for navigation.
     * Mirrors the same logic used in AppSkillModelDetails and SkillDetails.
     */
    function getIconName(iconImage: string | undefined): string {
        if (!iconImage) return appId;
        let iconName = iconImage.replace(/\.svg$/, '');
        if (iconName === 'coding') iconName = 'code';
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
            title: skill?.name_translation_key ? $text(skill.name_translation_key) : skillId,
        });
    }

    /**
     * Navigate to a connected skill's detail page.
     */
    function handleSkillClick(connected: ConnectedSkill) {
        dispatch('openSettings', {
            settingsPath: `app_store/${connected.appId}/skill/${connected.skillId}`,
            direction: 'forward',
            icon: getIconName(connected.appIconImage),
            title: connected.skillNameKey ? $text(connected.skillNameKey) : connected.skillId,
        });
    }
</script>

<div class="provider-details">
    {#if !provider}
        <div class="error">
            <p>{$text('settings.app_store.provider_not_found')}</p>
            <button class="back-button" onclick={goBack}>← {$text('settings.app_store.back_to_app')}</button>
        </div>
    {:else}
        <!-- About section: description + location -->
        <div class="section">
            <SettingsItem
                type="heading"
                icon="icon_info"
                title={$text('settings.app_store.provider_detail.about')}
            />
            <div class="about-content">
                <!-- Description -->
                {#if provider.description}
                    <p class="provider-description">{provider.description}</p>
                {/if}

                <!-- Location row -->
                {#if provider.country}
                    <div class="info-row">
                        <span class="info-label">{$text('settings.app_store.provider_detail.location')}</span>
                        <span class="info-value">
                            <span class="country-flag">{getCountryFlag(provider.country)}</span>
                            {getCountryName(provider.country)}
                        </span>
                    </div>
                {/if}
            </div>
        </div>

        <!-- Connected Skills section -->
        {#if connectedSkills.length > 0}
            <div class="section">
                <SettingsItem
                    type="heading"
                    icon="skill"
                    title={$text('settings.app_store.provider_detail.connected_skills')}
                />
                <div class="skills-list">
                    {#each connectedSkills as connected (connected.appId + '.' + connected.skillId)}
                        <div
                            class="skill-item"
                            role="button"
                            tabindex="0"
                            onclick={() => handleSkillClick(connected)}
                            onkeydown={(e) => e.key === 'Enter' && handleSkillClick(connected)}
                        >
                            <div class="skill-icon">
                                <Icon
                                    name={getIconName(connected.appIconImage)}
                                    type="app"
                                    size="32px"
                                    noAnimation={true}
                                />
                            </div>
                            <div class="skill-info">
                                <span class="skill-name">
                                    {connected.skillNameKey ? $text(connected.skillNameKey) : connected.skillId}
                                </span>
                                <span class="skill-app">
                                    {connected.appNameKey ? $text(connected.appNameKey) : connected.appId}
                                </span>
                            </div>
                            <span class="skill-chevron">›</span>
                        </div>
                    {/each}
                </div>
            </div>
        {/if}
    {/if}
</div>

<style>
    .provider-details {
        padding: 14px;
        max-width: 1400px;
        margin: 0 auto;
    }

    /* Sections */
    .section {
        margin-top: 1.5rem;
    }

    /* About content */
    .about-content {
        padding: 0.75rem 0 0.75rem 10px;
    }

    .provider-description {
        margin: 0 0 1rem;
        color: var(--color-grey-100);
        font-size: 1rem;
        line-height: 1.6;
    }

    /* Info rows (location) */
    .info-row {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 0.75rem 0;
        border-top: 1px solid var(--color-grey-15);
    }

    .info-label {
        color: var(--color-grey-60);
        font-size: 0.9rem;
    }

    .info-value {
        display: flex;
        align-items: center;
        gap: 0.5rem;
        color: var(--color-grey-100);
        font-size: 0.9rem;
        font-weight: 500;
    }

    .country-flag {
        font-size: 1.25rem;
    }

    /* Connected skills list */
    .skills-list {
        display: flex;
        flex-direction: column;
        gap: 0;
        margin-left: 10px;
    }

    .skill-item {
        display: flex;
        align-items: center;
        gap: 12px;
        padding: 12px 16px;
        border-radius: 8px;
        cursor: pointer;
        transition: background 0.15s;
    }

    .skill-item:hover {
        background: var(--color-grey-10);
    }

    .skill-icon {
        flex-shrink: 0;
        width: 32px;
        height: 32px;
        display: flex;
        align-items: center;
        justify-content: center;
    }

    .skill-info {
        flex: 1;
        min-width: 0;
        display: flex;
        flex-direction: column;
        gap: 2px;
    }

    .skill-name {
        font-size: 1rem;
        font-weight: 500;
        color: var(--color-primary-start);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }

    .skill-app {
        font-size: 0.875rem;
        color: var(--color-grey-60);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }

    .skill-chevron {
        flex-shrink: 0;
        font-size: 1.25rem;
        color: var(--color-grey-40);
        line-height: 1;
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
    :global(.dark) .skill-item:hover {
        background: var(--color-grey-15);
    }
</style>
