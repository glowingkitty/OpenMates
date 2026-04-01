<!--
  ReminderSetterPanel.svelte

  Inline reminder creation panel that renders inside the chat history scroll area
  (after the last message), bypassing LLM entirely.

  The panel calls POST /v1/apps/reminder/skills/set-reminder directly with
  session-cookie auth. On success it closes and a ReminderEmbedPreview
  appears inline through the normal embed flow.

  Architecture: docs/apps/reminder.md
  Test: frontend/apps/web_app/tests/reminder-same-chat.spec.ts
-->
<script lang="ts">
  import { text } from '@repo/ui';
  import { userProfile } from '../../stores/userProfile';
  import { getApiUrl } from '../../config/api';
  import { getLucideIcon } from '../../utils/categoryUtils';

  // ─── Props ─────────────────────────────────────────────────────────────────

  let {
    chatId,
    onClose,
    onSuccess,
  }: {
    /** ID of the current chat — passed as _chat_id context for existing_chat reminders. */
    chatId: string;
    onClose: () => void;
    /** Called after the API call succeeds with the reminder response data. */
    onSuccess: (reminderData: Record<string, unknown>) => void;
  } = $props();

  // ─── Icons ─────────────────────────────────────────────────────────────────

  const X = getLucideIcon('x');
  const Bell = getLucideIcon('bell');

  // ─── Form state ────────────────────────────────────────────────────────────

  let date = $state('');
  let time = $state('');
  /** Single toggle: 'this_chat' (simple notification) or 'new_task' (new chat + AI action) */
  let reminderMode = $state<'this_chat' | 'new_task'>('this_chat');
  let actionPrompt = $state('');
  let repeatType = $state<'none' | 'daily' | 'weekly' | 'monthly' | 'custom'>('none');
  let customInterval = $state(1);
  let customUnit = $state<'days' | 'weeks' | 'months'>('days');
  let endDate = $state('');

  let isSubmitting = $state(false);
  let errorMessage = $state('');

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

  /** When the selected date is today, set min time to current time + 1 minute */
  let minTime = $derived(() => {
    if (!date || date !== todayStr()) return '';
    const now = new Date();
    now.setMinutes(now.getMinutes() + 1);
    return `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`;
  });

  // ─── Submission ────────────────────────────────────────────────────────────

  async function handleSubmit(e: SubmitEvent) {
    e.preventDefault();
    errorMessage = '';

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
      // Map the single toggle to backend fields
      const isNewTask = reminderMode === 'new_task';
      const targetType = isNewTask ? 'new_chat' : 'existing_chat';
      const responseType = isNewTask ? 'full' : 'simple';
      // For this_chat: auto-generate a standard prompt (no note needed)
      // For new_task: use the action prompt the user typed
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
        chat_id: chatId,
      };

      if (isNewTask) {
        body.new_chat_title = prompt.slice(0, 50);
      }

      if (repeatType !== 'none') {
        const repeat: Record<string, unknown> = { type: repeatType };
        if (repeatType === 'custom') {
          repeat.interval = customInterval;
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
        console.error('[ReminderSetterPanel] API error:', detail);
        return;
      }

      const result = await response.json();
      onSuccess(result);
      onClose();
    } catch (err) {
      errorMessage = $text('reminder.panel.error_generic');
      console.error('[ReminderSetterPanel] fetch error:', err);
    } finally {
      isSubmitting = false;
    }
  }
</script>

<div class="reminder-panel" role="form" aria-label={$text('reminder.panel.title')}>
  <!-- Header -->
  <div class="panel-header">
    <div class="panel-title-row">
      <Bell size={16} />
      <span class="panel-title">{$text('reminder.panel.title')}</span>
    </div>
    <button class="close-btn" type="button" onclick={onClose} aria-label={$text('common.cancel')}>
      <X size={16} />
    </button>
  </div>

  <form onsubmit={handleSubmit}>
    <!-- Date + Time -->
    <div class="field-row">
      <div class="field">
        <label class="field-label" for="rsp-date">{$text('common.date')}</label>
        <input
          id="rsp-date"
          class="field-input"
          type="date"
          bind:value={date}
          min={todayStr()}
          required
        />
      </div>
      <div class="field">
        <label class="field-label" for="rsp-time">{$text('reminder.panel.time')}</label>
        <input
          id="rsp-time"
          class="field-input"
          type="time"
          bind:value={time}
          min={minTime() || undefined}
          required
        />
      </div>
    </div>

    <!-- Reminder mode toggle -->
    <div class="field">
      <div class="toggle-row">
        <button
          type="button"
          class="toggle-btn"
          class:active={reminderMode === 'this_chat'}
          onclick={() => (reminderMode = 'this_chat')}
        >
          {$text('reminder.panel.mode_this_chat')}
        </button>
        <button
          type="button"
          class="toggle-btn"
          class:active={reminderMode === 'new_task'}
          onclick={() => (reminderMode = 'new_task')}
        >
          {$text('reminder.panel.mode_new_task')}
        </button>
      </div>
    </div>

    <!-- Action prompt (only for new task mode) -->
    {#if reminderMode === 'new_task'}
      <div class="field">
        <label class="field-label" for="rsp-action">{$text('reminder.panel.action_prompt_label')}</label>
        <textarea
          id="rsp-action"
          class="field-input field-textarea"
          bind:value={actionPrompt}
          placeholder={$text('reminder.panel.action_prompt_placeholder')}
          rows="2"
        ></textarea>
      </div>
    {/if}

    <!-- Repeat -->
    <div class="field">
      <label class="field-label" for="rsp-repeat">{$text('reminder.panel.repeat')}</label>
      <select id="rsp-repeat" class="field-input field-select" bind:value={repeatType}>
        <option value="none">{$text('reminder.panel.repeat_none')}</option>
        <option value="daily">{$text('reminder.panel.repeat_daily')}</option>
        <option value="weekly">{$text('reminder.panel.repeat_weekly')}</option>
        <option value="monthly">{$text('common.monthly')}</option>
        <option value="custom">{$text('common.custom')}</option>
      </select>
    </div>

    {#if repeatType === 'custom'}
      <div class="field-row">
        <div class="field field-narrow">
          <label class="field-label" for="rsp-interval">{$text('reminder.panel.repeat_every')}</label>
          <input
            id="rsp-interval"
            class="field-input"
            type="number"
            min="1"
            max="365"
            bind:value={customInterval}
          />
        </div>
        <div class="field">
          <label class="field-label" for="rsp-unit">&nbsp;</label>
          <select id="rsp-unit" class="field-input field-select" bind:value={customUnit}>
            <option value="days">{$text('reminder.panel.repeat_days')}</option>
            <option value="weeks">{$text('reminder.panel.repeat_weeks')}</option>
            <option value="months">{$text('reminder.panel.repeat_months')}</option>
          </select>
        </div>
      </div>
    {/if}

    {#if repeatType !== 'none'}
      <div class="field">
        <label class="field-label" for="rsp-end-date">{$text('reminder.panel.end_date')}</label>
        <input
          id="rsp-end-date"
          class="field-input"
          type="date"
          bind:value={endDate}
          min={date || todayStr()}
        />
      </div>
    {/if}

    {#if errorMessage}
      <p class="error-message">{errorMessage}</p>
    {/if}

    <!-- Actions -->
    <div class="actions-row">
      <button type="button" class="btn-cancel" onclick={onClose}>
        {$text('common.cancel')}
      </button>
      <button
        type="submit"
        class="btn-submit"
        disabled={isSubmitting || !date || !time || (reminderMode === 'new_task' && !actionPrompt.trim())}
      >
        {isSubmitting ? $text('reminder.panel.setting') : $text('reminder.panel.submit')}
      </button>
    </div>
  </form>
</div>

<style>
  .reminder-panel {
    margin: 16px 0 8px;
    padding: 16px;
    background: var(--color-grey-10);
    border: 1px solid var(--color-grey-25);
    border-radius: 12px;
    max-width: 480px;
    width: 100%;
    box-sizing: border-box;
  }

  /* ─── Header ───────────────────────────────────────────────────────────── */

  .panel-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 14px;
  }

  .panel-title-row {
    display: flex;
    align-items: center;
    gap: 6px;
    color: var(--color-font-primary);
  }

  .panel-title {
    font-size: var(--font-size-h4);
    font-weight: 600;
  }

  .close-btn {
    all: unset;
    display: flex;
    align-items: center;
    justify-content: center;
    width: 26px;
    height: 26px;
    border-radius: 6px;
    cursor: pointer;
    color: var(--color-font-secondary);
    transition: background-color 0.15s ease, color 0.15s ease;
  }

  .close-btn:hover {
    background: var(--color-grey-20);
    color: var(--color-font-primary);
  }

  /* ─── Fields ───────────────────────────────────────────────────────────── */

  .field {
    display: flex;
    flex-direction: column;
    gap: 4px;
    margin-bottom: 10px;
    flex: 1;
  }

  .field-row {
    display: flex;
    gap: 10px;
    align-items: flex-start;
  }

  .field-narrow {
    flex: 0 0 80px;
  }

  .field-label {
    font-size: var(--processing-details-font-size);
    color: var(--color-font-secondary);
    font-weight: 500;
  }

  .field-input {
    background: var(--color-grey-0);
    border: 1px solid var(--color-grey-25);
    border-radius: 8px;
    padding: 7px 10px;
    font-size: var(--input-font-size);
    color: var(--color-font-primary);
    width: 100%;
    box-sizing: border-box;
    transition: border-color 0.15s ease;
    font-family: inherit;
  }

  .field-input:focus {
    border-color: var(--color-primary-light, var(--color-primary));
  }

  .field-textarea {
    resize: vertical;
    min-height: 60px;
  }

  .field-select {
    appearance: auto;
    cursor: pointer;
  }

  /* ─── Toggle buttons ───────────────────────────────────────────────────── */

  .toggle-row {
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
  }

  .toggle-btn {
    all: unset;
    box-sizing: border-box;
    padding: 5px 12px;
    border-radius: 20px;
    border: 1px solid var(--color-grey-25);
    background: var(--color-grey-0);
    color: var(--color-font-secondary);
    font-size: var(--processing-details-font-size);
    cursor: pointer;
    transition: background-color 0.15s ease, color 0.15s ease, border-color 0.15s ease;
    white-space: nowrap;
  }

  .toggle-btn:hover {
    border-color: var(--color-grey-30);
    color: var(--color-font-primary);
  }

  .toggle-btn.active {
    background: var(--color-primary);
    border-color: var(--color-primary);
    color: white;
  }

  /* ─── Error ────────────────────────────────────────────────────────────── */

  .error-message {
    margin: 0 0 10px;
    font-size: var(--processing-details-font-size);
    color: var(--color-error);
  }

  /* ─── Action buttons ───────────────────────────────────────────────────── */

  .actions-row {
    display: flex;
    justify-content: flex-end;
    gap: 8px;
    margin-top: 12px;
  }

  .btn-cancel {
    all: unset;
    box-sizing: border-box;
    padding: 7px 14px;
    border-radius: 8px;
    border: 1px solid var(--color-grey-25);
    background: transparent;
    color: var(--color-font-secondary);
    font-size: var(--button-font-size);
    cursor: pointer;
    transition: background-color 0.15s ease;
  }

  .btn-cancel:hover {
    background: var(--color-grey-10);
  }

  .btn-submit {
    all: unset;
    box-sizing: border-box;
    padding: 7px 16px;
    border-radius: 8px;
    background: var(--color-primary);
    color: white;
    font-size: var(--button-font-size);
    font-weight: 600;
    cursor: pointer;
    transition: opacity 0.15s ease;
  }

  .btn-submit:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .btn-submit:not(:disabled):hover {
    opacity: 0.88;
  }
</style>
