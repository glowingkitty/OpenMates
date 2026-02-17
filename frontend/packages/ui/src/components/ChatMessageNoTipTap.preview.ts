/**
 * Preview mock data for ChatMessageNoTipTap.
 *
 * This file provides sample props and named variants for the component preview system.
 * The ChatMessageNoTipTap component is a lightweight message renderer that does not use TipTap.
 * It requires a `children` Snippet for the message content.
 * Note: Since this component expects a Svelte Snippet for `children`, the preview system
 * may not be able to render the content area, but the layout/wrapper can be tested.
 * Access at: /dev/preview/ChatMessageNoTipTap
 */

/** Default props — shows a user message wrapper */
const defaultProps = {
	role: 'user' as const,
	messageParts: [],
	showScrollableContainer: false,
	defaultHidden: false,
	animated: false
};

export default defaultProps;

/** Named variants for different message types */
export const variants = {
	/** Assistant message */
	assistant: {
		role: 'assistant' as const,
		messageParts: [],
		showScrollableContainer: false,
		defaultHidden: false,
		animated: false
	},

	/** With scrollable container */
	scrollable: {
		role: 'assistant' as const,
		messageParts: [],
		showScrollableContainer: true,
		defaultHidden: false,
		animated: false
	},

	/** Hidden by default — collapsed state */
	hidden: {
		role: 'assistant' as const,
		messageParts: [],
		showScrollableContainer: false,
		defaultHidden: true,
		animated: false
	},

	/** Animated entry */
	animated: {
		role: 'user' as const,
		messageParts: [],
		showScrollableContainer: false,
		defaultHidden: false,
		animated: true
	}
};
