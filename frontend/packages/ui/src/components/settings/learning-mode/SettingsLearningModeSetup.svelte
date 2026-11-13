<!-- Native Swift counterparts: apple/OpenMates/Sources/Features/Settings/Views/SettingsLearningModeView.swift -->
<!--
    SettingsLearningModeSetup — Account-wide Learning Mode setup page.

    Uses canonical settings/elements form primitives instead of browser prompt,
    alert, or confirm overlays. Accounts keep activation/deactivation
    backend-backed so Learning Mode cannot be bypassed by clearing browser state.
    Guests get a browser-local, passcode-locked Learning Mode (never sent to the
    server) and an honest notice about its limits. "Allow collaborative building"
    is on by default, hidden and forced off for under-10 learners, can be turned
    off freely, and needs the passcode to be turned on again. Opened from the
    main settings Learning Mode quick row as a deep-linked sub-settings page.
-->
<script lang="ts">
    import { text } from '@repo/ui';
    import { createEventDispatcher } from 'svelte';
    import {
        learningMode,
        LearningModeRequestError,
        MAX_FAILED_PASSCODE_ATTEMPTS,
        type LearningModeAgeGroup,
    } from '../../../stores/learningModeStore';
    import { authStore } from '../../../stores/authStore';
    import { notificationStore } from '../../../stores/notificationStore';
    import {
        SettingsButton,
        SettingsButtonGroup,
        SettingsDropdown,
        SettingsInfoBox,
        SettingsInput,
        SettingsItem,
        SettingsPageContainer,
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
    let collaborativeBuild = $state(true);
    let collaborativePrompt = $state(false);
    let collaborativePasscode = $state('');
    let previousAgeGroup = '13_15';
    let isSubmitting = $state(false);
    let formError = $state('');
    let isAuthenticated = $derived($authStore.isAuthenticated);

    let isUnderTen = $derived(selectedAgeGroup === 'under_10');
    let collaborativeToggleVisible = $derived(
        !isUnderTen && ($learningMode.enabled ? $learningMode.age_group !== 'under_10' : true)
    );

    $effect(() => {
        if ($learningMode.enabled && $learningMode.age_group) {
            selectedAgeGroup = $learningMode.age_group;
        }
    });

    // Collaborative building is forced off for under-10 learners and returns to
    // its default (on) when the user picks an older age group again.
    $effect(() => {
        const current = selectedAgeGroup;
        if (current === previousAgeGroup) return;
        collaborativeBuild = current !== 'under_10';
        previousAgeGroup = current;
    });

    $effect(() => {
        if (!isAuthenticated) {
            if ($learningMode.source === 'guest_session' || $learningMode.loading) return;
            learningMode.loadGuest();
            return;
        }
        if (($learningMode.loaded && $learningMode.source === 'account') || $learningMode.loading) return;
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

    function describeError(error: unknown): string {
        if (error instanceof LearningModeRequestError) {
            if (error.reason === 'blocked') return $text('settings.learning_mode_locked');
            if (error.reason === 'wrong_passcode') {
                const remaining = Math.max(0, MAX_FAILED_PASSCODE_ATTEMPTS - $learningMode.failed_attempts);
                return $text('settings.learning_mode_attempts_remaining', { values: { count: remaining } });
            }
            if (error.reason === 'invalid_passcode') return $text('settings.learning_mode_passcode_invalid');
        }
        return $text('settings.learning_mode_save_error');
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
                if (isAuthenticated) {
                    await learningMode.deactivate(trimmedPasscode);
                } else {
                    await learningMode.deactivateGuest(trimmedPasscode);
                }
                notificationStore.success($text('settings.learning_mode_disabled'));
                passcode = '';
                navigateBack();
                return;
            }

            const ageGroup = selectedAgeGroup as LearningModeAgeGroup;
            const allowCollaborative = ageGroup !== 'under_10' && collaborativeBuild;
            if (isAuthenticated) {
                await learningMode.activate(trimmedPasscode, ageGroup, allowCollaborative);
            } else {
                await learningMode.activateGuest(trimmedPasscode, ageGroup, allowCollaborative);
            }
            notificationStore.success($text('settings.learning_mode_enabled'));
            passcode = '';
            navigateBack();
        } catch (error) {
            console.error('[SettingsLearningModeSetup] Learning Mode update failed:', error);
            formError = describeError(error);
        } finally {
            isSubmitting = false;
        }
    }

    async function applyCollaborativeBuild(enabled: boolean, enteredPasscode?: string) {
        formError = '';
        isSubmitting = true;
        try {
            if (isAuthenticated) {
                await learningMode.setCollaborativeBuild(enabled, enteredPasscode);
            } else {
                await learningMode.setGuestCollaborativeBuild(enabled, enteredPasscode);
            }
            collaborativePrompt = false;
            collaborativePasscode = '';
            notificationStore.success(enabled
                ? $text('settings.learning_mode_collaborative_enabled')
                : $text('settings.learning_mode_collaborative_disabled'));
        } catch (error) {
            console.error('[SettingsLearningModeSetup] Collaborative building update failed:', error);
            formError = describeError(error);
        } finally {
            isSubmitting = false;
        }
    }

    function handleCollaborativeToggle() {
        if (!$learningMode.enabled) {
            collaborativeBuild = !collaborativeBuild;
            return;
        }
        if ($learningMode.collaborative_build) {
            // Turning collaborative building off is free.
            collaborativePrompt = false;
            collaborativePasscode = '';
            void applyCollaborativeBuild(false);
            return;
        }
        collaborativePrompt = !collaborativePrompt;
    }

    function confirmCollaborativeOn() {
        const trimmedPasscode = collaborativePasscode.trim();
        if (!trimmedPasscode) {
            formError = $text('settings.learning_mode_passcode_required');
            return;
        }
        void applyCollaborativeBuild(true, trimmedPasscode);
    }
</script>

<div data-testid="learning-mode-settings-page">
<SettingsPageContainer>
    {#if formError}
        <SettingsInfoBox type="error" ariaLabel={$text('settings.learning_mode_save_error')}>
            <p>{formError}</p>
        </SettingsInfoBox>
    {:else if $learningMode.enabled}
        <SettingsInfoBox type="warning" ariaLabel={$text('settings.learning_mode_active')}>
            <p>{isAuthenticated ? $text('settings.learning_mode_active_detail') : $text('settings.learning_mode_guest_active_detail')}</p>
        </SettingsInfoBox>
    {:else}
        <SettingsInfoBox type="info" ariaLabel={$text('settings.learning_mode_inactive')}>
            <p>{isAuthenticated ? $text('settings.learning_mode_inactive_detail') : $text('settings.learning_mode_guest_inactive_detail')}</p>
        </SettingsInfoBox>
    {/if}

    {#if !isAuthenticated}
        <SettingsInfoBox type="warning" ariaLabel={$text('settings.learning_mode_guest_notice')} data-testid="learning-mode-guest-notice">
            <p>{$text('settings.learning_mode_guest_notice')}</p>
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

    {#if collaborativeToggleVisible}
        <SettingsItem
            type="quickaction"
            icon="study"
            title={$text('settings.learning_mode_collaborative_label')}
            subtitleTop={$text('settings.learning_mode_collaborative_help')}
            hasToggle={true}
            checked={$learningMode.enabled ? $learningMode.collaborative_build : collaborativeBuild}
            disabled={isSubmitting || $learningMode.loading}
            data-testid="learning-mode-collaborative"
            onClick={handleCollaborativeToggle}
        />
    {/if}

    {#if collaborativePrompt && $learningMode.enabled && !$learningMode.collaborative_build}
        <SettingsSectionHeading title={$text('settings.learning_mode_collaborative_enable_prompt')} icon="lock" />
        <SettingsInput
            bind:value={collaborativePasscode}
            type="password"
            name="learning-mode-collaborative-passcode"
            autocomplete="current-password"
            dataTestid="learning-mode-collaborative-passcode-input"
            placeholder={$text('settings.learning_mode_disable_passcode_placeholder')}
            ariaLabel={$text('settings.learning_mode_collaborative_enable_prompt')}
            onKeydown={(event) => {
                if (event.key === 'Enter') {
                    event.preventDefault();
                    confirmCollaborativeOn();
                }
            }}
        />
        <SettingsButtonGroup align="left">
            <SettingsButton
                variant="primary"
                fullWidth={true}
                loading={isSubmitting}
                disabled={!collaborativePasscode.trim()}
                dataTestid="learning-mode-collaborative-confirm-button"
                onClick={confirmCollaborativeOn}
            >
                {$text('settings.learning_mode_collaborative_confirm_button')}
            </SettingsButton>
        </SettingsButtonGroup>
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
