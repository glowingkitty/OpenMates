<!--
  frontend/packages/ui/src/components/settings/appSettings/ReminderEntryDetail.svelte

  View/edit detail page for a single active reminder.
  Similar to AppSettingsMemoriesEntryDetail — shows reminder fields in view mode
  with an Edit button, and inline form inputs in edit mode.

  Route: app_store/reminder/entry/{reminder_id}[/edit]
  API: GET /v1/settings/reminders (list, filtered client-side)
       PATCH /v1/settings/reminders/{reminder_id}
       DELETE /v1/settings/reminders/{reminder_id}
-->

<script lang="ts">
	import { text } from '@repo/ui';
	import { onMount, createEventDispatcher, untrack } from 'svelte';
	import { getApiEndpoint } from '../../../config/api';
	import SettingsPageContainer from '../elements/SettingsPageContainer.svelte';
	import SettingsSectionHeading from '../elements/SettingsSectionHeading.svelte';
	import SettingsInfoBox from '../elements/SettingsInfoBox.svelte';

	interface Props {
		reminderId: string;
		startInEditMode?: boolean;
	}

	let { reminderId, startInEditMode = false }: Props = $props();

	const dispatch = createEventDispatcher();

	// ─── State ──────────────────────────────────────────────────────────────────

	interface ReminderDetail {
		reminder_id: string;
		prompt_preview: string;
		trigger_at: number;
		trigger_at_formatted: string;
		target_type: string;
		is_repeating: boolean;
		status: string;
	}

	let reminder = $state<ReminderDetail | null>(null);
	let loading = $state(true);
	let error = $state<string | null>(null);
	let mode = $state<'view' | 'edit'>(untrack(() => startInEditMode ? 'edit' : 'view'));

	// Edit form state
	let editDate = $state('');
	let editTime = $state('');
	let editSaving = $state(false);
	let editError = $state('');

	// Delete state
	let confirmDelete = $state(false);
	let deleting = $state(false);

	// ─── Data fetching ─────────────────────────────────────────────────────────

	async function fetchReminder() {
		loading = true;
		error = null;

		try {
			const response = await fetch(getApiEndpoint('/v1/settings/reminders'), {
				credentials: 'include'
			});
			if (!response.ok) throw new Error(`HTTP ${response.status}`);

			const data = await response.json();
			if (data.success && data.reminders) {
				const found = data.reminders.find(
					(r: ReminderDetail) => r.reminder_id === reminderId
				);
				if (found) {
					reminder = found;
					// Pre-fill edit form from current values
					const d = new Date(found.trigger_at * 1000);
					editDate = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
					editTime = `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
				} else {
					error = 'Reminder not found';
				}
			} else {
				error = 'Failed to load reminder';
			}
		} catch (e) {
			console.error('[ReminderEntryDetail] Error:', e);
			error = e instanceof Error ? e.message : 'Unknown error';
		} finally {
			loading = false;
		}
	}

	// ─── Actions ───────────────────────────────────────────────────────────────

	function startEdit() {
		mode = 'edit';
		editError = '';
	}

	function cancelEdit() {
		mode = 'view';
		editError = '';
		// Reset form to current values
		if (reminder) {
			const d = new Date(reminder.trigger_at * 1000);
			editDate = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
			editTime = `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
		}
	}

	async function handleSave() {
		if (!editDate || !editTime) return;
		editError = '';

		const triggerDatetime = `${editDate}T${editTime}:00`;
		const triggerMs = new Date(triggerDatetime).getTime();
		if (triggerMs <= Date.now()) {
			editError = $text('reminder.panel.error_past');
			return;
		}

		editSaving = true;
		try {
			const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
			const response = await fetch(getApiEndpoint(`/v1/settings/reminders/${reminderId}`), {
				method: 'PATCH',
				headers: { 'Content-Type': 'application/json' },
				credentials: 'include',
				body: JSON.stringify({ trigger_datetime: triggerDatetime, timezone })
			});

			if (!response.ok) throw new Error(`HTTP ${response.status}`);

			const data = await response.json();
			if (data.success) {
				mode = 'view';
				await fetchReminder();
			} else {
				editError = data.detail || 'Failed to update';
			}
		} catch (e) {
			console.error('[ReminderEntryDetail] Save error:', e);
			editError = e instanceof Error ? e.message : 'Failed to save';
		} finally {
			editSaving = false;
		}
	}

	async function handleDelete() {
		if (!confirmDelete) {
			confirmDelete = true;
			return;
		}

		deleting = true;
		try {
			const response = await fetch(getApiEndpoint(`/v1/settings/reminders/${reminderId}`), {
				method: 'DELETE',
				credentials: 'include'
			});

			if (!response.ok) throw new Error(`HTTP ${response.status}`);

			const data = await response.json();
			if (data.success) {
				// Navigate back to the reminder app store page
				dispatch('openSettings', {
					settingsPath: 'app_store/reminder',
					direction: 'back'
				});
			} else {
				error = data.detail || 'Failed to delete';
			}
		} catch (e) {
			console.error('[ReminderEntryDetail] Delete error:', e);
			error = e instanceof Error ? e.message : 'Failed to delete';
		} finally {
			deleting = false;
			confirmDelete = false;
		}
	}

	onMount(() => {
		fetchReminder();
	});
</script>

<SettingsPageContainer>
	{#if loading}
		<div class="loading-state">
			<div class="loading-spinner"></div>
			<span>{$text('apps.reminder.active_reminders.loading')}</span>
		</div>
	{:else if error}
		<SettingsInfoBox type="error">{error}</SettingsInfoBox>
	{:else if reminder}
		{#if mode === 'view'}
			<!-- View mode -->
			<SettingsSectionHeading icon="reminder" title={$text('reminder.panel.title')} />
			<div class="detail-value">{reminder.prompt_preview || '—'}</div>

			<SettingsSectionHeading icon="calendar" title={$text('reminder.settings.day_heading')} />
			<div class="detail-value">{reminder.trigger_at_formatted}</div>

			<SettingsSectionHeading icon="task" title={$text('reminder.settings.type_heading')} />
			<div class="detail-value">
				{reminder.target_type === 'existing_chat'
					? $text('reminder.settings.type_chat_reminder')
					: $text('reminder.settings.type_task')}
			</div>

			{#if reminder.is_repeating}
				<SettingsSectionHeading icon="reload" title={$text('reminder.settings.repeat_heading')} />
				<div class="detail-value">{$text('apps.reminder.active_reminders.repeating')}</div>
			{/if}

			<div class="action-buttons">
				<button class="btn-edit" data-testid="edit-reminder-btn" onclick={startEdit}>
					{$text('common.edit')}
				</button>
				<button
					class="btn-delete"
					data-testid="delete-reminder-btn"
					disabled={deleting}
					onclick={handleDelete}
				>
					{#if confirmDelete}
						{deleting ? '...' : $text('common.confirm')}
					{:else}
						{$text('common.delete')}
					{/if}
				</button>
			</div>
		{:else}
			<!-- Edit mode -->
			<SettingsSectionHeading icon="reminder" title={$text('reminder.panel.title')} />
			<div class="detail-value">{reminder.prompt_preview || '—'}</div>

			<SettingsSectionHeading icon="calendar" title={$text('reminder.settings.day_heading')} />
			<div class="native-input-wrapper">
				<input
					class="native-input"
					type="date"
					bind:value={editDate}
				/>
			</div>

			<SettingsSectionHeading icon="clock" title={$text('reminder.settings.time_heading')} />
			<div class="native-input-wrapper">
				<input
					class="native-input"
					type="time"
					bind:value={editTime}
				/>
			</div>

			{#if editError}
				<SettingsInfoBox type="error">{editError}</SettingsInfoBox>
			{/if}

			<div class="action-buttons">
				<button
					class="btn-save"
					data-testid="save-reminder-btn"
					disabled={editSaving || !editDate || !editTime}
					onclick={handleSave}
				>
					{editSaving ? '...' : $text('common.save')}
				</button>
				<button class="btn-cancel" onclick={cancelEdit}>
					{$text('common.cancel')}
				</button>
			</div>
		{/if}
	{/if}
</SettingsPageContainer>

<style>
	.loading-state {
		display: flex;
		align-items: center;
		gap: 0.75rem;
		padding: 1rem;
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

	.detail-value {
		padding: 0.75rem 1.25rem;
		font-family: 'Lexend Deca Variable', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
		font-size: var(--font-size-p, 0.875rem);
		font-weight: 500;
		color: var(--color-font-primary);
		line-height: 1.4;
	}

	.native-input-wrapper {
		padding: 0 0.625rem;
	}

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
		appearance: none;
		-webkit-appearance: none;
		transition: box-shadow var(--duration-normal) var(--easing-default);
		box-sizing: border-box;
	}

	.native-input:focus {
		outline: none;
		box-shadow: 0 0.25rem 0.5rem rgba(0, 0, 0, 0.15);
	}

	.action-buttons {
		display: flex;
		gap: 0.75rem;
		padding: 1rem 0.625rem;
	}

	.btn-edit, .btn-save {
		flex: 1;
		padding: 0.75rem;
		border: none;
		border-radius: 1.5rem;
		background: var(--color-primary);
		color: white;
		font-family: inherit;
		font-size: var(--font-size-p, 0.875rem);
		font-weight: 600;
		cursor: pointer;
		transition: opacity var(--duration-fast) var(--easing-default);
	}

	.btn-edit:hover, .btn-save:hover { opacity: 0.88; }
	.btn-save:disabled { opacity: 0.5; cursor: not-allowed; }

	.btn-delete {
		padding: 0.75rem 1.25rem;
		border: 1px solid var(--color-error, #e53e3e);
		border-radius: 1.5rem;
		background: transparent;
		color: var(--color-error, #e53e3e);
		font-family: inherit;
		font-size: var(--font-size-p, 0.875rem);
		font-weight: 600;
		cursor: pointer;
		transition: background var(--duration-fast) var(--easing-default);
	}

	.btn-delete:hover { background: var(--color-error-5, #fff5f5); }
	.btn-delete:disabled { opacity: 0.5; cursor: not-allowed; }

	.btn-cancel {
		padding: 0.75rem 1.25rem;
		border: 1px solid var(--color-grey-25);
		border-radius: 1.5rem;
		background: transparent;
		color: var(--color-font-secondary);
		font-family: inherit;
		font-size: var(--font-size-p, 0.875rem);
		font-weight: 500;
		cursor: pointer;
		transition: background var(--duration-fast) var(--easing-default);
	}

	.btn-cancel:hover { background: var(--color-grey-10); }
</style>
