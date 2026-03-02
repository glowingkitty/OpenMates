/**
 * Preview mock data for ReminderEmbedPreview.
 *
 * This file provides sample props and named variants for the component preview system.
 * Access at: /dev/preview/embeds/reminder/ReminderEmbedPreview
 */

/** Default props — shows a finished reminder embed card */
const defaultProps = {
	id: 'preview-reminder-1',
	reminderId: 'rem-abc-123',
	triggerAtFormatted: 'Tomorrow at 9:00 AM',
	triggerAt: Math.floor(Date.now() / 1000) + 86400,
	targetType: 'new_chat' as const,
	isRepeating: false,
	prompt: 'Review the pull request for the new authentication module',
	message: 'Reminder set successfully! I will remind you tomorrow at 9:00 AM.',
	status: 'finished' as const,
	isMobile: false,
	onFullscreen: () => console.log('[Preview] Fullscreen clicked')
};

export default defaultProps;

/** Named variants for different component states */
export const variants = {
	/** Processing state — shows loading animation */
	processing: {
		id: 'preview-reminder-processing',
		prompt: 'Setting up your reminder...',
		status: 'processing' as const,
		isMobile: false
	},

	/** Error state */
	error: {
		id: 'preview-reminder-error',
		prompt: 'Remind me about the meeting',
		status: 'error' as const,
		error: 'Could not create reminder: invalid trigger time.',
		isMobile: false
	},

	/** Repeating reminder */
	repeating: {
		...defaultProps,
		id: 'preview-reminder-repeating',
		isRepeating: true,
		triggerAtFormatted: 'Every Monday at 9:00 AM',
		prompt: 'Weekly standup meeting preparation',
		message: 'Repeating reminder set! I will remind you every Monday at 9:00 AM.'
	},

	/** Existing chat target */
	existingChat: {
		...defaultProps,
		id: 'preview-reminder-existing-chat',
		targetType: 'existing_chat' as const,
		prompt: 'Follow up on the design review feedback',
		message: 'Reminder set! I will send a message in this chat tomorrow at 9:00 AM.'
	},

	/** With email notification warning */
	withEmailWarning: {
		...defaultProps,
		id: 'preview-reminder-email-warning',
		emailNotificationWarning:
			'Email notifications are not enabled. You will only receive in-app notifications.'
	},

	/** Mobile view */
	mobile: {
		...defaultProps,
		id: 'preview-reminder-mobile',
		isMobile: true
	}
};
