/**
 * Sends the `inspiration_viewed` WebSocket event for a Daily Inspiration card the
 * user can actually see. The backend counts views to decide whether a user gets a
 * new personalized set the next day, so every surface that shows inspiration cards
 * (the guest landing banner and the start-screen rows) reports through here.
 *
 * Authenticated only: guests have no WebSocket and nothing is tracked for them.
 * Each id is sent at most once per page session.
 */
import { get } from 'svelte/store';
import { authStore } from '../stores/authStore';

const sentIds = new Set<string>();

export async function sendInspirationViewed(inspirationId: string): Promise<void> {
  if (!get(authStore).isAuthenticated || sentIds.has(inspirationId)) return;
  let superseded: (error: unknown) => boolean = () => false;
  try {
    const { webSocketService, isWebSocketConnectionChanged } = await import('./websocketService');
    superseded = isWebSocketConnectionChanged;
    if (!webSocketService.isConnected()) {
      console.debug('[dailyInspirationViewed] Skipping inspiration_viewed while WebSocket is disconnected:', inspirationId);
      return;
    }
    sentIds.add(inspirationId);
    await webSocketService.sendMessage('inspiration_viewed', { inspiration_id: inspirationId });
  } catch (err) {
    sentIds.delete(inspirationId);
    // A reconnect replacing the socket is an expected race, not a failure.
    const logFn = superseded(err) ? console.warn : console.error;
    logFn('[dailyInspirationViewed] Failed to send inspiration_viewed:', err);
  }
}
