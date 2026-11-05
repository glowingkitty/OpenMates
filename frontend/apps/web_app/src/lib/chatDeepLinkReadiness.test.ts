import { describe, expect, it } from 'vitest';
import { isResolvedChatMessageLink } from '../../tests/helpers/chat-hydration';

describe('resolved chat message readiness', () => {
  const canonical = 'http://localhost:5173/#chat-id=chat-1&message-id=message-1';

  // contract-test: supporting surface=gui.web assertions=notifications.workflow-run.chat-target
  it('rejects the incoming pending URL even though its prefix already names the exact message', () => {
    const pending = `${canonical}&delivery-id=delivery-1&workflow-id=workflow-1&run-id=run-1&workflow-tab=runs`;
    expect(isResolvedChatMessageLink(new URL(pending), 'chat-1', 'message-1')).toBe(false);
    expect(isResolvedChatMessageLink(new URL(canonical), 'chat-1', 'message-1')).toBe(true);
  });

  // contract-test: supporting surface=gui.web assertions=notifications.workflow-run.chat-target
  it('requires the exact root chat/message destination and keeps query diagnostics independent', () => {
    expect(isResolvedChatMessageLink(new URL(canonical), 'chat-1', 'other-message')).toBe(false);
    expect(isResolvedChatMessageLink(new URL(canonical), 'other-chat', 'message-1')).toBe(false);
    expect(isResolvedChatMessageLink(new URL(canonical.replace('/#', '/workflows#')), 'chat-1', 'message-1')).toBe(false);
    expect(isResolvedChatMessageLink(new URL(canonical.replace('/#', '/?e2e-debug=run#')), 'chat-1', 'message-1')).toBe(true);
  });
});
