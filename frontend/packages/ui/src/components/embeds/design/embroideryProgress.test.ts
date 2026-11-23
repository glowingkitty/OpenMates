// Unit tests of the design.embroidery card helpers (TASK-1610).
import { describe, expect, it } from 'vitest';
import { embroideryStageLabelKey, readEmbroideryStage } from './embroideryProgress';
import { generatedMediaSkillIcon } from '../generatedMediaGroup';

describe('design.embroidery card', () => {
  // contract-test: supporting surface=gui.web assertions=design-embroidery.progress.input-and-stages
  it('uses the needle icon; other generation skills keep the AI sparkle', () => {
    expect(generatedMediaSkillIcon('design', 'embroidery')).toBe('embroidery');
    expect(generatedMediaSkillIcon('images', 'generate')).toBe('ai');
    expect(generatedMediaSkillIcon('web', 'search')).toBe('web');
  });

  // contract-test: supporting surface=gui.web assertions=design-embroidery.progress.input-and-stages
  it('reads known stages only and keeps the last one otherwise', () => {
    expect(readEmbroideryStage({ progress_stage: 'stitching' })).toBe('stitching');
    expect(readEmbroideryStage({ progress_stage: 'bogus' }, 'checking')).toBe('checking');
    expect(readEmbroideryStage({}, 'saving')).toBe('saving');
    expect(embroideryStageLabelKey('reading')).toBe('embeds.design.embroidery.progress_reading');
    expect(embroideryStageLabelKey(undefined)).toBeUndefined();
  });
});
