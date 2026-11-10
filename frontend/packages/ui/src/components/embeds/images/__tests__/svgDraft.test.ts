import { describe, expect, it } from 'vitest';
import { childDraftContent, mergeSvgDraft, readSvgDraft, shouldShowSvgDraft, svgDraftStageLabelKey } from '../svgDraft';

describe('svgDraft helpers', () => {
  // contract-test: supporting surface=gui.web assertions=images-generate.vector.progressive-drafts
  it('reads draft, stage and attempt from decoded content', () => {
    expect(readSvgDraft({ svg_draft: '<svg>', draft_stage: 'checking', draft_attempt: 2 })).toEqual({
      draft: '<svg>',
      stage: 'checking',
      attempt: 2
    });
    expect(readSvgDraft({ svg_draft: 5, draft_stage: 'bogus' })).toEqual({
      draft: '',
      stage: undefined,
      attempt: undefined
    });
    expect(readSvgDraft(null).draft).toBe('');
  });

  // contract-test: supporting surface=gui.web assertions=images-generate.vector.progressive-drafts
  it('shows the drawing only while processing with non-empty source', () => {
    expect(shouldShowSvgDraft('processing', '<svg')).toBe(true);
    expect(shouldShowSvgDraft('processing', '  ')).toBe(false);
    expect(shouldShowSvgDraft('finished', '<svg></svg>')).toBe(false);
    expect(shouldShowSvgDraft('error', '<svg></svg>')).toBe(false);
  });

  // contract-test: supporting surface=gui.web assertions=images-generate.vector.progressive-drafts
  it('labels only the checking and correcting stages', () => {
    expect(svgDraftStageLabelKey('drawing')).toBeNull();
    expect(svgDraftStageLabelKey(undefined)).toBeNull();
    expect(svgDraftStageLabelKey('checking')).toBe('embeds.image_generate.checking');
    expect(svgDraftStageLabelKey('correcting')).toBe('embeds.image_generate.correcting');
  });

  // contract-test: supporting surface=gui.web assertions=images-generate.vector.progressive-drafts
  it('supports the scripting stage and merges stage-only updates', () => {
    expect(svgDraftStageLabelKey('scripting')).toBe('embeds.image_generate.scripting');
    expect(readSvgDraft({ svg_draft: '', draft_stage: 'scripting' }).stage).toBe('scripting');
    const prev = { draft: '<svg>', stage: 'drawing' as const, attempt: 1 };
    expect(mergeSvgDraft(prev, { draft: '', stage: 'checking', attempt: undefined })).toEqual({
      draft: '<svg>',
      stage: 'checking',
      attempt: 1
    });
    expect(mergeSvgDraft(prev, { draft: '', stage: 'scripting', attempt: 2 })).toEqual({
      draft: '',
      stage: 'scripting',
      attempt: 2
    });
    expect(mergeSvgDraft(prev, { draft: '', stage: undefined, attempt: undefined })).toBe(prev);
    expect(mergeSvgDraft(prev, { draft: '<svg><g/>', stage: 'drawing', attempt: 1 }).draft).toBe('<svg><g/>');
  });

  // contract-test: supporting surface=gui.web assertions=images-generate.vector.progressive-drafts
  it('accepts a processing draft of a child image embed for the parent card only', () => {
    const detail = { embed_id: 'child', parent_embed_id: 'card', status: 'processing', content: 'svg_draft: x' };
    expect(childDraftContent(detail, 'card')).toBe('svg_draft: x');
    expect(childDraftContent(detail, 'other-card')).toBeNull();
    expect(childDraftContent({ ...detail, status: 'finished' }, 'card')).toBeNull();
    expect(childDraftContent({ ...detail, content: '' }, 'card')).toBeNull();
    expect(childDraftContent({ ...detail, embed_id: 'card' }, 'card')).toBeNull();
  });
});
