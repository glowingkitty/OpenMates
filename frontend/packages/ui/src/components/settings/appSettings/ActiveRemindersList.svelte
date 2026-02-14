<!--
  frontend/packages/ui/src/components/settings/appSettings/ActiveRemindersList.svelte
  
  Displays a list of active (pending) reminders in the reminder app settings page.
  Fetches reminders from the REST API and shows them in a compact list format.
  
  Only shown for authenticated users on the reminder app page.
  
  Data source: GET /v1/settings/reminders
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
    
    // Component state
    let reminders = $state<ActiveReminder[]>([]);
    let loading = $state(true);
    let error = $state<string | null>(null);
    
    /**
     * Fetch active reminders from the backend API.
     * Uses credentials: 'include' for cookie-based auth.
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
    
    onMount(() => {
        fetchReminders();
    });
</script>

<div class="active-reminders">
    {#if loading}
        <!-- Loading state -->
        <div class="loading-state">
            <div class="loading-spinner"></div>
            <span class="loading-text">{$text('apps.reminder.active_reminders.loading')}</span>
        </div>
    {:else if error}
        <!-- Error state -->
        <div class="error-state">
            <span class="error-icon">&#9888;</span>
            <span class="error-text">{$text('apps.reminder.active_reminders.error')}</span>
        </div>
    {:else if reminders.length === 0}
        <!-- Empty state -->
        <div class="empty-state">
            <span class="empty-text">{$text('apps.reminder.active_reminders.empty')}</span>
        </div>
    {:else}
        <!-- Reminders list -->
        <div class="reminders-list">
            {#each reminders as reminder (reminder.reminder_id)}
                <div class="reminder-item">
                    <div class="reminder-icon">&#128276;</div>
                    <div class="reminder-content">
                        <!-- Prompt preview -->
                        {#if reminder.prompt_preview}
                            <div class="reminder-prompt">{reminder.prompt_preview}</div>
                        {/if}
                        
                        <!-- Trigger time and badges -->
                        <div class="reminder-meta">
                            <span class="reminder-time">&#128337; {reminder.trigger_at_formatted}</span>
                            {#if reminder.is_repeating}
                                <span class="badge repeat-badge">{$text('apps.reminder.active_reminders.repeating')}</span>
                            {/if}
                        </div>
                    </div>
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
    
    /* Loading state */
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
    
    .loading-text {
        font-size: 13px;
    }
    
    /* Error state */
    .error-state {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 8px 0;
        color: var(--color-grey-60);
    }
    
    .error-icon {
        font-size: 14px;
        color: var(--color-grey-50);
    }
    
    .error-text {
        font-size: 13px;
    }
    
    /* Empty state */
    .empty-state {
        padding: 8px 0;
        text-align: center;
    }
    
    .empty-text {
        font-size: 13px;
        color: var(--color-grey-60);
    }
    
    /* Reminders list */
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
    
    .reminder-item:hover {
        background: var(--color-grey-15);
    }
    
    .reminder-icon {
        font-size: 18px;
        flex-shrink: 0;
        padding-top: 1px;
    }
    
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
    
    .reminder-time {
        font-size: 12px;
        color: var(--color-grey-60);
        font-weight: 500;
    }
    
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
    
    /* Dark mode support */
    :global(.dark) .active-reminders {
        background: var(--color-grey-90, #1a1a1a);
        border-color: var(--color-grey-80);
    }
    
    :global(.dark) .reminder-item {
        background: var(--color-grey-85, #252525);
        border-color: var(--color-grey-80);
    }
    
    :global(.dark) .reminder-item:hover {
        background: var(--color-grey-80);
    }
    
    :global(.dark) .reminder-prompt {
        color: var(--color-grey-20);
    }
    
    :global(.dark) .reminder-time {
        color: var(--color-grey-40);
    }
    
    :global(.dark) .loading-state {
        color: var(--color-grey-40);
    }
    
    :global(.dark) .empty-text {
        color: var(--color-grey-40);
    }
    
    :global(.dark) .error-state {
        color: var(--color-grey-40);
    }
    
    :global(.dark) .repeat-badge {
        background: var(--color-warning-90, #40351a);
        color: var(--color-warning-40, #d0ba7a);
    }
</style>
