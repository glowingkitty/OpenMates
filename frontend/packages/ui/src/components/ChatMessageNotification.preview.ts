/**
 * Preview mock data for ChatMessageNotification.
 *
 * This file provides sample props and named variants for the component preview system.
 * The ChatMessageNotification component renders a notification for incoming chat messages
 * with mate profile image, chat title, message preview, and inline reply input.
 * Access at: /dev/preview/ChatMessageNotification
 */

/** Default props — shows a chat message notification */
const defaultProps = {
	notification: {
		id: 'preview-chat-notif-1',
		type: 'chat_message' as const,
		message: 'I found some great options for your trip to Barcelona! Let me share the details.',
		chatId: 'preview-chat-abc',
		chatTitle: 'Travel Planning',
		avatarUrl: '',
		duration: 0,
		dismissible: true
	}
};

export default defaultProps;

/** Named variants for different notification states */
export const variants = {
	/** Long message — tests truncation */
	longMessage: {
		notification: {
			id: 'preview-chat-notif-long',
			type: 'chat_message' as const,
			message:
				'I have completed the analysis of your codebase and found several areas where we can improve performance. ' +
				'The main bottleneck appears to be in the data fetching layer, where multiple sequential API calls could be parallelized. ' +
				'Additionally, I noticed some components are re-rendering unnecessarily due to missing memoization.',
			chatId: 'preview-chat-def',
			chatTitle: 'Code Review',
			avatarUrl: '',
			duration: 0,
			dismissible: true
		}
	},

	/** Short message */
	shortMessage: {
		notification: {
			id: 'preview-chat-notif-short',
			type: 'chat_message' as const,
			message: 'Done!',
			chatId: 'preview-chat-ghi',
			chatTitle: 'Quick Task',
			avatarUrl: '',
			duration: 0,
			dismissible: true
		}
	},

	/** No chat title */
	noTitle: {
		notification: {
			id: 'preview-chat-notif-no-title',
			type: 'chat_message' as const,
			message: 'Here is the information you requested about the API endpoints.',
			chatId: 'preview-chat-jkl',
			avatarUrl: '',
			duration: 0,
			dismissible: true
		}
	}
};
