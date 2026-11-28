/**
 * True while the user drives a live Browse browser (take control). Global
 * toasts that would cover the browser deliver after control ends.
 */
import { writable } from 'svelte/store';
import type { Notification } from './notificationStore';

export const browseTakeoverActive = writable(false);

/** Types that are held back, not dropped, during take control. */
const DEFERRED_DURING_TAKEOVER = new Set(['software_update']);

export function notificationsForTakeover<T extends Pick<Notification, 'type'>>(items: T[], takeover: boolean): T[] {
  return takeover ? items.filter(item => !DEFERRED_DURING_TAKEOVER.has(item.type)) : items;
}
