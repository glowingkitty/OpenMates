import { describe, expect, it } from 'vitest';
import { readSvgDraft, shouldShowSvgDraft, svgDraftStageLabelKey } from '../svgDraft';

describe('svgDraft helpers', () => {
  // contract-test: supporting surface=gui.web assertions=interactive-html.render.vector-image-and-progressive-streaming
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

  // contract-test: supporting surface=gui.web assertions=interactive-html.render.vector-image-and-progressive-streaming
  it('shows the drawing only while processing with non-empty source', () => {
    expect(shouldShowSvgDraft('processing', '<svg')).toBe(true);
    expect(shouldShowSvgDraft('processing', '  ')).toBe(false);
    expect(shouldShowSvgDraft('finished', '<svg></svg>')).toBe(false);
    expect(shouldShowSvgDraft('error', '<svg></svg>')).toBe(false);
  });

  // contract-test: supporting surface=gui.web assertions=interactive-html.render.vector-image-and-progressive-streaming
  it('labels only the checking and correcting stages', () => {
    expect(svgDraftStageLabelKey('drawing')).toBeNull();
    expect(svgDraftStageLabelKey(undefined)).toBeNull();
    expect(svgDraftStageLabelKey('checking')).toBe('embeds.image_generate.checking');
    expect(svgDraftStageLabelKey('correcting')).toBe('embeds.image_generate.correcting');
  });
});
