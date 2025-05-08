// frontend/packages/ui/src/stores/notificationStore.ts
/**
 * @file notificationStore.ts
 * @description Svelte store for managing and displaying global notifications (toasts/alerts).
 */
import { writable } from 'svelte/store';

export type NotificationType = 'info' | 'success' | 'warning' | 'error';

export interface Notification {
  id: string;
  type: NotificationType;
  message: string;
  duration?: number; // Optional: duration in ms, if undefined, notification is persistent until dismissed
  dismissible?: boolean; // Optional: whether the notification can be dismissed by the user
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
  addNotification: (
    type: NotificationType,
    message: string,
    duration: number = 5000, // Default duration 5 seconds
    dismissible: boolean = true
  ) => {
    const id = `notification-${notificationIdCounter++}`;
    const newNotification: Notification = { id, type, message, duration, dismissible };

    update(state => {
      return {
        notifications: [...state.notifications, newNotification],
      };
    });

    if (duration) {
      setTimeout(() => {
        notificationStore.removeNotification(id);
      }, duration);
    }
    return id; // Return ID in case manual removal is needed earlier
  },
  removeNotification: (id: string) => {
    update(state => {
      return {
        notifications: state.notifications.filter(n => n.id !== id),
      };
    });
  },
  clearAllNotifications: () => {
    update(state => {
      return {
        notifications: [],
      };
    });
  },
  // Convenience methods
  info: (message: string, duration?: number, dismissible?: boolean) =>
    notificationStore.addNotification('info', message, duration, dismissible),
  success: (message: string, duration?: number, dismissible?: boolean) =>
    notificationStore.addNotification('success', message, duration, dismissible),
  warning: (message: string, duration?: number, dismissible?: boolean) =>
    notificationStore.addNotification('warning', message, duration ?? 7000, dismissible), // Longer default for warnings
  error: (message: string, duration?: number, dismissible?: boolean) =>
    notificationStore.addNotification('error', message, duration ?? 10000, dismissible ?? true), // Longer default for errors, always dismissible
};

// Example Usage:
// import { notificationStore } from './notificationStore';
// notificationStore.success('Profile updated successfully!');
// notificationStore.error('Failed to save changes. Please try again.');
//
// In a Svelte component (e.g., a Toaster.svelte component):
// import { notificationStore } from './notificationStore';
// $: notifications = $notificationStore.notifications;