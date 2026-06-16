<!-- frontend/packages/ui/src/components/settings/AppDetails.svelte
     Component for displaying details of a specific app, including its skills.
     
     This component is used for the apps/{app_id} nested route.
     
     **Backend Implementation**:
     - Data source: Static appsMetadata.ts (generated at build time)
     - Store: frontend/packages/ui/src/stores/appSkillsStore.ts
     - Types: frontend/packages/ui/src/types/apps.ts
-->

<script lang="ts">
    import { onMount } from 'svelte';
    import { appSkillsStore } from '../../stores/appSkillsStore';
    import { authStore } from '../../stores/authStore';
    import { userProfile } from '../../stores/userProfile';
    import AppStoreCard from './AppStoreCard.svelte';
    import AppEmbedsPanel from './appSettings/AppEmbedsPanel.svelte';
    import ActiveRemindersList from './appSettings/ActiveRemindersList.svelte';
    import { SettingsButton, SettingsCard, SettingsCheckboxList, SettingsInfoBox, SettingsSectionHeading } from './elements';
    import type { AppMetadata, MemoryFieldMetadata, SkillMetadata } from '../../types/apps';
    import { CONTENT_EMBED_CATALOG, type ContentEmbedCatalogItem } from '../../data/embedRegistry.generated';
    import { createEventDispatcher } from 'svelte';
    import { text } from '@repo/ui';
    import { computeSHA256 } from '../../message_parsing/utils';
    import {
        listConnectedAccounts,
        summarizeConnectedAccountRows,
        type ConnectedAccountSummary,
        type EncryptedConnectedAccountRow
    } from '../../services/connectedAccountStorageService';
    import { finalizeOAuthHandoffAsConnectedAccount, startGoogleCalendarOAuth } from '../../services/connectedAccountOAuthService';
    
    // Create event dispatcher for navigation
    const dispatch = createEventDispatcher();
    
    // Get app ID from the current path
    // The path will be like "apps/ai" or "apps/web"
    // This will be passed as a prop from Settings.svelte
    
    interface Props {
        appId: string;
    }
    
    let { appId }: Props = $props();
    
    // Get store state reactively (Svelte 5)
    let storeState = $state(appSkillsStore.getState());
    
    // Check if user is authenticated (for read-only mode)
    let isAuthenticated = $derived($authStore.isAuthenticated);
    
    // Get app metadata from store
    let app = $derived<AppMetadata | undefined>(storeState.apps[appId]);
    let skills = $derived(app?.skills || []);
    let contentTypes = $derived(CONTENT_EMBED_CATALOG.filter((item) => item.appId === appId));
    let focusModes = $derived(app?.focus_modes || []);
    let memoryFields = $derived(app?.settings_and_memories || []);
    let connectedCalendarAccounts = $state<EncryptedConnectedAccountRow[]>([]);
    let connectedCalendarAccountSummaries = $state<ConnectedAccountSummary[]>([]);
    let connectedAccountsLoading = $state(false);
    let connectedAccountAction = $state<'idle' | 'connecting' | 'finalizing'>('idle');
    let connectedAccountError = $state('');
    let connectedAccountSuccess = $state('');
    let finalizedOAuthHandoffId = $state('');
    let calendarCapabilitySelections = $state<Record<CalendarCapability, boolean>>({
        read: true,
        write: true,
        delete: true
    });

    type CalendarCapability = 'read' | 'write' | 'delete';

    const CALENDAR_CAPABILITIES: CalendarCapability[] = ['read', 'write', 'delete'];

    function hasGuestExamples(category: MemoryFieldMetadata): boolean {
        return (category.example_entries?.length ?? 0) > 0 || (category.example_translation_keys?.length ?? 0) > 0;
    }

    // Guests can only explore read-only example data. Hide categories that would
    // open to an empty page because they only support authenticated saved entries.
    let visibleMemoryFields = $derived.by(() => (
        isAuthenticated ? memoryFields : memoryFields.filter(hasGuestExamples)
    ));

    let calendarCapabilityOptions = $derived(CALENDAR_CAPABILITIES.map((capability) => ({
        id: capability,
        label: $text(`settings.app_store.connected_accounts.capability_${capability}`),
        description: $text(`settings.app_store.connected_accounts.capability_${capability}_description`),
        checked: calendarCapabilitySelections[capability]
    })));
    let selectedCalendarCapabilities = $derived(
        CALENDAR_CAPABILITIES.filter((capability) => calendarCapabilitySelections[capability])
    );
    let calendarOAuthCapabilitySummary = $derived(
        selectedCalendarCapabilities.length
            ? selectedCalendarCapabilities
                .map((capability) => $text(`settings.app_store.connected_accounts.capability_${capability}`))
                .join(', ')
            : $text('settings.app_store.connected_accounts.no_capabilities_selected')
    );

    function updateCalendarCapability(id: string, checked: boolean) {
        if (!CALENDAR_CAPABILITIES.includes(id as CalendarCapability)) return;
        calendarCapabilitySelections[id as CalendarCapability] = checked;
    }
    
    /**
     * Convert a skill to an app-like metadata object for AppStoreCard.
     * This allows us to reuse AppStoreCard to display skills.
     *
     * Note: We use the appId (not skill.id) for the id field so that AppStoreCard
     * uses the correct app gradient for the card background.
     * When the skill has its own icon_image, that is used instead of the app icon,
     * so AppStoreCard renders the skill-specific icon with the grey skill gradient.
     */
    function skillToAppMetadata(skill: SkillMetadata, appId: string, app: AppMetadata): AppMetadata {
        return {
            id: appId, // Use appId so card background gradient matches the app
            name_translation_key: skill.name_translation_key,
            description_translation_key: skill.description_translation_key,
            // Use skill's own icon_image if available; fall back to app icon
            icon_image: skill.icon_image || app.icon_image,
            icon_colorgradient: app.icon_colorgradient,
            providers: skill.providers || [],
            skills: [],
            focus_modes: [],
            settings_and_memories: []
        };
    }

    function contentToAppMetadata(content: ContentEmbedCatalogItem, appId: string, app: AppMetadata): AppMetadata {
        return {
            id: appId,
            name: content.name,
            description: content.description,
            icon_image: `${content.icon || appId}.svg`,
            icon_colorgradient: app.icon_colorgradient,
            providers: [],
            skills: [],
            focus_modes: [],
            settings_and_memories: []
        };
    }
    
    /**
     * Get icon name from icon_image filename.
     * Maps icon_image like "ai.svg" to icon name "ai" for the Icon component.
     * Also handles special cases:
     * - "coding.svg" -> "code" (since the app ID is "code" but icon file is coding.svg)
     */
    function getIconName(iconImage: string | undefined): string {
        if (!iconImage) return appId;
        // Remove .svg extension and return the name
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
     * Handle skill card selection - navigate to skill details sub-page.
     */
    function handleSkillSelect(skillId: string) {
        dispatch('openSettings', {
            settingsPath: `apps/${appId}/skill/${skillId}`,
            direction: 'forward',
            icon: getIconName(app?.icon_image),
            title: $text(skills.find(s => s.id === skillId)?.name_translation_key || skillId)
        });
    }

    function handleContentSelect(contentTypeId: string) {
        const content = contentTypes.find((item) => item.contentTypeId === contentTypeId);
        dispatch('openSettings', {
            settingsPath: `apps/${appId}/content/${contentTypeId}`,
            direction: 'forward',
            icon: getIconName(app?.icon_image),
            title: content?.name || contentTypeId
        });
    }
    
    /**
     * Handle focus mode selection - navigate to focus mode details sub-page.
     */
    function handleFocusModeSelect(focusModeId: string) {
        dispatch('openSettings', {
            settingsPath: `apps/${appId}/focus/${focusModeId}`,
            direction: 'forward',
            icon: getIconName(app?.icon_image),
            title: $text(focusModes.find(f => f.id === focusModeId)?.name_translation_key || focusModeId)
        });
    }
    
    /**
     * Handle memories category selection - navigate to category details page.
     */
    function handleSettingsMemoriesCategorySelect(categoryId: string) {
        dispatch('openSettings', {
            settingsPath: `apps/${appId}/settings_memories/${categoryId}`,
            direction: 'forward',
            icon: getIconName(app?.icon_image),
            title: $text(visibleMemoryFields.find(c => c.id === categoryId)?.name_translation_key || categoryId)
        });
    }
    
    /**
     * Navigate back to Apps.
     */
    function goBack() {
        dispatch('openSettings', {
            settingsPath: 'apps',
            direction: 'back',
            icon: 'app',
            title: 'Apps'
        });
    }

    onMount(() => {
        if (appId !== 'calendar' || !isAuthenticated) return;
        void initializeCalendarConnectedAccounts();
    });

    $effect(() => {
        if (appId !== 'calendar' || !isAuthenticated) return;
        const handoffId = getOAuthHandoffId();
        const userId = $userProfile.user_id;
        if (!handoffId || !userId || finalizedOAuthHandoffId === handoffId || connectedAccountAction === 'finalizing') {
            return;
        }
        void initializeCalendarConnectedAccounts();
    });

    async function initializeCalendarConnectedAccounts() {
        await finalizeOAuthHandoffFromUrl();
        await loadConnectedCalendarAccounts(false);
    }

    async function loadConnectedCalendarAccounts(clearExistingError = true) {
        connectedAccountsLoading = true;
        if (clearExistingError) {
            connectedAccountError = '';
        }
        try {
            const providerHash = await computeSHA256('google_calendar');
            const rows = await listConnectedAccounts();
            connectedCalendarAccounts = rows.filter((row) => row.provider_type_hash === providerHash);
            connectedCalendarAccountSummaries = await summarizeConnectedAccountRows(connectedCalendarAccounts);
        } catch (error) {
            console.warn('[AppDetails] Failed to load Calendar connected accounts:', error);
            connectedAccountError = $text('settings.app_store.connected_accounts.load_error');
        } finally {
            connectedAccountsLoading = false;
        }
    }

    async function finalizeOAuthHandoffFromUrl() {
        const handoffId = getOAuthHandoffId();
        if (!handoffId) return;
        if (finalizedOAuthHandoffId === handoffId) return;
        const userId = $userProfile.user_id;
        if (!userId) {
            if (!isAuthenticated) {
                connectedAccountError = $text('settings.app_store.connected_accounts.sign_in_required');
            }
            return;
        }
        finalizedOAuthHandoffId = handoffId;
        connectedAccountAction = 'finalizing';
        connectedAccountError = '';
        try {
            await finalizeOAuthHandoffAsConnectedAccount({ userId, handoffId });
            connectedAccountSuccess = $text('settings.app_store.connected_accounts.connected_success');
            removeOAuthHandoffQueryParam();
        } catch (error) {
            console.warn('[AppDetails] Failed to finalize Calendar OAuth handoff:', error);
            connectedAccountError = $text('settings.app_store.connected_accounts.finalize_error');
        } finally {
            connectedAccountAction = 'idle';
        }
    }

    function getOAuthHandoffId(): string | null {
        if (typeof window === 'undefined') return null;
        return new URLSearchParams(window.location.search).get('oauth_handoff_id');
    }

    function removeOAuthHandoffQueryParam() {
        if (typeof window === 'undefined') return;
        const url = new URL(window.location.href);
        url.searchParams.delete('oauth_handoff_id');
        window.history.replaceState({}, '', url.toString());
    }

    async function connectGoogleCalendar() {
        if (selectedCalendarCapabilities.length === 0) return;
        connectedAccountAction = 'connecting';
        connectedAccountError = '';
        connectedAccountSuccess = '';
        try {
            const result = await startGoogleCalendarOAuth({
                capabilities: selectedCalendarCapabilities,
                returnPath: '/#settings/apps/calendar'
            });
            window.location.assign(result.authorization_url);
        } catch (error) {
            console.warn('[AppDetails] Failed to start Google Calendar OAuth:', error);
            connectedAccountAction = 'idle';
            connectedAccountError = $text('settings.app_store.connected_accounts.start_error');
        }
    }

    function openConnectedAccountsSettings() {
        dispatch('openSettings', {
            settingsPath: 'privacy/connected-accounts',
            direction: 'forward',
            icon: 'privacy',
            title: $text('settings.privacy.connected_accounts.title')
        });
    }
</script>

<div class="app-details">
    {#if !app}
        <div class="error">
            <p>App not found.</p>
            <button class="back-button" onclick={goBack}>← Back to Apps</button>
        </div>
    {:else}
        <!-- Skills section - only show if skills exist -->
        {#if skills.length > 0}
            <div class="section">
                <SettingsSectionHeading title={$text('settings.app_store.skills.title')} icon="skill" />
                <p class="section-description">{$text('settings.app_store.skills.section_description')}</p>
                <div class="items-scroll-container" data-testid="settings-skill-cards-scroll">
                    <div class="items-scroll">
                        {#each skills as skill (skill.id)}
                            {@const skillApp = skillToAppMetadata(skill, appId, app)}
                            <AppStoreCard
                                app={skillApp}
                                cardIconType="skill"
                                skillProviders={skill.providers}
                                onSelect={() => handleSkillSelect(skill.id)}
                            />
                        {/each}
                    </div>
                </div>
            </div>
        {/if}

        <!-- Content section - durable artifacts this app can create or display -->
        {#if contentTypes.length > 0}
            <div class="section">
                <SettingsSectionHeading title={$text('settings.app_store.content.title')} icon="embed" />
                <p class="section-description">{$text('settings.app_store.content.section_description')}</p>
                <div class="items-scroll-container" data-testid="settings-content-cards-scroll">
                    <div class="items-scroll">
                        {#each contentTypes as content (content.id)}
                            {@const contentApp = contentToAppMetadata(content, appId, app)}
                            <div data-testid={`content-embed-card-${content.id}`}>
                                <AppStoreCard
                                    app={contentApp}
                                    cardIconType="skill"
                                    onSelect={() => handleContentSelect(content.contentTypeId)}
                                />
                            </div>
                        {/each}
                    </div>
                </div>
            </div>
        {/if}

        <!-- Memories section - always show cards for each category -->
        {#if visibleMemoryFields.length > 0}
            <div class="section">
                <SettingsSectionHeading title={$text('settings.app_store.settings_memories.title')} icon="settings" />
                <p class="section-description">{$text('settings.app_store.settings_memories.section_description')}</p>
                <div class="items-scroll-container" data-testid="settings-memory-cards-scroll">
                    <div class="items-scroll">
                        {#each visibleMemoryFields as category (category.id)}
                            {@const categoryApp: AppMetadata = {
                                id: appId,
                                name_translation_key: category.name_translation_key,
                                description_translation_key: category.description_translation_key,
                                // Use category's own icon_image if available; fall back to app icon
                                icon_image: category.icon_image || app.icon_image,
                                icon_colorgradient: app.icon_colorgradient,
                                providers: [],
                                skills: [],
                                focus_modes: [],
                                settings_and_memories: []
                            }}
                            <AppStoreCard
                                app={categoryApp}
                                cardIconType="memory"
                                onSelect={() => handleSettingsMemoriesCategorySelect(category.id)}
                            />
                        {/each}
                    </div>
                </div>
            </div>
        {/if}
        
        <!-- Focus Modes section - only show if focus modes exist -->
        {#if focusModes.length > 0}
            <div class="section">
                <SettingsSectionHeading title={$text('settings.app_store.focus_modes.title')} icon="focus" />
                <p class="section-description">{$text('settings.app_store.focus_modes.section_description')}</p>
                <div class="items-scroll-container" data-testid="settings-focus-cards-scroll">
                    <div class="items-scroll">
                        {#each focusModes as focusMode (focusMode.id)}
                            {@const focusModeApp: AppMetadata = {
                                id: appId,
                                name_translation_key: focusMode.name_translation_key,
                                description_translation_key: focusMode.description_translation_key,
                                // Use focus mode's own icon_image if available; fall back to app icon
                                icon_image: focusMode.icon_image || app.icon_image,
                                icon_colorgradient: app.icon_colorgradient,
                                providers: [],
                                skills: [],
                                focus_modes: [],
                                settings_and_memories: []
                            }}
                            <AppStoreCard
                                app={focusModeApp}
                                cardIconType="focus"
                                onSelect={() => handleFocusModeSelect(focusMode.id)}
                            />
                        {/each}
                    </div>
                </div>
            </div>
        {/if}

        {#if isAuthenticated && appId === 'calendar'}
            <div class="section" data-testid="calendar-connected-accounts-section">
                <SettingsSectionHeading title={$text('settings.app_store.connected_accounts.title')} icon="calendar" />
                <p class="section-description">{$text('settings.app_store.connected_accounts.description')}</p>

                <SettingsCard>
                    <div class="connected-account-card">
                        <div>
                            <h3>{$text('settings.app_store.connected_accounts.google_calendar_title')}</h3>
                            <p>
                                {#if connectedAccountsLoading}
                                    {$text('settings.app_store.connected_accounts.loading')}
                                {:else if connectedCalendarAccounts.length > 0}
                                    {$text('settings.app_store.connected_accounts.connected_count', { values: { count: String(connectedCalendarAccounts.length) } })}
                                {:else}
                                    {$text('settings.app_store.connected_accounts.not_connected')}
                                {/if}
                            </p>
                            <div data-testid="calendar-capability-toggles">
                                <SettingsCheckboxList
                                    options={calendarCapabilityOptions}
                                    onChange={updateCalendarCapability}
                                />
                            </div>
                            <p data-testid="calendar-oauth-capability-summary">
                                {$text('settings.app_store.connected_accounts.oauth_summary', {
                                    values: { capabilities: calendarOAuthCapabilitySummary }
                                })}
                            </p>
                        </div>
                        <SettingsButton
                            dataTestid="connect-google-calendar-button"
                            loading={connectedAccountAction === 'connecting'}
                            disabled={connectedAccountAction !== 'idle' || selectedCalendarCapabilities.length === 0}
                            onClick={connectGoogleCalendar}
                        >
                            {$text('settings.app_store.connected_accounts.connect_button')}
                        </SettingsButton>
                    </div>
                </SettingsCard>

                {#if connectedCalendarAccountSummaries.length > 0}
                    <SettingsCard>
                        {#each connectedCalendarAccountSummaries as account (account.id)}
                            <div data-testid="calendar-connected-account-link">
                                <SettingsButton
                                    variant="ghost"
                                    fullWidth={true}
                                    dataTestid={`calendar-connected-account-detail-${account.id}`}
                                    onClick={openConnectedAccountsSettings}
                                >
                                    {$text('settings.app_store.connected_accounts.manage_account', {
                                        values: { label: account.label }
                                    })}
                                </SettingsButton>
                            </div>
                        {/each}
                    </SettingsCard>
                {/if}

                {#if connectedAccountAction === 'finalizing'}
                    <SettingsInfoBox type="info">
                        <p>{$text('settings.app_store.connected_accounts.finalizing')}</p>
                    </SettingsInfoBox>
                {/if}

                {#if connectedAccountSuccess}
                    <SettingsInfoBox type="success">
                        <p>{connectedAccountSuccess}</p>
                    </SettingsInfoBox>
                {/if}

                {#if connectedAccountError}
                    <SettingsInfoBox type="error">
                        <p>{connectedAccountError}</p>
                    </SettingsInfoBox>
                {/if}
            </div>
        {/if}
         
        <!-- Active Reminders section - only shown for reminder app, authenticated users -->
        {#if isAuthenticated && appId === 'reminder'}
            <div class="section">
                <SettingsSectionHeading title={$text('apps.reminder.active_reminders.title')} icon="reminder" />
                <ActiveRemindersList on:openSettings={(e) => dispatch('openSettings', e.detail)} />
            </div>
        {/if}
        
        <!-- My Embeds section - show all embeds generated by this app -->
        {#if isAuthenticated}
            <div class="section">
                <SettingsSectionHeading title={'My embeds'} icon="embed" />
                <div class="embeds-preview">
                    <AppEmbedsPanel appId={appId} />
                </div>
            </div>
        {/if}
    {/if}
</div>

<style>
    .app-details {
        padding: 14px;
        max-width: 1400px;
        margin: 0 auto;
    }
    
    .section {
        margin-top: 2rem;
        padding-left: 0;
    }

    /* Description text shown under section headings (Skills / Focus Modes / Memories) */
    .section-description {
        margin: 0.35rem 0 0.5rem 0;
        padding: 0;
        font-size: 0.9rem;
        line-height: 1.5;
        color: var(--color-font-secondary);
    }
    
    /* Ensure SettingsItem headings align with description text */
    .section :global(.menu-item.heading) {
        padding-left: 0;
        padding-right: 0;
    }
    
    /* Ensure items scroll container aligns with description */
    .section :global(.items-scroll-container) {
        margin-left: 0;
    }

    .embeds-preview {
        margin-top: 0.5rem;
        padding: 1rem;
        background: var(--color-grey-10);
        border-radius: var(--radius-3);
        border: 1px solid var(--color-grey-20);
    }

    .connected-account-card {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 1rem;
    }

    .connected-account-card h3 {
        margin: 0 0 0.25rem 0;
        font-size: var(--font-size-p, 0.875rem);
        color: var(--color-font-primary);
    }

    .connected-account-card p {
        margin: 0;
        color: var(--color-font-secondary);
        font-size: 0.875rem;
        line-height: 1.4;
    }

    @media (max-width: 640px) {
        .connected-account-card {
            align-items: stretch;
            flex-direction: column;
        }
    }

    .error {
        padding: 2rem;
        text-align: center;
        color: var(--error-color, #dc3545);
    }
    
    .items-scroll-container {
        overflow-x: auto;
        overflow-y: hidden;
        padding-bottom: 0.5rem;
        padding-left: 0;
        margin-top: 0.5rem;
        /* Match settings menu scrollbar style */
        scrollbar-width: thin;
        scrollbar-color: rgba(128, 128, 128, 0.2) transparent;
        transition: scrollbar-color var(--duration-normal) var(--easing-default);
    }
    
    .items-scroll-container:hover {
        scrollbar-color: rgba(128, 128, 128, 0.5) transparent;
    }
    
    .items-scroll-container::-webkit-scrollbar {
        height: 8px;
    }
    
    .items-scroll-container::-webkit-scrollbar-track {
        background: transparent;
    }
    
    .items-scroll-container::-webkit-scrollbar-thumb {
        background-color: rgba(128, 128, 128, 0.2);
        border-radius: var(--radius-1);
        border: 2px solid var(--color-grey-20);
        transition: background-color var(--duration-normal) var(--easing-default);
    }
    
    .items-scroll-container:hover::-webkit-scrollbar-thumb {
        background-color: rgba(128, 128, 128, 0.5);
    }
    
    .items-scroll-container::-webkit-scrollbar-thumb:hover {
        background-color: rgba(128, 128, 128, 0.7);
    }
    
    .items-scroll {
        display: flex;
        gap: 1rem;
        padding-right: 1rem;
        min-width: min-content;
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
</style>
