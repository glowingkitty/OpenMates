import { describe, expect, it } from 'vitest';
import { buildWholeDocumentPatch, isMemoryActive, isMemoryExpiredBeyondGrace, parseRuleDocument, serializeRuleDocument, validateRuleCatalog } from '../ruleDocuments';
import { applyProjectFilePatch } from '../projectFilePatch';

const guide = '---\ntitle: Python practices\ndescription: Reliable services.\nwhen_to_use: Writing Python.\n---\n- Release resources.\n- Preserve cancellation.\n';

describe('Rule Markdown boundaries', () => {
  // contract-test: supporting surface=gui.web assertions=rules.definition.guide-format
  it('round-trips a coherent guide without separate bullet records', () => {
    const fields = parseRuleDocument(guide);
    expect(fields.body.split('\n')).toHaveLength(2);
    expect(parseRuleDocument(serializeRuleDocument(fields))).toEqual(fields);
    expect(validateRuleCatalog([{ id: 'personal:r', source: 'personal', document: guide }])).toHaveLength(1);
  });

  // contract-test: supporting surface=gui.web assertions=rules.definition.guide-format
  it.each([
    guide.replace('title: Python practices', 'title: A\ntitle: B'),
    guide.replace('description: Reliable services.', 'description: &name Reliable\nwhen_to_use: *name'),
    guide.replace('description: Reliable services.', 'description: [wrong, type]'),
    guide.replace('title: Python practices', 'title: ""'),
    guide.replace('description: Reliable services.', 'description: &a A\nunknown: *a'),
    guide.replace('- Release resources.\n- Preserve cancellation.', ''),
    guide + 'x'.repeat(24_000),
  ])('rejects malformed or ambiguous document %#', (document) => {
    expect(() => parseRuleDocument(document)).toThrow();
  });

  // contract-test: supporting surface=gui.web assertions=rules.ownership.encrypted-custom
  it('rejects duplicate identities and invalid source binding', () => {
    const rule = { id: 'personal:r', source: 'personal' as const, document: guide };
    expect(() => validateRuleCatalog([rule, rule])).toThrow();
    expect(() => validateRuleCatalog([{ ...rule, source: 'project' }])).toThrow();
    expect(() => validateRuleCatalog([{ ...rule, id: 'app:code:spoof' }])).toThrow();
  });
});

const canonical = '---\ntitle: Trip\nload_mode: ask_first\nvalid_from: "2026-01-01T00:00:00Z"\nvalid_until: "2026-02-01T00:00:00Z"\nreferences:\n  - kind: embed\n    id: e1\n  - kind: chat\n    id: c1\n---\nPacking list.\n';

// contract-test: supporting surface=rest_api assertions=app-memories.document.canonical-shape,app-memories.load-modes,app-memories.references.embeds-and-chats
describe('canonical Memory shape', () => {
  it('parses and round-trips every new field with blank when_to_use', () => {
    const fields = parseRuleDocument(canonical);
    expect(fields).toMatchObject({ title: 'Trip', when_to_use: '', load_mode: 'ask_first', body: 'Packing list.' });
    expect(fields.references).toEqual([{ kind: 'embed', id: 'e1' }, { kind: 'chat', id: 'c1' }]);
    expect(parseRuleDocument(serializeRuleDocument(fields))).toEqual(fields);
  });

  // contract-test: supporting surface=gui.web assertions=app-memories.document.canonical-shape
  it('keeps legacy description documents and minimal title+body documents valid', () => {
    expect(parseRuleDocument(guide).description).toBe('Reliable services.');
    expect(parseRuleDocument('---\ntitle: T\n---\nBody\n')).toEqual({ title: 'T', when_to_use: '', body: 'Body' });
  });

  // contract-test: supporting surface=gui.web assertions=app-memories.document.canonical-shape
  it.each([
    canonical.replace('ask_first', 'sometimes'),
    canonical.replace('2026-02-01T00:00:00Z', '2025-01-01T00:00:00Z'),
    canonical.replace('"2026-01-01T00:00:00Z"', 'not-a-date'),
    canonical.replace('kind: chat', 'kind: note'),
    canonical.replace('id: c1', 'id: e1').replace('kind: chat', 'kind: embed'),
    canonical.replace('title: Trip\n', 'title: Trip\nextra: 1\n'),
    canonical.replace('title: Trip\n', ''),
  ])('rejects invalid canonical document %#', (document) => {
    expect(() => parseRuleDocument(document)).toThrow();
  });
});

// contract-test: supporting surface=rest_api assertions=app-memories.expiry.client-enforced
describe('Memory expiry window', () => {
  const window = { valid_from: '2026-01-01T00:00:00Z', valid_until: '2026-02-01T00:00:00Z' };
  it('is active only inside the window', () => {
    expect(isMemoryActive(window, new Date('2025-12-31T23:59:59Z'))).toBe(false);
    expect(isMemoryActive(window, new Date('2026-01-15T00:00:00Z'))).toBe(true);
    expect(isMemoryActive(window, new Date('2026-02-01T00:00:01Z'))).toBe(false);
    expect(isMemoryActive({}, new Date())).toBe(true);
  });
  // contract-test: supporting surface=gui.web assertions=app-memories.expiry.client-enforced
  it('is deletable only after the grace period', () => {
    expect(isMemoryExpiredBeyondGrace(window, new Date('2026-02-07T00:00:00Z'))).toBe(false);
    expect(isMemoryExpiredBeyondGrace(window, new Date('2026-02-09T00:00:00Z'))).toBe(true);
    expect(isMemoryExpiredBeyondGrace({}, new Date('2030-01-01'))).toBe(false);
  });
});

describe('encrypted Project document patch', () => {
  // contract-test: supporting surface=gui.web assertions=rules.ownership.encrypted-custom,projects.files.exact-patch
  it.each([
    ['first\n', 'second\n'], ['first', 'second'], ['first', 'second\n'],
    ['first\n', 'second'], ['first\n\n', 'second\n\n'], ['', 'second\n'],
  ])('preserves exact final-newline semantics %#', (original, updated) => {
    const path = '.openmates/rules/guide.md';
    const patch = buildWholeDocumentPatch(original, updated, path);
    expect(applyProjectFilePatch(original, patch, path).content).toBe(updated);
  });
});
