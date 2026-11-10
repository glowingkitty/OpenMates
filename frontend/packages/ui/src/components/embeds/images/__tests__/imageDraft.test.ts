import { describe, expect, it } from 'vitest';
import {
  EMPTY_IMAGE_MODIFY, imageDraftUrl, imageModifyStageKey, mergeImageModify, readImageModify, readUnmetRequirements, showsAttempt,
} from '../imageDraft';

describe('imageDraft helpers', () => {
  // contract-test: supporting surface=gui.web assertions=images-modify.progress.shown-while-running
  it('reads stage, attempt and a valid draft', () => {
    expect(readImageModify({ draft_stage: 'checking', draft_attempt: 2, image_draft: 'QUJD' })).toEqual({ stage: 'checking', attempt: 2, draft: 'QUJD' });
    expect(readImageModify({ draft_stage: 'bogus', draft_attempt: 0, image_draft: 'not base64!' })).toEqual(EMPTY_IMAGE_MODIFY);
  });

  // contract-test: supporting surface=gui.web assertions=images-modify.progress.shown-while-running
  it('builds a data URL only from valid base64', () => {
    expect(imageDraftUrl('QUJD')).toBe('data:image/jpeg;base64,QUJD');
    expect(imageDraftUrl('QUJ')).toBeNull();
    expect(imageDraftUrl('<script>')).toBeNull();
    expect(imageDraftUrl('')).toBeNull();
  });

  // contract-test: supporting surface=gui.web assertions=images-modify.progress.shown-while-running
  it('keeps the picture on stage-only updates and drops it when writing restarts', () => {
    const shown = { stage: 'checking' as const, attempt: 1, draft: 'QUJD' };
    expect(mergeImageModify(shown, { stage: 'correcting', attempt: 2, draft: '' }).draft).toBe('QUJD');
    expect(mergeImageModify(shown, { stage: 'writing', attempt: 2, draft: '' }).draft).toBe('');
    expect(mergeImageModify(shown, EMPTY_IMAGE_MODIFY)).toBe(shown);
  });

  // contract-test: supporting surface=gui.web assertions=images-modify.progress.shown-while-running
  it('maps stages to keys and shows the attempt from the second on', () => {
    expect(imageModifyStageKey('running')).toBe('embeds.image_modify.running');
    expect(imageModifyStageKey(undefined)).toBeNull();
    expect(showsAttempt(1)).toBe(false);
    expect(showsAttempt(2)).toBe(true);
  });

  // contract-test: supporting surface=gui.web assertions=images-modify.result.normal-image
  it('lists unmet requirements only for unmet_delivered', () => {
    expect(readUnmetRequirements({ review_status: 'unmet_delivered', unmet_requirements: ['a', ' ', 'b'] })).toEqual(['a', 'b']);
    expect(readUnmetRequirements({ review_status: 'accepted', unmet_requirements: ['a'] })).toEqual([]);
  });
});
