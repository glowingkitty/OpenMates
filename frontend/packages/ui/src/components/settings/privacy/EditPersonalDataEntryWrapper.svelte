<!--
Edit Personal Data Entry Wrapper — router wrapper for edit routes.

Parses the active settings path to extract the entry type and ID, then
renders the appropriate edit component (name / address / birthday / custom).

Route patterns:
  privacy/hide-personal-data/edit-name/{entryId}
  privacy/hide-personal-data/edit-address/{entryId}
  privacy/hide-personal-data/edit-birthday/{entryId}
  privacy/hide-personal-data/edit-custom/{entryId}

This wrapper follows the same pattern as AppDetailsWrapper.svelte for
encoding structured data (entryId) into the settingsPath string.

Architecture context: docs/architecture/pii-protection.md
Related to: SettingsEditName, SettingsEditAddress, SettingsEditBirthday, SettingsEditCustomEntry
-->

<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import SettingsEditName from './SettingsEditName.svelte';
    import SettingsEditAddress from './SettingsEditAddress.svelte';
    import SettingsEditBirthday from './SettingsEditBirthday.svelte';
    import SettingsEditCustomEntry from './SettingsEditCustomEntry.svelte';

    const dispatch = createEventDispatcher();

    // ─── Props ───────────────────────────────────────────────────────────────

    interface Props {
        activeSettingsView?: string;
        accountId?: string;
    }

    let { activeSettingsView = '' }: Props = $props();

    // ─── Route Parsing ───────────────────────────────────────────────────────

    /**
     * Parse the active settings path to extract entryType and entryId.
     *
     * Expected formats:
     *   privacy/hide-personal-data/edit-name/{entryId}
     *   privacy/hide-personal-data/edit-address/{entryId}
     *   privacy/hide-personal-data/edit-birthday/{entryId}
     *   privacy/hide-personal-data/edit-custom/{entryId}
     */
    let routeInfo = $derived.by(() => {
        const parts = activeSettingsView.split('/');
        // parts[0] = 'privacy', parts[1] = 'hide-personal-data', parts[2] = 'edit-*', parts[3] = entryId
        if (parts.length !== 4 || parts[0] !== 'privacy' || parts[1] !== 'hide-personal-data') {
            return null;
        }

        const editSegment = parts[2];
        const entryId = parts[3];

        if (!entryId) return null;

        if (editSegment === 'edit-name') return { type: 'name', entryId };
        if (editSegment === 'edit-address') return { type: 'address', entryId };
        if (editSegment === 'edit-birthday') return { type: 'birthday', entryId };
        if (editSegment === 'edit-custom') return { type: 'custom', entryId };

        return null;
    });

    // ─── Event forwarding ────────────────────────────────────────────────────

    function handleOpenSettings(event: CustomEvent) {
        dispatch('openSettings', event.detail);
    }
</script>

{#if routeInfo}
    {#if routeInfo.type === 'name'}
        <SettingsEditName
            entryId={routeInfo.entryId}
            on:openSettings={handleOpenSettings}
        />
    {:else if routeInfo.type === 'address'}
        <SettingsEditAddress
            entryId={routeInfo.entryId}
            on:openSettings={handleOpenSettings}
        />
    {:else if routeInfo.type === 'birthday'}
        <SettingsEditBirthday
            entryId={routeInfo.entryId}
            on:openSettings={handleOpenSettings}
        />
    {:else if routeInfo.type === 'custom'}
        <SettingsEditCustomEntry
            entryId={routeInfo.entryId}
            on:openSettings={handleOpenSettings}
        />
    {/if}
{/if}
