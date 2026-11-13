import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { PIIMatch } from '../piiDetectionService';

const detector = vi.hoisted(() => ({ detectPIIForWeb: vi.fn() }));
vi.mock('../webPIIDetectionService', () => ({
  createWebPIIDocumentScanContext: () => ({ purpose: 'document' }),
  detectPIIForWeb: detector.detectPIIForWeb,
}));
vi.mock('../../../../stores/personalDataStore', async () => {
  const { readable } = await import('svelte/store');
  return { personalDataStore: {
    settings: readable({ masterEnabled: true, enhancedEnabled: true, categories: {} }),
    enabledEntries: readable([]),
  } };
});
vi.mock('../../../../services/embedStore', () => ({ embedStore: { put: vi.fn(), get: vi.fn() } }));

import { redactEmbedContent } from '../codeEmbedService';

const person = (match: string, startIndex: number): PIIMatch =>
  ({ id: `id-${startIndex}`, type: 'PERSON_NAME', match, startIndex, endIndex: startIndex + match.length, placeholder: '[PERSON_NAME_1]' }) as PIIMatch;

describe('embed content redaction', () => {
  beforeEach(() => detector.detectPIIForWeb.mockReset());

  // contract-test: supporting surface=gui.web assertions=pii.composer.detect-redact-exclude,pii.web.local-bounded-inference
  it('replaces model-detected names in pasted documents using the shared document scan context', async () => {
    const text = 'Notes from the call with Herr Neumann about the delayed audit report.';
    detector.detectPIIForWeb.mockResolvedValue([person('Neumann', text.indexOf('Neumann'))]);
    const context = { purpose: 'document' as const };
    const { redactedContent, piiMappings } = await redactEmbedContent(text, context);
    expect(redactedContent).toBe('Notes from the call with Herr [PERSON_NAME_1] about the delayed audit report.');
    expect(piiMappings.map(mapping => mapping.original)).toEqual(['Neumann']);
    expect(detector.detectPIIForWeb).toHaveBeenCalledWith(text, expect.anything(), context);
  });

  // contract-test: supporting surface=gui.web assertions=pii.composer.detect-redact-exclude
  it('leaves text without matches untouched', async () => {
    detector.detectPIIForWeb.mockResolvedValue([]);
    await expect(redactEmbedContent('Nothing sensitive in this sentence.')).resolves.toEqual({
      redactedContent: 'Nothing sensitive in this sentence.', piiMappings: [],
    });
  });
});
