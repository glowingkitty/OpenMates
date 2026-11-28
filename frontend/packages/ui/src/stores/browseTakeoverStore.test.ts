import { describe, expect, it } from 'vitest';
import { notificationsForTakeover } from './browseTakeoverStore';

describe('notificationsForTakeover', () => {
  const items = [{ type: 'software_update' as const }, { type: 'error' as const }];
  // contract-test: supporting surface=gui.web assertions=web-browse.exclusive-takeover
  it('holds the software update toast back during take control only', () => {
    expect(notificationsForTakeover(items, true)).toEqual([{ type: 'error' }]);
    expect(notificationsForTakeover(items, false)).toEqual(items);
  });
});
