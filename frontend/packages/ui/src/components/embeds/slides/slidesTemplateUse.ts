/**
 * frontend/packages/ui/src/components/embeds/slides/slidesTemplateUse.ts
 *
 * "Use this design" of a slide template embed: asks the active chat to send a
 * user message naming the design. The chat (ActiveChat) listens for the event and
 * sends it through the same path as a follow-up suggestion click.
 */

export const SEND_CHAT_MESSAGE_EVENT = 'openmates:send-chat-message';

/** sessionStorage key an isolated E2E sets so the next press carries a replay marker. */
export const E2E_SEND_MARKER_KEY = 'openmates:e2e-send-marker';

/** Send `message` as the user's next chat message in the current chat. */
export function sendChatMessage(message: string): void {
  const marker = sessionStorage.getItem(E2E_SEND_MARKER_KEY);
  const detail = marker ? { message, testMockMarker: marker } : { message };
  window.dispatchEvent(new CustomEvent(SEND_CHAT_MESSAGE_EVENT, { detail }));
}
