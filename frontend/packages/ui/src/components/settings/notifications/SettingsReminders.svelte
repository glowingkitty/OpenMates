<!--
  SettingsReminders.svelte

  Reminder creation page within the Reminders app settings.
  Uses canonical settings design elements (SettingsSectionHeading + SettingsDropdown).

  Opened via chat top bar reminder button (deep link: app_store/reminder/create).
  Reads chat context from reminderContext store (set by ActiveChat bell button handler)
  and loads decrypted metadata from chatMetadataCache for the preview.

  Layout follows Figma designs (nodes 5206:44369 and 5228:44720):
  Reminder type → explainer → chat preview / Task textarea → Day → Time → Repeat → Button

  API: POST /v1/apps/reminder/skills/set-reminder (creation)

  Architecture: docs/architecture/ai/reminder.md
-->

<script lang="ts">
	import { text } from '@repo/ui';
	import { userProfile } from '../../../stores/userProfile';
	import { activeChatStore } from '../../../stores/activeChatStore';
	import { reminderContext } from '../../../stores/reminderContextStore';
	import { getApiUrl } from '../../../config/api';
	import SettingsPageContainer from '../elements/SettingsPageContainer.svelte';
	import SettingsTextarea from '../elements/SettingsTextarea.svelte';
	import SettingsDropdown from '../elements/SettingsDropdown.svelte';
	import SettingsInfoBox from '../elements/SettingsInfoBox.svelte';
	import SettingsSectionHeading from '../elements/SettingsSectionHeading.svelte';
	import { chatMetadataCache } from '../../../services/chatMetadataCache';
	import { chatDB } from '../../../services/db';
	import {
		getCategoryGradientColors,
		getFallbackIconForCategory,
		getLucideIcon
	} from '../../../utils/categoryUtils';
	import { settingsMenuVisible } from '../../Settings.svelte';
	import { panelState } from '../../../stores/panelStateStore';
	import { createEventDispatcher } from 'svelte';

	const dispatch = createEventDispatcher();

	// ─── Chat context ──────────────────────────────────────────────────────────

	/** Chat ID from reminderContext store (set by bell button), fallback to activeChatStore */
	let contextChatId = $derived($reminderContext?.chatId || $activeChatStore || null);

	// ─── Chat metadata (title, category, icon — all from decrypted metadata) ──

	let chatTitle = $state<string | null>(null);
	let chatCategory = $state<string | null>(null);
	let chatIcon = $state<string | null>(null);

	/** Load decrypted metadata for the context chat */
	$effect(() => {
		if (!contextChatId) {
			chatTitle = null;
			chatCategory = null;
			chatIcon = null;
			return;
		}
		(async () => {
			const chat = await chatDB.getChat(contextChatId);
			if (!chat) return;
			const meta = await chatMetadataCache.getDecryptedMetadata(chat);
			if (meta) {
				chatTitle = meta.title;
				chatCategory = meta.category;
				chatIcon = meta.icon;
			}
		})();
	});

	let hasActiveChat = $derived(!!contextChatId && !!chatTitle);

	let categoryGradient = $derived(
		getCategoryGradientColors(chatCategory || 'general_knowledge')
	);
	let CategoryIcon = $derived(
		getLucideIcon(chatIcon || getFallbackIconForCategory(chatCategory || 'general_knowledge'))
	);

	// ─── Form state ────────────────────────────────────────────────────────────

	let date = $state('');
	let time = $state('');
	/** Reminder type: 'this_chat' (chat reminder notification) or 'new_task' (new chat + AI task) */
	let reminderMode = $state<'this_chat' | 'new_task'>('this_chat');
	let actionPrompt = $state('');
	let repeatType = $state('none');
	let customInterval = $state('1');
	let customUnit = $state('days');
	let endDate = $state('');

	let isSubmitting = $state(false);
	let errorMessage = $state('');

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
		{ value: 'custom', label: $text('common.custom') }
	]);

	let customUnitOptions = $derived([
		{ value: 'days', label: $text('reminder.panel.repeat_days') },
		{ value: 'weeks', label: $text('reminder.panel.repeat_weeks') },
		{ value: 'months', label: $text('reminder.panel.repeat_months') }
	]);

	/** Always show both options — Chat reminder + Task */
	let reminderModeOptions = $derived([
		{ value: 'this_chat', label: $text('reminder.settings.type_chat_reminder') },
		{ value: 'new_task', label: $text('reminder.settings.type_task') }
	]);

	// ─── Submission ────────────────────────────────────────────────────────────

	async function handleSubmit() {
		errorMessage = '';

		if (!date || !time) return;

		const triggerDatetime = `${date}T${time}:00`;
		const triggerMs = new Date(triggerDatetime).getTime();
		if (triggerMs <= Date.now()) {
			errorMessage = $text('reminder.panel.error_past');
			return;
		}

		isSubmitting = true;

		try {
			const isNewTask = reminderMode === 'new_task';
			const targetType = isNewTask ? 'new_chat' : 'existing_chat';
			const responseType = isNewTask ? 'full' : 'simple';
			const prompt =
				isNewTask && actionPrompt.trim()
					? actionPrompt.trim()
					: $text('reminder.panel.auto_prompt');

			const body: Record<string, unknown> = {
				prompt,
				trigger_type: 'specific',
				trigger_datetime: triggerDatetime,
				timezone,
				target_type: targetType,
				response_type: responseType
			};

			if (targetType === 'existing_chat' && contextChatId) {
				body._chat_id = contextChatId;
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
				body: JSON.stringify(body)
			});

			if (!response.ok) {
				let detail = `${response.status}`;
				try {
					const err = await response.json();
					detail = err.detail || err.error || detail;
				} catch {
					/* ignore */
				}
				errorMessage = $text('reminder.panel.error_generic');
				console.error('[SettingsReminders] API error:', detail);
				return;
			}

			// The external API wraps the skill response: { success, data: { success, error, ... } }
			const result = await response.json();
			const skillData = result.data || result;
			if (skillData.success === false) {
				errorMessage = skillData.error || $text('reminder.panel.error_generic');
				console.error('[SettingsReminders] Skill error:', skillData.error);
				return;
			}

			// Navigate to the reminder app store page so the user sees
			// their new reminder in the ActiveRemindersList.
			dispatch('openSettings', {
				settingsPath: 'app_store/reminder',
				direction: 'forward'
			});
		} catch (err) {
			errorMessage = $text('reminder.panel.error_generic');
			console.error('[SettingsReminders] fetch error:', err);
		} finally {
			isSubmitting = false;
		}
	}
</script>

<SettingsPageContainer>
	<!-- 1. Reminder type -->
	<SettingsSectionHeading
		icon="reminder"
		title={$text('reminder.settings.type_heading')}
	/>
	<SettingsDropdown
		bind:value={reminderMode}
		options={reminderModeOptions}
		ariaLabel={$text('reminder.settings.type_heading')}
	/>

	<!-- 2. Explainer text with icon, based on selected type -->
	<div class="explainer" data-testid="reminder-type-explainer">
		{#if reminderMode === 'this_chat'}
			<span class="explainer-icon" style="-webkit-mask-image: var(--icon-url-chat); mask-image: var(--icon-url-chat);"></span>
			<p class="explainer-text">{$text('reminder.settings.explainer_chat_reminder')}</p>
		{:else}
			<span class="explainer-icon" style="-webkit-mask-image: var(--icon-url-task); mask-image: var(--icon-url-task);"></span>
			<p class="explainer-text">{$text('reminder.settings.explainer_task')}</p>
		{/if}
	</div>

	<!-- 3. Chat context preview (clickable, when chat reminder + active chat) -->
	{#if hasActiveChat && reminderMode === 'this_chat'}
		<button
			class="chat-context"
			data-testid="chat-context"
			onclick={() => {
				settingsMenuVisible.set(false);
				panelState.closeSettings();
			}}
		>
			<div
				class="category-circle"
				style={categoryGradient
					? `background: linear-gradient(135deg, ${categoryGradient.start}, ${categoryGradient.end})`
					: 'background: #cccccc'}
			>
				<CategoryIcon size={16} color="white" />
			</div>
			<span class="chat-context-title">{chatTitle}</span>
		</button>
	{/if}

	<!-- 4. Task prompt (only for new_task mode) -->
	{#if reminderMode === 'new_task'}
		<SettingsSectionHeading
			icon="task"
			title={$text('reminder.settings.task_prompt_label')}
		/>
		<SettingsTextarea
			bind:value={actionPrompt}
			placeholder={$text('reminder.settings.task_prompt_placeholder')}
			ariaLabel={$text('reminder.settings.task_prompt_label')}
			rows={4}
		/>
	{/if}

	<!-- 5. Day? -->
	<SettingsSectionHeading
		icon="calendar"
		title={$text('reminder.settings.day_heading')}
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

	<!-- 6. Time? -->
	<SettingsSectionHeading
		icon="clock"
		title={$text('reminder.settings.time_heading')}
	/>
	<div class="native-input-wrapper">
		<input
			id="settings-reminder-time"
			class="native-input"
			type="time"
			bind:value={time}
		/>
	</div>

	<!-- 7. Repeat? -->
	<SettingsSectionHeading
		icon="reload"
		title={$text('reminder.settings.repeat_heading')}
	/>
	<SettingsDropdown
		bind:value={repeatType}
		options={repeatOptions}
		ariaLabel={$text('reminder.settings.repeat_heading')}
	/>

	{#if showCustomRepeat}
		<SettingsSectionHeading
			icon="reload"
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
		<SettingsSectionHeading
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

	<button
		data-testid="settings-button-primary"
		disabled={isSubmitting || !date || !time || (reminderMode === 'new_task' && !actionPrompt.trim())}
		onclick={handleSubmit}
	>
		{isSubmitting ? $text('reminder.panel.setting') : $text('reminder.settings.create_title')}
	</button>
</SettingsPageContainer>

<style>
	/* Explainer text block with icon (shown below Reminder type dropdown) */
	.explainer {
		display: flex;
		gap: 0.75rem;
		padding: 0.75rem 1rem;
		margin: 0 0.625rem;
	}

	.explainer-icon {
		flex-shrink: 0;
		width: 1.5rem;
		height: 1.5rem;
		margin-top: 0.125rem;
		background-color: var(--color-font-secondary, var(--color-grey-60));
		-webkit-mask-size: contain;
		mask-size: contain;
		-webkit-mask-repeat: no-repeat;
		mask-repeat: no-repeat;
	}

	.explainer-text {
		margin: 0;
		font-family:
			'Lexend Deca Variable',
			-apple-system,
			BlinkMacSystemFont,
			'Segoe UI',
			Roboto,
			sans-serif;
		font-size: var(--font-size-p, 0.875rem);
		font-weight: 500;
		line-height: 1.4;
		color: var(--color-font-secondary, var(--color-grey-60));
	}

	/* Clickable chat context preview card */
	.chat-context {
		display: flex;
		align-items: center;
		gap: 0.75rem;
		padding: 0.75rem 1rem;
		margin: 0 0.625rem;
		background: var(--color-grey-10);
		border-radius: 1rem;
		border: 1px solid var(--color-grey-25);
		cursor: pointer;
		transition: background 0.15s ease;
		width: calc(100% - 1.25rem);
		text-align: left;
	}

	.chat-context:hover {
		background: var(--color-grey-15);
	}

	.category-circle {
		flex-shrink: 0;
		width: 28px;
		height: 28px;
		border-radius: 50%;
		display: flex;
		align-items: center;
		justify-content: center;
		box-shadow: 0px 2px 4px rgba(0, 0, 0, 0.1);
		border: 2px solid var(--color-background);
	}

	.chat-context-title {
		font-family:
			'Lexend Deca Variable',
			-apple-system,
			BlinkMacSystemFont,
			'Segoe UI',
			Roboto,
			sans-serif;
		font-size: var(--font-size-p, 0.875rem);
		font-weight: 500;
		color: var(--color-font-primary);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	/* Wrapper to match SettingsDropdown horizontal padding */
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
		font-family:
			'Lexend Deca Variable',
			-apple-system,
			BlinkMacSystemFont,
			'Segoe UI',
			Roboto,
			sans-serif;
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
