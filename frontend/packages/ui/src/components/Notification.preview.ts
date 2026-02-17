/**
 * Preview mock data for Notification.
 *
 * This file provides sample props and named variants for the component preview system.
 * The Notification component renders a toast notification with swipe-to-dismiss gesture.
 * Access at: /dev/preview/Notification
 */

/** Default props — shows a success notification toast */
const defaultProps = {
	notification: {
		id: 'preview-notification-1',
		type: 'success' as const,
		title: 'Changes saved',
		message: 'Your settings have been updated successfully.',
		duration: 0,
		dismissible: true
	}
};

export default defaultProps;

/** Named variants for different notification types */
export const variants = {
	/** Info notification */
	info: {
		notification: {
			id: 'preview-notification-info',
			type: 'info' as const,
			title: 'New feature available',
			message: 'You can now export your conversations to PDF format.',
			duration: 0,
			dismissible: true
		}
	},

	/** Warning notification */
	warning: {
		notification: {
			id: 'preview-notification-warning',
			type: 'warning' as const,
			title: 'Storage almost full',
			message: 'You are using 95% of your available storage.',
			duration: 0,
			dismissible: true
		}
	},

	/** Error notification */
	error: {
		notification: {
			id: 'preview-notification-error',
			type: 'error' as const,
			title: 'Connection failed',
			message: 'Could not connect to the server. Please check your internet connection.',
			duration: 0,
			dismissible: true
		}
	},

	/** Auto-logout notification */
	autoLogout: {
		notification: {
			id: 'preview-notification-logout',
			type: 'auto_logout' as const,
			message: 'You have been logged out due to inactivity.',
			duration: 0,
			dismissible: true
		}
	},

	/** Connection status notification */
	connection: {
		notification: {
			id: 'preview-notification-connection',
			type: 'connection' as const,
			message: 'Reconnecting to the server...',
			duration: 0,
			dismissible: false
		}
	},

	/** Software update notification */
	softwareUpdate: {
		notification: {
			id: 'preview-notification-update',
			type: 'software_update' as const,
			title: 'Update available',
			message: 'A new version is available. Refresh to update.',
			duration: 0,
			dismissible: true,
			actionLabel: 'Refresh now',
			onAction: () => console.log('[Preview] Update action clicked')
		}
	},

	/** With action button */
	withAction: {
		notification: {
			id: 'preview-notification-action',
			type: 'info' as const,
			title: 'Download ready',
			message: 'Your export file is ready for download.',
			duration: 0,
			dismissible: true,
			actionLabel: 'Download',
			onAction: () => console.log('[Preview] Download action clicked')
		}
	},

	/** With secondary message */
	withSecondary: {
		notification: {
			id: 'preview-notification-secondary',
			type: 'success' as const,
			title: 'File uploaded',
			message: 'document.pdf has been uploaded successfully.',
			messageSecondary: 'File size: 2.4 MB',
			duration: 0,
			dismissible: true
		}
	}
};
