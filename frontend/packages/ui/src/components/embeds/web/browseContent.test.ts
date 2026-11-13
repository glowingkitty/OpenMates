import { describe, expect, it } from 'vitest';
import { browseContent, browsePhaseKey, browseStepKey, browseStepShowsLabel, canViewBrowseSession } from './browseContent';

// contract-test: supporting surface=gui.web assertions=web-browse.private-storage-and-api,web-browse.exclusive-takeover
describe('Browse live owner boundary', () => {
  const owner = { chatId: 'owner-chat', lookupChatId: 'owner-chat', isReadOnly: false };
  // contract-test: supporting surface=gui.web assertions=web-browse.private-storage-and-api,web-browse.exclusive-takeover
  it('permits a normal owner chat whose lookup points to that same chat', () => {
    expect(canViewBrowseSession(true, 'owner', owner)).toBe(true);
    expect(canViewBrowseSession(true, 'owner', { ...owner, lookupChatId: null })).toBe(true);
  });
  // contract-test: supporting surface=gui.web assertions=web-browse.private-storage-and-api,web-browse.exclusive-takeover
  it('denies public, shared, cross-chat, missing-policy and unauthenticated views', () => {
    expect(canViewBrowseSession(false, 'owner', owner)).toBe(false);
    expect(canViewBrowseSession(true, null, owner)).toBe(false);
    for (const source of [undefined, { ...owner, chatId: null }, { ...owner, isReadOnly: true },
      { ...owner, isReadOnly: undefined }, { ...owner, exampleChatId: 'public-example' },
      { ...owner, lookupChatId: 'another-chat' }]) {
      expect(canViewBrowseSession(true, 'owner', source)).toBe(false);
    }
  });
});

// contract-test: supporting surface=gui.web assertions=web-browse.structured-data,web-browse.truthful-completion,web-browse.private-storage-and-api
describe('saved Browse result boundary', () => {
  it('uses the real outcome and restores exact JSON without guessing flattened key paths', () => {
    const data = { a_b: { c: null }, a: { b_c: [] }, values: ['a|b', 'c'], ok: false, count: 0 };
    const output = browseContent({ status: 'finished', results: [{ status: 'needs_user', data_json: JSON.stringify(data), data_a_b_c: 'ambiguous' }] });
    expect(output.status).toBe('needs_user');
    expect(output.data).toEqual(data);
  });
  // contract-test: supporting surface=gui.web assertions=web-browse.private-storage-and-api
  it('does not render arbitrary URL schemes as saved screenshots', () => {
    for (const screenshot_base64 of ['https://tracker.invalid/pixel', 'data:image/svg+xml,<svg/>', '<script>'])
      expect(browseContent({ screenshot_base64 }).screenshot).toBe('');
  });
  // contract-test: supporting surface=gui.web assertions=web-browse.structured-data,web-browse.truthful-completion
  it('keeps malformed JSON unavailable rather than inventing a result', () => {
    expect(browseContent({ data_json: '{invalid', data_a_b: 'text' }).data).toBe(null);
  });
});

// contract-test: supporting surface=gui.web assertions=web-browse.truthful-completion,web-browse.structured-data
describe('Browse partial verification and step helpers', () => {
  it('reads the unverified paths from the result and ignores malformed entries', () => {
    const output = browseContent({ status: 'finished', results: [{ status: 'completed', missing: ['items[0].price', ' purpose ', '', 4, null] }] });
    expect(output.missing).toEqual(['items[0].price', 'purpose']);
  });
  // contract-test: supporting surface=gui.web assertions=web-browse.truthful-completion
  it('treats absent, empty or non-array missing as complete', () => {
    expect(browseContent({ status: 'finished', results: [{ status: 'completed' }] }).missing).toEqual([]);
    expect(browseContent({ status: 'finished', results: [{ status: 'completed', missing: [] }] }).missing).toEqual([]);
    expect(browseContent({ status: 'finished', results: [{ status: 'completed', missing: 'purpose' }] }).missing).toEqual([]);
  });
  // contract-test: supporting surface=gui.web assertions=web-browse.embed-and-observation
  it('maps step kinds to translated verbs and shows labels only for element actions', () => {
    expect(browseStepKey('click')).toBe('embeds.browse.step_click');
    expect(browseStepKey('back')).toBe('embeds.browse.step_back');
    expect(browseStepKey('unknown')).toBe('embeds.browse.step_goto');
    expect(browseStepShowsLabel('type')).toBe(true);
    expect(browseStepShowsLabel('scroll')).toBe(false);
    expect(browsePhaseKey('starting')).toBe('embeds.browse.phase_starting');
    expect(browsePhaseKey('idle')).toBe('');
    expect(browsePhaseKey(undefined)).toBe('');
  });
});
