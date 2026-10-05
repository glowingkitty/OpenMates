import { describe, expect, it } from 'vitest';
import { buildWholeDocumentPatch, parseRuleDocument, serializeRuleDocument, validateRuleCatalog } from '../ruleDocuments';
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
