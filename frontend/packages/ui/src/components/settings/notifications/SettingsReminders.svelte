<!--
  SettingsReminders.svelte

  Reminder management settings page. Allows users to create new reminders
  and view active (pending) reminders. Uses canonical settings design elements.

  Opened via:
  - Chat top bar bell button (deep link: notifications/reminders)
  - Settings → Notifications → Reminders

  API: POST /v1/apps/reminder/skills/set-reminder (creation)
  API: GET /v1/settings/reminders (list, via ActiveRemindersList)

  Architecture: docs/architecture/ai/reminder.md
-->

<script lang="ts">
    import { text } from '@repo/ui';
    import { userProfile } from '../../../stores/userProfile';
    import { getApiUrl } from '../../../config/api';
    import SettingsPageContainer from '../elements/SettingsPageContainer.svelte';
    import SettingsPageHeader from '../elements/SettingsPageHeader.svelte';
    import SettingsInput from '../elements/SettingsInput.svelte';
    import SettingsTextarea from '../elements/SettingsTextarea.svelte';
    import SettingsDropdown from '../elements/SettingsDropdown.svelte';
    import SettingsButton from '../elements/SettingsButton.svelte';
    import SettingsDivider from '../elements/SettingsDivider.svelte';
    import SettingsInfoBox from '../elements/SettingsInfoBox.svelte';
    import ActiveRemindersList from '../appSettings/ActiveRemindersList.svelte';

    // ─── Form state ────────────────────────────────────────────────────────────

    let date = $state('');
    let time = $state('');
    let note = $state('');
    let responseType = $state<'simple' | 'full'>('simple');
    let actionPrompt = $state('');
    let repeatType = $state('none');
    let customInterval = $state('1');
    let customUnit = $state('days');
    let endDate = $state('');

    let isSubmitting = $state(false);
    let errorMessage = $state('');
    let successMessage = $state('');
    let refreshTrigger = $state(0);

    // ─── Derived ───────────────────────────────────────────────────────────────

    /** Timezone from user profile, falling back to browser timezone. */
    let timezone = $derived(
        $userProfile.timezone || Intl.DateTimeFormat().resolvedOptions().timeZone
    );

    /** Today's date string (YYYY-MM-DD) used as the min value for date inputs. */
    let todayStr = $derived(() => {
        const d = new Date();
        return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
    });

    let showCustomRepeat = $derived(repeatType === 'custom');

    /** Repeat type dropdown options */
    const repeatOptions = [
        { value: 'none', label: '' },
        { value: 'daily', label: '' },
        { value: 'weekly', label: '' },
        { value: 'monthly', label: '' },
        { value: 'custom', label: '' },
    ];

    /** Custom repeat unit dropdown options */
    const customUnitOptions = [
        { value: 'days', label: '' },
        { value: 'weeks', label: '' },
        { value: 'months', label: '' },
    ];

    /** Response type dropdown options */
    const responseTypeOptions = [
        { value: 'simple', label: '' },
        { value: 'full', label: '' },
    ];

    // Populate labels reactively (need $text which is reactive)
    $effect(() => {
        repeatOptions[0].label = $text('reminder.panel.repeat_none');
        repeatOptions[1].label = $text('reminder.panel.repeat_daily');
        repeatOptions[2].label = $text('reminder.panel.repeat_weekly');
        repeatOptions[3].label = $text('reminder.panel.repeat_monthly');
        repeatOptions[4].label = $text('reminder.panel.repeat_custom');

        customUnitOptions[0].label = $text('reminder.panel.repeat_days');
        customUnitOptions[1].label = $text('reminder.panel.repeat_weeks');
        customUnitOptions[2].label = $text('reminder.panel.repeat_months');

        responseTypeOptions[0].label = $text('reminder.panel.type_notification');
        responseTypeOptions[1].label = $text('reminder.panel.type_action');
    });

    // ─── Submission ────────────────────────────────────────────────────────────

    async function handleSubmit() {
        errorMessage = '';
        successMessage = '';

        if (!date || !time) return;

        // Validate that the chosen date/time is in the future
        const triggerDatetime = `${date}T${time}:00`;
        const triggerMs = new Date(triggerDatetime).getTime();
        if (triggerMs <= Date.now()) {
            errorMessage = $text('reminder.panel.error_past');
            return;
        }

        isSubmitting = true;

        try {
            const prompt = responseType === 'full' && actionPrompt.trim()
                ? actionPrompt.trim()
                : (note.trim() || $text('reminder.panel.note_placeholder'));

            const body: Record<string, unknown> = {
                prompt,
                trigger_type: 'specific',
                trigger_datetime: triggerDatetime,
                timezone,
                target_type: 'new_chat',
                response_type: responseType,
                new_chat_title: prompt.slice(0, 50),
            };

            if (repeatType !== 'none') {
                const repeat: Record<string, unknown> = { type: repeatType };
                if (repeatType === 'custom') {
                    repeat.interval = parseInt(customInterval) || 1;
                    repeat.interval_unit = customUnit;
                }
                if (endDate) {
                    repeat.end_date = endDate;
                }
                body.repeat = repeat;
            }

            const response = await fetch(`${getApiUrl()}/v1/apps/reminder/skills/set-reminder`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify(body),
            });

            if (!response.ok) {
                let detail = `${response.status}`;
                try {
                    const err = await response.json();
                    detail = err.detail || err.error || detail;
                } catch { /* ignore */ }
                errorMessage = $text('reminder.panel.error_generic');
                console.error('[SettingsReminders] API error:', detail);
                return;
            }

            // Success — reset form and refresh list
            successMessage = $text('reminder.settings.success');
            date = '';
            time = '';
            note = '';
            actionPrompt = '';
            responseType = 'simple';
            repeatType = 'none';
            customInterval = '1';
            customUnit = 'days';
            endDate = '';
            refreshTrigger++;

            // Clear success message after 5 seconds
            setTimeout(() => { successMessage = ''; }, 5000);
        } catch (err) {
            errorMessage = $text('reminder.panel.error_generic');
            console.error('[SettingsReminders] fetch error:', err);
        } finally {
            isSubmitting = false;
        }
    }
</script>

<SettingsPageContainer>
    <SettingsPageHeader
        title={$text('reminder.settings.title')}
        description={$text('reminder.settings.description')}
    />

    <!-- Create new reminder form -->
    <h3 class="section-heading">{$text('reminder.settings.create_title')}</h3>

    <div class="form-row">
        <div class="form-field">
            <label class="field-label" for="settings-reminder-date">{$text('reminder.panel.date')}</label>
            <input
                id="settings-reminder-date"
                class="native-input"
                type="date"
                bind:value={date}
                min={todayStr()}
            />
        </div>
        <div class="form-field">
            <label class="field-label" for="settings-reminder-time">{$text('reminder.panel.time')}</label>
            <input
                id="settings-reminder-time"
                class="native-input"
                type="time"
                bind:value={time}
            />
        </div>
    </div>

    <SettingsDropdown
        bind:value={responseType}
        options={responseTypeOptions}
        ariaLabel={$text('reminder.panel.type_notification')}
    />

    {#if responseType === 'simple'}
        <SettingsInput
            bind:value={note}
            placeholder={$text('reminder.panel.note_placeholder')}
            ariaLabel={$text('reminder.panel.note')}
        />
    {:else}
        <SettingsTextarea
            bind:value={actionPrompt}
            placeholder={$text('reminder.panel.action_prompt_placeholder')}
            ariaLabel={$text('reminder.panel.action_prompt_label')}
            rows={4}
        />
    {/if}

    <SettingsDropdown
        bind:value={repeatType}
        options={repeatOptions}
        ariaLabel={$text('reminder.panel.repeat')}
    />

    {#if showCustomRepeat}
        <div class="form-row">
            <div class="form-field">
                <label class="field-label" for="settings-reminder-interval">{$text('reminder.panel.repeat_every')}</label>
                <input
                    id="settings-reminder-interval"
                    class="native-input"
                    type="number"
                    min="1"
                    bind:value={customInterval}
                />
            </div>
            <div class="form-field form-field-grow">
                <SettingsDropdown
                    bind:value={customUnit}
                    options={customUnitOptions}
                    ariaLabel={$text('reminder.panel.repeat_days')}
                />
            </div>
        </div>
    {/if}

    {#if repeatType !== 'none'}
        <div class="form-field">
            <label class="field-label" for="settings-reminder-end-date">{$text('reminder.panel.end_date')}</label>
            <input
                id="settings-reminder-end-date"
                class="native-input"
                type="date"
                bind:value={endDate}
                min={todayStr()}
            />
        </div>
    {/if}

    {#if errorMessage}
        <SettingsInfoBox type="error">{errorMessage}</SettingsInfoBox>
    {/if}

    {#if successMessage}
        <SettingsInfoBox type="success">{successMessage}</SettingsInfoBox>
    {/if}

    <SettingsButton
        variant="primary"
        loading={isSubmitting}
        disabled={!date || !time}
        onClick={handleSubmit}
    >
        {isSubmitting ? $text('reminder.panel.setting') : $text('reminder.panel.submit')}
    </SettingsButton>

    <SettingsDivider />

    <!-- Active reminders list -->
    <h3 class="section-heading">{$text('reminder.settings.active_title')}</h3>
    <ActiveRemindersList {refreshTrigger} />
</SettingsPageContainer>

<style>
    .section-heading {
        font-family: 'Lexend Deca Variable', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        font-size: var(--font-size-h3, 1.125rem);
        font-weight: 600;
        color: var(--color-font-primary);
        margin: 0.5rem 0.625rem 0.75rem;
    }

    .form-row {
        display: flex;
        gap: 0.75rem;
        padding: 0 0.625rem;
    }

    .form-field {
        display: flex;
        flex-direction: column;
        gap: 0.375rem;
        flex: 1;
    }

    .form-field-grow {
        flex: 2;
    }

    .field-label {
        font-family: 'Lexend Deca Variable', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        font-size: var(--font-size-small, 0.8125rem);
        font-weight: 500;
        color: var(--color-font-secondary);
        padding-left: 0.25rem;
    }

    /* Native date/time/number inputs styled to match SettingsInput */
    .native-input {
        width: 100%;
        padding: 1.0625rem 1.4375rem;
        background: var(--color-grey-0);
        border: none;
        border-radius: 1.5rem;
        box-shadow: 0 0.25rem 0.25rem rgba(0, 0, 0, 0.1);
        font-family: 'Lexend Deca Variable', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        font-weight: 500;
        font-size: var(--input-font-size, 1rem);
        line-height: 1.25;
        color: var(--color-grey-100);
        transition: box-shadow 0.2s ease;
        box-sizing: border-box;
    }

    .native-input:focus {
        outline: none;
        box-shadow: 0 0.25rem 0.5rem rgba(0, 0, 0, 0.15);
    }
</style>
