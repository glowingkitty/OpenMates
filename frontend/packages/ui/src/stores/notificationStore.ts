// frontend/packages/ui/src/stores/notificationStore.ts
/**
 * @file notificationStore.ts
 * @description Svelte store for managing and displaying global notifications (toasts/alerts).
 *
 * Notification Types:
 * - info: General informational notifications
 * - success: Success confirmations
 * - warning: Warning alerts
 * - error: Error messages
 * - auto_logout: User session expiration warnings
 * - connection: Server connection status
 * - software_update: Available software updates
 * - chat_message: New chat message notifications (with reply input)
 */
import { writable } from "svelte/store";

/**
 * Notification types supported by the system
 * - Basic types: info, success, warning, error
 * - System types: auto_logout, connection, software_update
 * - Chat types: chat_message (with embedded reply input)
 */
export type NotificationType =
  | "info"
  | "success"
  | "warning"
  | "error"
  | "auto_logout"
  | "connection"
  | "software_update"
  | "chat_message";

/**
 * Notification interface
 * Extended to support the new notification design with:
 * - title: Header text (e.g., "Auto logout", "Can't connect to server")
 * - message: Primary message (highlighted in primary color)
 * - messageSecondary: Secondary message (in bold font color)
 * - chatId: For chat_message notifications, the chat ID to reply to
 * - avatarUrl: For chat_message notifications, the avatar image URL
 * - onAction: Optional callback for an action button (e.g., "Tap to reconnect")
 * - actionLabel: Label text for the action button
 */
export interface Notification {
  id: string;
  type: NotificationType;
  title?: string; // Header title text
  message: string; // Primary message (displayed in primary color)
  messageSecondary?: string; // Secondary message (displayed in bold)
  duration?: number; // Duration in ms, if undefined, notification is persistent until dismissed
  dismissible?: boolean; // Whether the notification can be dismissed by the user

  // Action button support (e.g., "Tap to reconnect" on connection notifications)
  onAction?: () => void; // Callback when action button is clicked
  actionLabel?: string; // Label text for the action button

  // Chat message notification specific fields
  chatId?: string; // The chat ID for reply functionality
  chatTitle?: string; // The chat title to display
  avatarUrl?: string; // Avatar image URL for chat message notifications
}

/**
 * Options for creating a notification
 */
export interface NotificationOptions {
  title?: string;
  message: string;
  messageSecondary?: string;
  duration?: number;
  dismissible?: boolean;
  onAction?: () => void; // Optional callback for action button
  actionLabel?: string; // Label text for the action button
  chatId?: string;
  chatTitle?: string;
  avatarUrl?: string;
}

export interface NotificationState {
  notifications: Notification[];
}

const initialState: NotificationState = {
  notifications: [],
};

const { subscribe, update } = writable<NotificationState>(initialState);

let notificationIdCounter = 0;

export const notificationStore = {
  subscribe,

  /**
   * Add a notification with full options support
   */
  addNotification: (
    type: NotificationType,
    message: string,
    duration: number = 5000,
    dismissible: boolean = true,
  ) => {
    const id = `notification-${notificationIdCounter++}`;
    const newNotification: Notification = {
      id,
      type,
      message,
      duration,
      dismissible,
    };

    update((state) => {
      return {
        notifications: [...state.notifications, newNotification],
      };
    });

    if (duration) {
      setTimeout(() => {
        notificationStore.removeNotification(id);
      }, duration);
    }
    return id;
  },

  /**
   * Add a notification with extended options (new design support)
   */
  addNotificationWithOptions: (
    type: NotificationType,
    options: NotificationOptions,
  ) => {
    const id = `notification-${notificationIdCounter++}`;
    const newNotification: Notification = {
      id,
      type,
      ...options,
      duration: options.duration ?? 5000,
      dismissible: options.dismissible ?? true,
    };

    update((state) => {
      return {
        notifications: [...state.notifications, newNotification],
      };
    });

    if (newNotification.duration) {
      setTimeout(() => {
        notificationStore.removeNotification(id);
      }, newNotification.duration);
    }
    return id;
  },

  removeNotification: (id: string) => {
    update((state) => {
      return {
        notifications: state.notifications.filter((n) => n.id !== id),
      };
    });
  },

  clearAllNotifications: () => {
    update(() => {
      return {
        notifications: [],
      };
    });
  },

  // Basic convenience methods (legacy API)
  info: (message: string, duration?: number, dismissible?: boolean) =>
    notificationStore.addNotification("info", message, duration, dismissible),
  success: (message: string, duration?: number, dismissible?: boolean) =>
    notificationStore.addNotification(
      "success",
      message,
      duration,
      dismissible,
    ),
  warning: (message: string, duration?: number, dismissible?: boolean) =>
    notificationStore.addNotification(
      "warning",
      message,
      duration ?? 7000,
      dismissible,
    ),
  error: (message: string, duration?: number, dismissible?: boolean) =>
    notificationStore.addNotification(
      "error",
      message,
      duration ?? 10000,
      dismissible ?? true,
    ),

  // Extended notification methods (new design)

  /**
   * Show auto-logout notification
   * @param message Primary message (e.g., "Enable 'Stay logged in' during login to prevent this.")
   * @param messageSecondary Secondary message (optional)
   * @param duration Duration in ms (default 7000)
   * @param title Custom title (default "You have been logged out")
   */
  autoLogout: (
    message: string,
    messageSecondary?: string,
    duration?: number,
    title?: string,
  ) =>
    notificationStore.addNotificationWithOptions("auto_logout", {
      title: title ?? "You have been logged out",
      message,
      messageSecondary,
      duration: duration ?? 7000,
    }),

  /**
   * Show connection status notification
   * @param message Primary message (e.g., "Trying to reconnect for 30 seconds.")
   * @param messageSecondary Secondary message (e.g., "Else Offline Mode will be activated.")
   */
  connection: (message: string, messageSecondary?: string, duration?: number) =>
    notificationStore.addNotificationWithOptions("connection", {
      title: "Can't connect to server.",
      message,
      messageSecondary,
      duration: duration ?? 0, // Persistent until connection restored
      dismissible: true,
    }),

  /**
   * Show software update notification
   * @param message Primary message (e.g., "OpenMates v0.3 is available now.")
   * @param messageSecondary Secondary message (e.g., "Check your server settings to install it.")
   */
  softwareUpdate: (
    message: string,
    messageSecondary?: string,
    duration?: number,
  ) =>
    notificationStore.addNotificationWithOptions("software_update", {
      title: "Software update available",
      message,
      messageSecondary,
      duration: duration ?? 10000,
    }),

  /**
   * Show chat message notification for background chats
   * @param chatId The chat ID for reply functionality
   * @param chatTitle The chat title to display
   * @param message The message preview text
   * @param avatarUrl Optional avatar URL
   */
  chatMessage: (
    chatId: string,
    chatTitle: string,
    message: string,
    avatarUrl?: string,
  ) =>
    notificationStore.addNotificationWithOptions("chat_message", {
      title: chatTitle,
      message,
      chatId,
      chatTitle,
      avatarUrl,
      duration: 3000, // 3 seconds as specified
      dismissible: true,
    }),
};

// Example Usage:
// import { notificationStore } from './notificationStore';
//
// // Legacy API (still works)
// notificationStore.success('Profile updated successfully!');
// notificationStore.error('Failed to save changes. Please try again.');
//
// // New design API
// notificationStore.autoLogout("Consider activating 'Stay logged in'.", "During login, to remain connected.");
// notificationStore.connection("Trying to reconnect for 30 seconds.", "Else Offline Mode will be activated.");
// notificationStore.softwareUpdate("OpenMates v0.3 is available now.", "Check your server settings to install it.");
// notificationStore.chatMessage("chat-123", "Offline Whisper iOS Integration", "As promised, here the updated code...");
