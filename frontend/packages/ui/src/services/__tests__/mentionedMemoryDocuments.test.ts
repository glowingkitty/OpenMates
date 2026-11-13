import { beforeEach, expect, it, vi } from 'vitest';
const mocks = vi.hoisted(() => ({personal: vi.fn()}));
vi.mock('../ruleDocumentService', () => ({personalDocumentMemoryEntries: mocks.personal}));
import {extractMentionedSettingsMemoriesCleartext} from '../mentionedSettingsMemoriesCleartext';
const entries = ['a', 'b'].map(id => ({id: `account-memory-${id}`, app_id: 'openmates', settings_group: 'memories',
  item_value: {title: id, document: `Private guide ${id}`}}));
beforeEach(() => {vi.clearAllMocks(); mocks.personal.mockResolvedValue(entries);});

// contract-test: supporting surface=gui.web assertions=app-memories.conversation.explicit-approval,app-memories.access.owner-scoped
it('includes only the explicitly mentioned private entry, without reading unrelated memories', async () => {
  expect(await extractMentionedSettingsMemoriesCleartext('Use @memory-entry:openmates:memories:account-memory-a')).toEqual({
    'openmates:memories': [entries[0].item_value],
  });
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

// contract-test: supporting surface=gui.web assertions=app-memories.conversation.explicit-approval
it('resolves a free-form memory mentioned by its title slug', async () => {
  mocks.personal.mockResolvedValue([{...entries[0], item_value: {title: 'Travel Plans', document: 'Private travel'}}]);
  expect(await extractMentionedSettingsMemoriesCleartext('Use @memory-entry:openmates:memories:travel-plans')).toEqual({
    'openmates:memories': [{title: 'Travel Plans', document: 'Private travel'}],
  });
});
