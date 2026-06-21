<!--
    Settings Interests Component - lets authenticated users edit encrypted
    account topic preferences used to personalize suggestions across devices.

    Native Swift counterparts:
    - apple/OpenMates/Sources/Features/Settings/Views/SettingsView.swift
-->
<script lang="ts">
    import { untrack } from 'svelte';
    import { text } from '@repo/ui';

    import { INTEREST_TAGS, type InterestTagId } from '../../../demo_chats/interestTags';
    import { saveAccountTopicPreferences } from '../../../services/topicPreferencesSync';
    import { userProfile } from '../../../stores/userProfile';
    import {
        SettingsButton,
        SettingsButtonGroup,
        SettingsCard,
        SettingsCheckboxList,
        SettingsInfoBox,
        SettingsPageContainer,
        SettingsPageHeader,
    } from '../elements';

    type CheckboxOption = {
        id: string;
        label: string;
        description?: string;
        icon?: string;
        checked: boolean;
    };

    let selectedTagIds = $state<InterestTagId[]>([]);
    let initialTagIds = $state<InterestTagId[]>([]);
    let isSaving = $state(false);
    let successMessage = $state<string | null>(null);
    let errorMessage = $state<string | null>(null);

    let selectedKey = $derived(selectedTagIds.join('|'));
    let initialKey = $derived(initialTagIds.join('|'));
    let hasChanges = $derived(selectedKey !== initialKey);

    let checkboxOptions = $state<CheckboxOption[]>([]);

    function refreshCheckboxOptions() {
        checkboxOptions = INTEREST_TAGS.map((tag) => ({
            id: tag.id,
            label: $text(tag.labelKey),
            icon: tag.icon,
            checked: selectedTagIds.includes(tag.id),
        }));
    }

    $effect(() => {
        const profileTagIds = $userProfile.topic_preferences?.selectedTagIds ?? [];
        selectedTagIds = [...profileTagIds];
        initialTagIds = [...profileTagIds];
        untrack(refreshCheckboxOptions);
    });

    function handleTagChange(id: string, checked: boolean) {
        successMessage = null;
        errorMessage = null;

        if (checked) {
            selectedTagIds = Array.from(new Set([...selectedTagIds, id as InterestTagId]));
        } else {
            selectedTagIds = selectedTagIds.filter((tagId) => tagId !== id);
        }
        refreshCheckboxOptions();
    }

    async function handleSave() {
        if (!hasChanges || isSaving) return;

        isSaving = true;
        successMessage = null;
        errorMessage = null;

        try {
            const savedPayload = await saveAccountTopicPreferences(selectedTagIds);
            selectedTagIds = [...savedPayload.selectedTagIds];
            initialTagIds = [...savedPayload.selectedTagIds];
            refreshCheckboxOptions();
            successMessage = $text('settings.account.interests_saved');
        } catch (error) {
            console.error('[SettingsInterests] Failed to save topic preferences:', error);
            errorMessage = $text('settings.account.interests_save_error');
        } finally {
            isSaving = false;
        }
    }
</script>

<SettingsPageContainer>
    <SettingsPageHeader
        title={$text('settings.account.interests')}
        description={$text('settings.account.interests_description')}
    />

    <SettingsInfoBox type="info">
        {$text('settings.account.interests_privacy_note')}
    </SettingsInfoBox>

    {#if successMessage}
        <SettingsInfoBox type="success">
            {successMessage}
        </SettingsInfoBox>
    {/if}

    {#if errorMessage}
        <SettingsInfoBox type="error">
            {errorMessage}
        </SettingsInfoBox>
    {/if}

    <SettingsCard>
        <SettingsCheckboxList
            bind:options={checkboxOptions}
            dataTestid="account-interests-list"
            onChange={handleTagChange}
        />
    </SettingsCard>

    <SettingsButtonGroup>
        <SettingsButton
            variant="primary"
            loading={isSaving}
            disabled={!hasChanges || isSaving}
            dataTestid="account-interests-save"
            onClick={handleSave}
        >
            {$text('common.save')}
        </SettingsButton>
    </SettingsButtonGroup>
</SettingsPageContainer>
