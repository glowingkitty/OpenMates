/**
 * Preview mock data for ReminderEmbedFullscreen.
 *
 * This file provides sample props and named variants for the component preview system.
 * Access at: /dev/preview/embeds/reminder/ReminderEmbedFullscreen
 */

/** Default props — shows a fullscreen reminder detail view */
const defaultProps = {
	reminderId: 'rem-abc-123',
	triggerAtFormatted: 'Tomorrow at 9:00 AM',
	triggerAt: Math.floor(Date.now() / 1000) + 86400,
	targetType: 'new_chat' as const,
	isRepeating: false,
	message: 'Reminder set successfully! I will remind you tomorrow at 9:00 AM.',
	onClose: () => console.log('[Preview] Close clicked'),
	hasPreviousEmbed: false,
	hasNextEmbed: false,
	onReminderCancelled: (id: string) => console.log(`[Preview] Reminder cancelled: ${id}`)
};

export default defaultProps;

/** Named variants for different component states */
export const variants = {
	/** With navigation arrows */
	withNavigation: {
		...defaultProps,
		hasPreviousEmbed: true,
		hasNextEmbed: true,
		onNavigatePrevious: () => console.log('[Preview] Navigate previous'),
		onNavigateNext: () => console.log('[Preview] Navigate next')
	},

	/** Repeating reminder */
	repeating: {
		...defaultProps,
		isRepeating: true,
		triggerAtFormatted: 'Every Monday at 9:00 AM',
		message: 'Repeating reminder set! I will remind you every Monday at 9:00 AM.'
	},

	/** Error state */
	error: {
		...defaultProps,
		error: 'Could not create reminder: invalid trigger time.',
		message: undefined
	},

	/** With email notification warning */
	withEmailWarning: {
		...defaultProps,
		emailNotificationWarning:
			'Email notifications are not enabled. You will only receive in-app notifications.'
	}
};
