<!--
  frontend/packages/ui/src/components/settings/appSettings/ActiveRemindersList.svelte

  Displays active (pending) reminders in the reminder app store page.
  Uses SettingsItem components for consistent layout with Memories entries.
  Each reminder row is clickable (view mode) with an edit pencil button (edit mode).

  Data source: GET /v1/settings/reminders
  Detail page: app_store/reminder/entry/{reminder_id}[/edit]
-->

<script lang="ts">
	import { onMount, createEventDispatcher } from 'svelte';
	import { text } from '@repo/ui';
	import { getApiEndpoint } from '../../../config/api';
	import SettingsItem from '../../SettingsItem.svelte';

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
		refreshTrigger = 0
	}: {
		refreshTrigger?: number;
	} = $props();

	const dispatch = createEventDispatcher();

	let reminders = $state<ActiveReminder[]>([]);
	let loading = $state(true);
	let error = $state<string | null>(null);

	let mounted = $state(false);
	$effect(() => {
		const _ = refreshTrigger;
		if (mounted) {
			fetchReminders();
		}
	});

	async function fetchReminders() {
		loading = true;
		error = null;

		try {
			const response = await fetch(getApiEndpoint('/v1/settings/reminders'), {
				credentials: 'include'
			});

			if (!response.ok) throw new Error(`HTTP ${response.status}`);

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

	/** Navigate to reminder detail page (view mode) */
	function handleEntryClick(reminderId: string) {
		dispatch('openSettings', {
			settingsPath: `app_store/reminder/entry/${reminderId}`,
			direction: 'forward'
		});
	}

	/** Navigate to reminder detail page (edit mode) */
	function handleEditClick(reminderId: string) {
		dispatch('openSettings', {
			settingsPath: `app_store/reminder/entry/${reminderId}/edit`,
			direction: 'forward'
		});
	}

	/** Build subtitle from trigger time + badges */
	function buildSubtitle(r: ActiveReminder): string {
		const parts = [r.trigger_at_formatted];
		if (r.is_repeating) parts.push($text('apps.reminder.active_reminders.repeating'));
		const typeLabel = r.target_type === 'existing_chat'
			? $text('reminder.panel.mode_this_chat')
			: $text('reminder.panel.mode_new_task');
		parts.push(typeLabel);
		return parts.join(' · ');
	}

	onMount(() => {
		fetchReminders();
		mounted = true;
	});
</script>

{#if loading}
	<div class="loading-state">
		<div class="loading-spinner"></div>
		<span class="loading-text">{$text('apps.reminder.active_reminders.loading')}</span>
	</div>
{:else if error}
	<div class="error-state">
		<span class="error-text">{error}</span>
	</div>
{:else if reminders.length === 0}
	<div class="empty-state">
		<span class="empty-text">{$text('apps.reminder.active_reminders.empty')}</span>
	</div>
{:else}
	{#each reminders as reminder (reminder.reminder_id)}
		<SettingsItem
			type="submenu"
			icon="reminder"
			iconColor="var(--color-app-reminder, #FF9500)"
			title={reminder.prompt_preview || '—'}
			subtitleBottom={buildSubtitle(reminder)}
			hasModifyButton={true}
			onClick={() => handleEntryClick(reminder.reminder_id)}
			onModifyClick={() => handleEditClick(reminder.reminder_id)}
		/>
	{/each}
{/if}

<style>
	.loading-state {
		display: flex;
		align-items: center;
		gap: 0.625rem;
		padding: 1rem 0.625rem;
		color: var(--color-font-secondary);
	}

	.loading-spinner {
		width: 1rem;
		height: 1rem;
		border: 2px solid var(--color-grey-30);
		border-top-color: var(--color-grey-60);
		border-radius: 50%;
		animation: spin 0.8s linear infinite;
	}

	@keyframes spin {
		to { transform: rotate(360deg); }
	}

	.loading-text { font-size: 0.8125rem; }

	.error-state {
		padding: 1rem 0.625rem;
		color: var(--color-font-secondary);
	}

	.error-text { font-size: 0.8125rem; }

	.empty-state {
		padding: 1rem 0.625rem;
		text-align: center;
	}

	.empty-text {
		font-size: 0.8125rem;
		color: var(--color-font-secondary);
	}
</style>
