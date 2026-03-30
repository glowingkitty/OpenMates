<!--
  SettingsReminders.svelte

  Reminder creation page within the Reminders app settings.
  Uses canonical settings design elements (SettingsItem headings + SettingsInput/Dropdown).

  Opened via chat top bar reminder button (deep link: app_store/reminder/create).
  Reads the active chat from activeChatStore to show context and allow "This chat"
  as a target option.

  API: POST /v1/apps/reminder/skills/set-reminder (creation)
  API: GET /v1/settings/reminders (list, via ActiveRemindersList)

  Architecture: docs/architecture/ai/reminder.md
-->

<script lang="ts">
    import { text } from '@repo/ui';
    import { userProfile } from '../../../stores/userProfile';
    import { activeChatStore } from '../../../stores/activeChatStore';
    import { chatListCache } from '../../../services/chatListCache';
    import { getApiUrl } from '../../../config/api';
    import SettingsPageContainer from '../elements/SettingsPageContainer.svelte';
    import SettingsTextarea from '../elements/SettingsTextarea.svelte';
    import SettingsDropdown from '../elements/SettingsDropdown.svelte';
    import SettingsButton from '../elements/SettingsButton.svelte';
    import SettingsDivider from '../elements/SettingsDivider.svelte';
    import SettingsInfoBox from '../elements/SettingsInfoBox.svelte';
    import SettingsItem from '../../SettingsItem.svelte';
    import ActiveRemindersList from '../appSettings/ActiveRemindersList.svelte';

    // ─── Chat context ──────────────────────────────────────────────────────────

    /** Active chat ID from store (set by ActiveChat before opening this page) */
    let activeChatId = $derived($activeChatStore);

    /** Look up the chat title from the chat list cache */
    let activeChatTitle = $derived.by(() => {
        if (!activeChatId) return '';
        const chats = chatListCache.getCache();
        if (!chats) return '';
        const chat = chats.find(c => c.chat_id === activeChatId);
        return chat?.title || '';
    });

    let hasActiveChat = $derived(!!activeChatId && !!activeChatTitle);

    // ─── Form state ────────────────────────────────────────────────────────────

    let date = $state('');
    let time = $state('');
    /** Single toggle: 'this_chat' (simple notification) or 'new_task' (new chat + AI action) */
    let reminderMode = $state<'this_chat' | 'new_task'>('this_chat');
    let actionPrompt = $state('');
    let repeatType = $state('none');
    let customInterval = $state('1');
    let customUnit = $state('days');
    let endDate = $state('');

    let isSubmitting = $state(false);
    let errorMessage = $state('');
    let successMessage = $state('');
    let refreshTrigger = $state(0);

    // Default to new_task if no active chat context
    $effect(() => {
        if (!hasActiveChat) {
            reminderMode = 'new_task';
        }
    });

    // ─── Derived ───────────────────────────────────────────────────────────────

    let timezone = $derived(
        $userProfile.timezone || Intl.DateTimeFormat().resolvedOptions().timeZone
    );

    let todayStr = $derived.by(() => {
        const d = new Date();
        return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
    });

    let showCustomRepeat = $derived(repeatType === 'custom');

    let repeatOptions = $derived([
        { value: 'none', label: $text('reminder.panel.repeat_none') },
        { value: 'daily', label: $text('reminder.panel.repeat_daily') },
        { value: 'weekly', label: $text('reminder.panel.repeat_weekly') },
        { value: 'monthly', label: $text('common.monthly') },
        { value: 'custom', label: $text('common.custom') },
    ]);

    let customUnitOptions = $derived([
        { value: 'days', label: $text('reminder.panel.repeat_days') },
        { value: 'weeks', label: $text('reminder.panel.repeat_weeks') },
        { value: 'months', label: $text('reminder.panel.repeat_months') },
    ]);

    let reminderModeOptions = $derived([
        ...(hasActiveChat
            ? [{ value: 'this_chat', label: $text('reminder.panel.mode_this_chat') }]
            : []),
        { value: 'new_task', label: $text('reminder.panel.mode_new_task') },
    ]);

    // ─── Submission ────────────────────────────────────────────────────────────

    async function handleSubmit() {
        errorMessage = '';
        successMessage = '';

        if (!date || !time) return;

        const triggerDatetime = `${date}T${time}:00`;
        const triggerMs = new Date(triggerDatetime).getTime();
        if (triggerMs <= Date.now()) {
            errorMessage = $text('reminder.panel.error_past');
            return;
        }

        isSubmitting = true;

        try {
            // Map single toggle to backend fields
            const isNewTask = reminderMode === 'new_task';
            const targetType = isNewTask ? 'new_chat' : 'existing_chat';
            const responseType = isNewTask ? 'full' : 'simple';
            const prompt = isNewTask && actionPrompt.trim()
                ? actionPrompt.trim()
                : $text('reminder.panel.auto_prompt');

            const body: Record<string, unknown> = {
                prompt,
                trigger_type: 'specific',
                trigger_datetime: triggerDatetime,
                timezone,
                target_type: targetType,
                response_type: responseType,
            };

            if (targetType === 'existing_chat' && activeChatId) {
                body._chat_id = activeChatId;
            } else {
                body.target_type = 'new_chat';
                body.new_chat_title = prompt.slice(0, 50);
            }

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
            actionPrompt = '';
            reminderMode = hasActiveChat ? 'this_chat' : 'new_task';
            repeatType = 'none';
            customInterval = '1';
            customUnit = 'days';
            endDate = '';
            refreshTrigger++;

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
    <!-- Chat context: show which chat the reminder relates to -->
    {#if hasActiveChat}
        <div class="chat-context" data-testid="chat-context">
            <div class="chat-context-icon">
                <span class="icon reminder"></span>
            </div>
            <div class="chat-context-info">
                <span class="chat-context-title">{activeChatTitle}</span>
            </div>
        </div>
    {/if}

    <!-- Reminder mode: this chat notification vs new task -->
    <SettingsItem
        type="heading"
        icon="reminder"
        title={$text('reminder.settings.target_heading')}
    />
    <SettingsDropdown
        bind:value={reminderMode}
        options={reminderModeOptions}
        ariaLabel={$text('reminder.settings.target_heading')}
    />

    <!-- Date -->
    <SettingsItem
        type="heading"
        icon="calendar"
        title={$text('common.date')}
    />
    <div class="native-input-wrapper">
        <input
            id="settings-reminder-date"
            class="native-input"
            type="date"
            bind:value={date}
            min={todayStr}
        />
    </div>

    <!-- Time -->
    <SettingsItem
        type="heading"
        icon="calendar"
        title={$text('reminder.panel.time')}
    />
    <div class="native-input-wrapper">
        <input
            id="settings-reminder-time"
            class="native-input"
            type="time"
            bind:value={time}
        />
    </div>

    <!-- Action prompt (only for new task mode) -->
    {#if reminderMode === 'new_task'}
        <SettingsItem
            type="heading"
            icon="text"
            title={$text('reminder.panel.action_prompt_label')}
        />
        <SettingsTextarea
            bind:value={actionPrompt}
            placeholder={$text('reminder.panel.action_prompt_placeholder')}
            ariaLabel={$text('reminder.panel.action_prompt_label')}
            rows={4}
        />
    {/if}

    <!-- Repeat -->
    <SettingsItem
        type="heading"
        icon="reminder"
        title={$text('reminder.panel.repeat')}
    />
    <SettingsDropdown
        bind:value={repeatType}
        options={repeatOptions}
        ariaLabel={$text('reminder.panel.repeat')}
    />

    {#if showCustomRepeat}
        <SettingsItem
            type="heading"
            icon="reminder"
            title={$text('reminder.panel.repeat_every')}
        />
        <div class="custom-repeat-row">
            <div class="native-input-wrapper interval-field">
                <input
                    id="settings-reminder-interval"
                    class="native-input"
                    type="number"
                    min="1"
                    bind:value={customInterval}
                />
            </div>
            <div class="unit-field">
                <SettingsDropdown
                    bind:value={customUnit}
                    options={customUnitOptions}
                    ariaLabel={$text('reminder.panel.repeat_days')}
                />
            </div>
        </div>
    {/if}

    {#if repeatType !== 'none'}
        <SettingsItem
            type="heading"
            icon="calendar"
            title={$text('reminder.panel.end_date')}
        />
        <div class="native-input-wrapper">
            <input
                id="settings-reminder-end-date"
                class="native-input"
                type="date"
                bind:value={endDate}
                min={todayStr}
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
        disabled={!date || !time || (reminderMode === 'new_task' && !actionPrompt.trim())}
        onClick={handleSubmit}
    >
        {isSubmitting ? $text('reminder.panel.setting') : $text('reminder.panel.submit')}
    </SettingsButton>

    <SettingsDivider />

    <!-- Active reminders list -->
    <SettingsItem
        type="heading"
        icon="reminder"
        title={$text('reminder.settings.active_title')}
    />
    <ActiveRemindersList {refreshTrigger} />
</SettingsPageContainer>

<style>
    /* Chat context preview at top of form */
    .chat-context {
        display: flex;
        align-items: center;
        gap: 0.75rem;
        padding: 0.75rem 1rem;
        margin: 0 0.625rem;
        background: var(--color-grey-10);
        border-radius: 1rem;
        border: 1px solid var(--color-grey-25);
    }

    .chat-context-icon {
        flex-shrink: 0;
        width: 2rem;
        height: 2rem;
        display: flex;
        align-items: center;
        justify-content: center;
    }

    .chat-context-title {
        font-family: 'Lexend Deca Variable', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        font-size: var(--font-size-p, 0.875rem);
        font-weight: 500;
        color: var(--color-font-primary);
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }

    /* Wrapper to match SettingsInput/SettingsDropdown horizontal padding */
    .native-input-wrapper {
        padding: 0 0.625rem;
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

    .custom-repeat-row {
        display: flex;
        gap: 0.75rem;
        align-items: flex-start;
    }

    .interval-field {
        flex: 1;
    }

    .unit-field {
        flex: 2;
    }
</style>
