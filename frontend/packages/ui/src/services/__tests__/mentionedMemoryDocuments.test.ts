import { beforeEach, expect, it, vi } from 'vitest';
const mocks = vi.hoisted(() => ({personal: vi.fn(), db: vi.fn()}));
vi.mock('../../stores/appSettingsMemoriesStore', async () => {
  const {writable} = await import('svelte/store');
  return {appSettingsMemoriesStore: writable({entriesByApp: new Map(), decryptedEntries: new Map()})};
});
vi.mock('../ruleDocumentService', () => ({personalDocumentMemoryEntries: mocks.personal}));
vi.mock('../db', () => ({chatDB: {getAppSettingsMemoriesEntry: mocks.db}}));
vi.mock('../cryptoService', () => ({decryptWithMasterKey: vi.fn()}));
import {extractMentionedSettingsMemoriesCleartext} from '../mentionedSettingsMemoriesCleartext';
const entries = ['a', 'b'].map(id => ({id: `account-memory-${id}`, app_id: 'openmates', settings_group: 'memories',
  item_value: {title: id, document: `Private guide ${id}`}}));
beforeEach(() => {vi.clearAllMocks(); mocks.personal.mockResolvedValue(entries); mocks.db.mockResolvedValue(null);});

// contract-test: supporting surface=gui.web assertions=app-memories.conversation.explicit-approval,app-memories.access.owner-scoped
it('includes only the explicitly mentioned private entry, without reading unrelated memories', async () => {
  expect(await extractMentionedSettingsMemoriesCleartext('Use @memory-entry:openmates:memories:account-memory-a')).toEqual({
    'openmates:memories': [entries[0].item_value],
  });
  expect(mocks.db).not.toHaveBeenCalled();
});

// contract-test: supporting surface=gui.web assertions=app-memories.conversation.explicit-approval
it('includes the whole account category only when explicitly mentioned', async () => {
  expect(await extractMentionedSettingsMemoriesCleartext('Use @memory:openmates:memories:list')).toEqual({
    'openmates:memories': entries.map(entry => entry.item_value),
  });
});

// contract-test: supporting surface=gui.web assertions=app-memories.conversation.explicit-approval
it('does not decrypt legacy personal guides for an ordinary request', async () => {
  expect(await extractMentionedSettingsMemoriesCleartext('Work on this project')).toEqual({});
  expect(mocks.personal).not.toHaveBeenCalled();
});
