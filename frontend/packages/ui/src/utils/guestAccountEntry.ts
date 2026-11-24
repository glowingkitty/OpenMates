import { getLastAuthMethod } from './lastAuthMethod';

/** Open the app's account interface for a signed-out visitor. */
export function openGuestAccountEntry(): void {
  const event = getLastAuthMethod() ? 'openLoginInterface' : 'openSignupInterface';
  window.dispatchEvent(new Event(event));
}
