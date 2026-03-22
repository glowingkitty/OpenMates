<!-- frontend/packages/ui/src/components/settings/SettingsMates.svelte
     Mates settings page — vertical list of all available AI mates.

     Layout:
     - One row per mate: profile image (circular, from mates.css), name (primary colour),
       short expertise description, and a right-pointing chevron arrow.
     - Clicking a row navigates forward to mates/{mateId} (the MateDetailsWrapper).

     Data source: static matesMetadata.ts — no store or API call needed.
-->

<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import { text } from '@repo/ui';
    import { matesMetadata } from '../../data/matesMetadata';

    // Event dispatcher — forwards openSettings navigation events to Settings.svelte
    const dispatch = createEventDispatcher();

    /**
     * Navigate to the detail page for a specific mate.
     * Uses the same "forward" navigation pattern as AppStoreCard → AppDetails.
     */
    function openMateDetails(mateId: string) {
        dispatch('openSettings', {
            settingsPath: `mates/${mateId}`,
            direction: 'forward',
            icon: 'mates',
            title: '',   // Settings.svelte will resolve the title from mates.{mateId} translation key
        });
    }
</script>

<div class="settings-mates">
    {#each matesMetadata as mate (mate.id)}
        <button
            class="mate-row"
            type="button"
            onclick={() => openMateDetails(mate.id)}
            aria-label={$text(mate.name_translation_key)}
        >
            <!-- Profile image — uses existing .mate-profile CSS class from mates.css -->
            <div class="mate-profile {mate.profile_class} mate-profile-settings"></div>

            <!-- Name + description text block -->
            <div class="mate-text">
                <span class="mate-name">{$text(mate.name_translation_key)}</span>
                <span class="mate-description">{$text(mate.description_translation_key)}</span>
            </div>

            <!-- Right chevron arrow -->
            <div class="mate-chevron"></div>
        </button>
    {/each}
</div>

<style>
    .settings-mates {
        padding: 8px 0 3rem 0;
        display: flex;
        flex-direction: column;
    }

    /* Each mate is a full-width clickable row.
       Must reset properties leaked by the global `button { }` rule in buttons.css:
       height, min-width, filter, margin-right, and scale hover/active transforms. */
    .mate-row {
        display: flex;
        align-items: center;
        gap: 0;
        padding: 6px 12px 6px 0;
        background: none;
        border: none;
        cursor: pointer;
        width: 100%;
        text-align: left;
        border-radius: 8px;
        transition: background 0.15s ease;
        /* Reset global button rule leakage */
        height: auto;
        min-width: 0;
        filter: none;
        margin: 0;
    }

    .mate-row:hover {
        background: var(--color-grey-15, rgba(0, 0, 0, 0.05));
        /* Neutralise global button:hover { scale: 1.02 } */
        scale: 1;
    }

    .mate-row:active {
        background: var(--color-grey-20, rgba(0, 0, 0, 0.1));
        /* Neutralise global button:active { scale: 0.98 } */
        scale: 1;
        filter: none;
    }

    /*
     * Override the default .mate-profile size for the settings list.
     * The base class (from mates.css) sets 60px; we want a slightly smaller
     * avatar in the compact list view, and suppress the AI badge pseudo-elements.
     */
    :global(.mate-profile.mate-profile-settings) {
        width: 46px;
        height: 46px;
        margin: 6px 12px 6px 10px;
        flex-shrink: 0;
    }

    /* Hide the AI badge (::before / ::after) in the settings list */
    :global(.mate-profile.mate-profile-settings::before),
    :global(.mate-profile.mate-profile-settings::after) {
        display: none;
    }

    .mate-text {
        flex: 1;
        display: flex;
        flex-direction: column;
        gap: 2px;
        min-width: 0;
    }

    .mate-name {
        font-size: 0.95rem;
        font-weight: 600;
        color: var(--color-primary, #6364FF);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }

    .mate-description {
        font-size: 0.8rem;
        color: var(--color-grey-60, #666);
        line-height: 1.3;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }

    /* Chevron arrow — thin right-pointing arrow matching SettingsItem style */
    .mate-chevron {
        width: 8px;
        height: 8px;
        border-right: 2px solid var(--color-grey-50, #999);
        border-top: 2px solid var(--color-grey-50, #999);
        transform: rotate(45deg);
        flex-shrink: 0;
        margin-left: 8px;
    }
</style>
