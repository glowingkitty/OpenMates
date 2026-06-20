<!--
    SettingsLearningModeSetup — Account-wide Learning Mode setup page.

    Uses canonical settings/elements form primitives instead of browser prompt,
    alert, or confirm overlays. Keeps activation/deactivation backend-backed so
    Learning Mode cannot be bypassed by clearing browser state. Opened from the
    main settings Learning Mode quick row as a deep-linked sub-settings page.
-->
<script lang="ts">
    import { text } from '@repo/ui';
    import { createEventDispatcher } from 'svelte';
    import { learningMode, type LearningModeAgeGroup } from '../../../stores/learningModeStore';
    import { notificationStore } from '../../../stores/notificationStore';
    import {
        SettingsButton,
        SettingsButtonGroup,
        SettingsDropdown,
        SettingsInfoBox,
        SettingsInput,
        SettingsPageContainer,
        SettingsPageHeader,
        SettingsSectionHeading,
    } from '../elements';

    const dispatch = createEventDispatcher();

    let ageGroupOptions = $derived<Array<{ value: LearningModeAgeGroup; label: string }>>([
        { value: 'under_10', label: $text('settings.learning_mode_age_under_10') },
        { value: '10_12', label: $text('settings.learning_mode_age_10_12') },
        { value: '13_15', label: $text('settings.learning_mode_age_13_15') },
        { value: '16_18', label: $text('settings.learning_mode_age_16_18') },
        { value: 'adult', label: $text('settings.learning_mode_age_adult') },
    ]);

    let selectedAgeGroup = $state('13_15');
    let passcode = $state('');
    let isSubmitting = $state(false);
    let formError = $state('');

    $effect(() => {
        if ($learningMode.enabled && $learningMode.age_group) {
            selectedAgeGroup = $learningMode.age_group;
        }
    });

    $effect(() => {
        if ($learningMode.loaded || $learningMode.loading) return;
        learningMode.load().catch((error) => {
            console.error('[SettingsLearningModeSetup] Failed to load Learning Mode status:', error);
            formError = $text('settings.learning_mode_load_error');
        });
    });

    function navigateBack() {
        dispatch('openSettings', {
            settingsPath: 'main',
            direction: 'backward',
            icon: '',
            title: '',
        });
    }

    async function handleSubmit() {
        const trimmedPasscode = passcode.trim();
        if (!trimmedPasscode) {
            formError = $text('settings.learning_mode_passcode_required');
            return;
        }

        formError = '';
        isSubmitting = true;
        try {
            if ($learningMode.enabled) {
                await learningMode.deactivate(trimmedPasscode);
                notificationStore.success($text('settings.learning_mode_disabled'));
                passcode = '';
                navigateBack();
                return;
            }

            await learningMode.activate(trimmedPasscode, selectedAgeGroup as LearningModeAgeGroup);
            notificationStore.success($text('settings.learning_mode_enabled'));
            passcode = '';
            navigateBack();
        } catch (error) {
            console.error('[SettingsLearningModeSetup] Learning Mode update failed:', error);
            formError = error instanceof Error ? error.message : $text('settings.learning_mode_save_error');
        } finally {
            isSubmitting = false;
        }
    }
</script>

<div data-testid="learning-mode-settings-page">
<SettingsPageContainer>
    <SettingsPageHeader
        title={$text('settings.learning_mode')}
        description={$learningMode.enabled
            ? $text('settings.learning_mode_disable_description')
            : $text('settings.learning_mode_enable_description')}
    />

    {#if formError}
        <SettingsInfoBox type="error" ariaLabel={$text('settings.learning_mode_save_error')}>
            <p>{formError}</p>
        </SettingsInfoBox>
    {:else if $learningMode.enabled}
        <SettingsInfoBox type="warning" ariaLabel={$text('settings.learning_mode_active')}>
            <p>{$text('settings.learning_mode_active_detail')}</p>
        </SettingsInfoBox>
    {:else}
        <SettingsInfoBox type="info" ariaLabel={$text('settings.learning_mode_inactive')}>
            <p>{$text('settings.learning_mode_inactive_detail')}</p>
        </SettingsInfoBox>
    {/if}

    {#if !$learningMode.enabled}
        <SettingsSectionHeading title={$text('settings.learning_mode_age_group_label')} icon="user" />
        <SettingsDropdown
            bind:value={selectedAgeGroup}
            options={ageGroupOptions}
            name="learning-mode-age-group"
            dataTestid="learning-mode-age-group-dropdown"
            ariaLabel={$text('settings.learning_mode_age_group_label')}
        />
    {/if}

    <SettingsSectionHeading title={$learningMode.enabled
        ? $text('settings.learning_mode_disable_passcode_label')
        : $text('settings.learning_mode_enable_passcode_label')} icon="lock" />
    <SettingsInput
        bind:value={passcode}
        type="password"
        name="learning-mode-passcode"
        autocomplete="new-password"
        dataTestid="learning-mode-passcode-input"
        placeholder={$learningMode.enabled
            ? $text('settings.learning_mode_disable_passcode_placeholder')
            : $text('settings.learning_mode_enable_passcode_placeholder')}
        ariaLabel={$learningMode.enabled
            ? $text('settings.learning_mode_disable_passcode_label')
            : $text('settings.learning_mode_enable_passcode_label')}
        onKeydown={(event) => {
            if (event.key === 'Enter') {
                event.preventDefault();
                handleSubmit();
            }
        }}
    />

    <SettingsButtonGroup align="left">
        <SettingsButton
            variant={$learningMode.enabled ? 'danger' : 'primary'}
            fullWidth={true}
            loading={isSubmitting || $learningMode.loading}
            disabled={!passcode.trim()}
            dataTestid={$learningMode.enabled ? 'learning-mode-disable-button' : 'learning-mode-enable-button'}
            onClick={handleSubmit}
        >
            {$learningMode.enabled ? $text('settings.learning_mode_disable_button') : $text('settings.learning_mode_enable_button')}
        </SettingsButton>
        <SettingsButton variant="ghost" fullWidth={true} dataTestid="learning-mode-cancel-button" onClick={navigateBack}>
            {$text('common.cancel')}
        </SettingsButton>
    </SettingsButtonGroup>
</SettingsPageContainer>
</div>
