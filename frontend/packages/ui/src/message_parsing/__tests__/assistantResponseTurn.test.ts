import { describe, expect, it } from 'vitest';
import { responseUserMessageId } from '../assistantResponseTurn';

describe('responseUserMessageId', () => {
  const messages = [
    { role: 'user', status: 'synced', message_id: 'current-turn' },
    { role: 'user', status: 'sending', message_id: 'new-follow-up' },
  ];

  // contract-test: direct surface=gui.web assertions=chat-processing-feedback.turn-lifecycle
  it('keeps the accepted task active while a follow-up sends and becomes queued', () => {
    expect(responseUserMessageId('current-turn', null, messages)).toBe('current-turn');
    expect(responseUserMessageId('current-turn', null, [
      messages[0], { ...messages[1], status: 'queued' },
    ])).toBe('current-turn');
    expect(responseUserMessageId(null, 'current-turn', messages)).toBe('current-turn');
  });

  // contract-test: direct surface=gui.web assertions=chat-processing-feedback.turn-lifecycle
  it('uses the latest nonqueued user only before an accepted task ID exists', () => {
    expect(responseUserMessageId(null, null, messages)).toBe('new-follow-up');
    expect(responseUserMessageId(null, null, [
      messages[0], { ...messages[1], status: 'queued' },
    ])).toBe('current-turn');
  });
});
