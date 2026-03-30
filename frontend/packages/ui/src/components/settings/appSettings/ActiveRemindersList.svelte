<!--
  frontend/packages/ui/src/components/settings/appSettings/ActiveRemindersList.svelte

  Displays a list of active (pending) reminders in the reminder app settings page.
  Supports viewing, editing (time/repeat), and deleting reminders.

  Data source: GET /v1/settings/reminders
  Edit: PATCH /v1/settings/reminders/{id}
  Delete: DELETE /v1/settings/reminders/{id}
-->

<script lang="ts">
    import { onMount } from 'svelte';
    import { text } from '@repo/ui';
    import { getApiEndpoint } from '../../../config/api';

    /**
     * Represents a single active reminder returned by the API.
     */
    interface ActiveReminder {
        reminder_id: string;
        prompt_preview: string;
        trigger_at: number;
        trigger_at_formatted: string;
        target_type: string;
        is_repeating: boolean;
        status: string;
    }

    let {
        /** Increment this counter to trigger a refetch of reminders. */
        refreshTrigger = 0,
    }: {
        refreshTrigger?: number;
    } = $props();

    // Component state
    let reminders = $state<ActiveReminder[]>([]);
    let loading = $state(true);
    let error = $state<string | null>(null);

    // Edit state
    let editingId = $state<string | null>(null);
    let editDate = $state('');
    let editTime = $state('');
    let editSaving = $state(false);

    // Delete state
    let deletingId = $state<string | null>(null);
    let confirmDeleteId = $state<string | null>(null);

    // Refetch when refreshTrigger changes (after initial mount)
    let mounted = $state(false);
    $effect(() => {
        const _ = refreshTrigger;
        if (mounted) {
            fetchReminders();
        }
    });

    /**
     * Fetch active reminders from the backend API.
     */
    async function fetchReminders() {
        loading = true;
        error = null;

        try {
            const response = await fetch(getApiEndpoint('/v1/settings/reminders'), {
                credentials: 'include'
            });

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }

            const data = await response.json();

            if (data.success) {
                reminders = data.reminders || [];
            } else {
                error = 'Failed to load reminders';
            }
        } catch (e) {
            console.error('[ActiveRemindersList] Error fetching reminders:', e);
            error = e instanceof Error ? e.message : 'Unknown error';
        } finally {
            loading = false;
        }
    }

    /**
     * Start editing a reminder — pre-fill date/time from trigger_at.
     */
    function startEdit(reminder: ActiveReminder) {
        editingId = reminder.reminder_id;
        // Parse the trigger_at unix timestamp into date/time inputs
        const d = new Date(reminder.trigger_at * 1000);
        editDate = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
        editTime = `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
    }

    function cancelEdit() {
        editingId = null;
        editDate = '';
        editTime = '';
    }

    /**
     * Save edited reminder via PATCH endpoint.
     */
    async function saveEdit(reminderId: string) {
        if (!editDate || !editTime) return;
        editSaving = true;

        try {
            const triggerDatetime = `${editDate}T${editTime}:00`;
            const triggerMs = new Date(triggerDatetime).getTime();
            if (triggerMs <= Date.now()) {
                error = $text('reminder.panel.error_past');
                editSaving = false;
                return;
            }

            const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
            const response = await fetch(getApiEndpoint(`/v1/settings/reminders/${reminderId}`), {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify({
                    trigger_datetime: triggerDatetime,
                    timezone,
                }),
            });

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }

            const data = await response.json();
            if (data.success) {
                editingId = null;
                editDate = '';
                editTime = '';
                error = null;
                await fetchReminders();
            } else {
                error = data.detail || 'Failed to update';
            }
        } catch (e) {
            console.error('[ActiveRemindersList] Error updating reminder:', e);
            error = e instanceof Error ? e.message : 'Unknown error';
        } finally {
            editSaving = false;
        }
    }

    /**
     * Delete/cancel a reminder via DELETE endpoint.
     */
    async function deleteReminder(reminderId: string) {
        deletingId = reminderId;

        try {
            const response = await fetch(getApiEndpoint(`/v1/settings/reminders/${reminderId}`), {
                method: 'DELETE',
                credentials: 'include',
            });

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }

            const data = await response.json();
            if (data.success) {
                confirmDeleteId = null;
                await fetchReminders();
            } else {
                error = data.detail || 'Failed to delete';
            }
        } catch (e) {
            console.error('[ActiveRemindersList] Error deleting reminder:', e);
            error = e instanceof Error ? e.message : 'Unknown error';
        } finally {
            deletingId = null;
        }
    }

    onMount(() => {
        fetchReminders();
        mounted = true;
    });
</script>

<div class="active-reminders">
    {#if loading}
        <div class="loading-state">
            <div class="loading-spinner"></div>
            <span class="loading-text">{$text('apps.reminder.active_reminders.loading')}</span>
        </div>
    {:else if error}
        <div class="error-state">
            <span class="error-icon">&#9888;</span>
            <span class="error-text">{error}</span>
        </div>
    {:else if reminders.length === 0}
        <div class="empty-state">
            <span class="empty-text">{$text('apps.reminder.active_reminders.empty')}</span>
        </div>
    {:else}
        <div class="reminders-list">
            {#each reminders as reminder (reminder.reminder_id)}
                <div class="reminder-item" data-testid="reminder-item">
                    <div class="reminder-icon">&#128276;</div>
                    <div class="reminder-content">
                        {#if reminder.prompt_preview}
                            <div class="reminder-prompt">{reminder.prompt_preview}</div>
                        {/if}

                        {#if editingId === reminder.reminder_id}
                            <!-- Inline edit form -->
                            <div class="edit-form">
                                <div class="edit-row">
                                    <input
                                        class="edit-input"
                                        type="date"
                                        bind:value={editDate}
                                    />
                                    <input
                                        class="edit-input"
                                        type="time"
                                        bind:value={editTime}
                                    />
                                </div>
                                <div class="edit-actions">
                                    <button
                                        class="btn-save"
                                        data-testid="btn-save"
                                        disabled={editSaving || !editDate || !editTime}
                                        onclick={() => saveEdit(reminder.reminder_id)}
                                    >
                                        {editSaving ? '...' : $text('common.save')}
                                    </button>
                                    <button class="btn-cancel-edit" onclick={cancelEdit}>
                                        {$text('common.cancel')}
                                    </button>
                                </div>
                            </div>
                        {:else}
                            <div class="reminder-meta">
                                <span class="reminder-time">&#128337; {reminder.trigger_at_formatted}</span>
                                {#if reminder.is_repeating}
                                    <span class="badge repeat-badge">{$text('apps.reminder.active_reminders.repeating')}</span>
                                {/if}
                                <span class="badge target-badge">
                                    {reminder.target_type === 'existing_chat'
                                        ? $text('reminder.panel.mode_this_chat')
                                        : $text('reminder.panel.mode_new_task')}
                                </span>
                            </div>
                        {/if}
                    </div>

                    <!-- Action buttons -->
                    {#if editingId !== reminder.reminder_id}
                        <div class="reminder-actions">
                            <button
                                class="action-btn edit-btn"
                                title={$text('common.edit')}
                                onclick={() => startEdit(reminder)}
                                data-testid="edit-reminder-btn"
                            >
                                &#9998;
                            </button>
                            {#if confirmDeleteId === reminder.reminder_id}
                                <button
                                    class="action-btn confirm-delete-btn"
                                    disabled={deletingId === reminder.reminder_id}
                                    onclick={() => deleteReminder(reminder.reminder_id)}
                                    data-testid="confirm-delete-reminder-btn"
                                >
                                    {deletingId === reminder.reminder_id ? '...' : '&#10003;'}
                                </button>
                                <button
                                    class="action-btn cancel-delete-btn"
                                    onclick={() => (confirmDeleteId = null)}
                                >
                                    &#10005;
                                </button>
                            {:else}
                                <button
                                    class="action-btn delete-btn"
                                    title={$text('common.delete')}
                                    onclick={() => (confirmDeleteId = reminder.reminder_id)}
                                    data-testid="delete-reminder-btn"
                                >
                                    &#128465;
                                </button>
                            {/if}
                        </div>
                    {/if}
                </div>
            {/each}
        </div>
    {/if}
</div>

<style>
    .active-reminders {
        margin-top: 0.5rem;
        padding: 1rem;
        background: var(--color-grey-10);
        border-radius: 8px;
        border: 1px solid var(--color-grey-20);
    }

    .loading-state {
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 8px 0;
        color: var(--color-grey-60);
    }

    .loading-spinner {
        width: 16px;
        height: 16px;
        border: 2px solid var(--color-grey-30);
        border-top-color: var(--color-grey-60);
        border-radius: 50%;
        animation: spin 0.8s linear infinite;
    }

    @keyframes spin {
        to { transform: rotate(360deg); }
    }

    .loading-text { font-size: 13px; }

    .error-state {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 8px 0;
        color: var(--color-grey-60);
    }

    .error-icon { font-size: 14px; color: var(--color-grey-50); }
    .error-text { font-size: 13px; }

    .empty-state { padding: 8px 0; text-align: center; }
    .empty-text { font-size: 13px; color: var(--color-grey-60); }

    .reminders-list {
        display: flex;
        flex-direction: column;
        gap: 10px;
    }

    .reminder-item {
        display: flex;
        align-items: flex-start;
        gap: 10px;
        padding: 10px 12px;
        background: var(--color-grey-5, #fafafa);
        border-radius: 8px;
        border: 1px solid var(--color-grey-15);
        transition: background 0.15s ease;
    }

    .reminder-item:hover { background: var(--color-grey-15); }

    .reminder-icon { font-size: 18px; flex-shrink: 0; padding-top: 1px; }

    .reminder-content {
        flex: 1;
        min-width: 0;
        display: flex;
        flex-direction: column;
        gap: 6px;
    }

    .reminder-prompt {
        font-size: 13px;
        color: var(--color-grey-90);
        line-height: 1.4;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }

    .reminder-meta {
        display: flex;
        align-items: center;
        gap: 8px;
        flex-wrap: wrap;
    }

    .reminder-time { font-size: 12px; color: var(--color-grey-60); font-weight: 500; }

    .badge {
        display: inline-flex;
        align-items: center;
        padding: 2px 6px;
        border-radius: 10px;
        font-size: 10px;
        font-weight: 500;
    }

    .repeat-badge {
        background: var(--color-warning-10, #fff8e8);
        color: var(--color-warning-70, #b08a4a);
    }

    .target-badge {
        background: var(--color-primary-10, #eef0ff);
        color: var(--color-primary-70, #5a5ccc);
    }

    /* Action buttons */
    .reminder-actions {
        display: flex;
        gap: 4px;
        flex-shrink: 0;
        align-items: center;
        padding-top: 2px;
    }

    .action-btn {
        all: unset;
        display: flex;
        align-items: center;
        justify-content: center;
        width: 28px;
        height: 28px;
        border-radius: 6px;
        cursor: pointer;
        font-size: 14px;
        transition: background 0.15s ease, color 0.15s ease;
        color: var(--color-grey-50);
    }

    .action-btn:hover { background: var(--color-grey-20); color: var(--color-grey-80); }
    .action-btn:disabled { opacity: 0.5; cursor: not-allowed; }

    .confirm-delete-btn { color: var(--color-error, #e53e3e); }
    .confirm-delete-btn:hover { background: var(--color-error-10, #fff5f5); }

    /* Inline edit form */
    .edit-form {
        display: flex;
        flex-direction: column;
        gap: 6px;
    }

    .edit-row {
        display: flex;
        gap: 6px;
    }

    .edit-input {
        padding: 4px 8px;
        border: 1px solid var(--color-grey-25);
        border-radius: 6px;
        font-size: 12px;
        background: var(--color-grey-0);
        color: var(--color-font-primary);
        font-family: inherit;
    }

    .edit-actions {
        display: flex;
        gap: 6px;
    }

    .btn-save {
        all: unset;
        padding: 3px 10px;
        border-radius: 6px;
        background: var(--color-primary);
        color: white;
        font-size: 11px;
        font-weight: 600;
        cursor: pointer;
    }

    .btn-save:disabled { opacity: 0.5; cursor: not-allowed; }

    .btn-cancel-edit {
        all: unset;
        padding: 3px 10px;
        border-radius: 6px;
        border: 1px solid var(--color-grey-25);
        font-size: 11px;
        color: var(--color-font-secondary);
        cursor: pointer;
    }

    /* Dark mode */
    :global(.dark) .active-reminders { background: var(--color-grey-90, #1a1a1a); border-color: var(--color-grey-80); }
    :global(.dark) .reminder-item { background: var(--color-grey-85, #252525); border-color: var(--color-grey-80); }
    :global(.dark) .reminder-item:hover { background: var(--color-grey-80); }
    :global(.dark) .reminder-prompt { color: var(--color-grey-20); }
    :global(.dark) .reminder-time { color: var(--color-grey-40); }
    :global(.dark) .loading-state { color: var(--color-grey-40); }
    :global(.dark) .empty-text { color: var(--color-grey-40); }
    :global(.dark) .error-state { color: var(--color-grey-40); }
    :global(.dark) .repeat-badge { background: var(--color-warning-90, #40351a); color: var(--color-warning-40, #d0ba7a); }
    :global(.dark) .target-badge { background: var(--color-primary-90, #1a1a40); color: var(--color-primary-40, #8a8cff); }
    :global(.dark) .edit-input { background: var(--color-grey-80); border-color: var(--color-grey-70); color: var(--color-grey-10); }
    :global(.dark) .action-btn { color: var(--color-grey-40); }
    :global(.dark) .action-btn:hover { background: var(--color-grey-80); color: var(--color-grey-20); }
</style>
