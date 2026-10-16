import { expect, it } from 'vitest';
import { teamChatTitleFromMessage } from '../teamChatTitle';

// contract-test: supporting surface=gui.web assertions=teams.chat.encrypted-until-invoked
it('uses the first human message rather than a generic Team chat title', () => {
  expect(teamChatTitleFromMessage('  Let’s meet\n near Alexanderplatz.  '))
    .toBe('Let’s meet near Alexanderplatz.');
});

// contract-test: supporting surface=gui.web assertions=teams.chat.encrypted-until-invoked
it('shortens long text without splitting an emoji or adding text to empty titles', () => {
  expect(teamChatTitleFromMessage('🎉'.repeat(81))).toBe('🎉'.repeat(79) + '…');
  expect(teamChatTitleFromMessage('   ')).toBe('New team chat');
});
