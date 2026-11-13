import { describe, expect, it } from 'vitest';
import {
  EMPTY_EDITS, buildEditRequestText, buildExtendRequestText, canRemovePart, canShorten, countEdits,
  normalizeTimeline, resultingDurationFrames, synthesizeTimeline, toggleRemoved, withText, withTrimStep,
  type Translate,
} from '../videos/videoTimelineModel';

const EN: Record<string, string> = {
  'embeds.video_generate.request_change_text': 'Part {label} (id {id}): change text {text} from {from} to {to}',
  'embeds.video_generate.request_shorten_start': 'Part {label} (id {id}): shorten by {seconds} s at the start',
  'embeds.video_generate.request_shorten_end': 'Part {label} (id {id}): shorten by {seconds} s at the end',
  'embeds.video_generate.request_remove_part': 'Remove part {label} (id {id})',
  'embeds.video_generate.request_trim_video': 'Trim the video: remove {start} s from the start and {end} s from the end',
  'embeds.video_generate.request_trim_video_start': 'Trim the video: remove {start} s from the start',
  'embeds.video_generate.request_trim_video_end': 'Trim the video: remove {end} s from the end',
};
const t: Translate = (key, values = {}) => (EN[key] ?? key).replace(/\{(\w+)\}/g, (_, k) => String(values[k]));

const content = {
  made_by: 'composed',
  timeline: {
    fps: 30, duration_in_frames: 300, width: 1280, height: 720,
    tracks: [{ id: 'main', name: 'Video', kind: 'visual', parts: [
      { id: 'scene-2', label: 'Budget vote', from: 150, duration_in_frames: 150, kind: 'scene', texts: [{ id: 'headline', value: 'Old' }] },
      { id: 'scene-1', label: 'Opening', from: 0, duration_in_frames: 150, kind: 'scene', texts: [] },
    ] }],
  },
};

describe('normalizeTimeline', () => {
  // contract-test: direct surface=gui.web assertions=videos-generate.timeline.below-the-video
  it('sorts parts in time order and keeps made_by', () => {
    const tl = normalizeTimeline(content)!;
    expect(tl.madeBy).toBe('composed');
    expect(tl.tracks[0].parts.map((p) => p.id)).toEqual(['scene-1', 'scene-2']);
  });
  // contract-test: direct surface=gui.web assertions=videos-generate.timeline.below-the-video
  it('returns undefined without a timeline and synthesizes a one-clip fallback', () => {
    expect(normalizeTimeline({})).toBeUndefined();
    const tl = synthesizeTimeline(8, 'Clip');
    expect(tl.durationInFrames).toBe(240);
    expect(tl.tracks[0].parts).toHaveLength(1);
    expect(tl.madeBy).toBe('generative');
  });
});

describe('edits', () => {
  const tl = normalizeTimeline(content)!;
  // contract-test: direct surface=gui.web assertions=videos-generate.change.edit-mode
  it('counts, resizes and builds one request', () => {
    let e = withText(EMPTY_EDITS, tl, 'scene-2', 'headline', 'New');
    e = withTrimStep(e, tl, 'scene-1', 'end', 2);
    expect(countEdits(e)).toBe(2);
    expect(resultingDurationFrames(tl, e)).toBe(270);
    expect(buildEditRequestText(e, tl, t)).toBe([
      'Apply these edits to this video:',
      '- Part "Budget vote" (id scene-2): change text "headline" from "Old" to "New"',
      '- Part "Opening" (id scene-1): shorten by 1.0 s at the end',
    ].join('\n'));
  });
  // contract-test: direct surface=gui.web assertions=videos-generate.change.edit-mode
  it('restoring the original text drops the edit', () => {
    const e = withText(withText(EMPTY_EDITS, tl, 'scene-2', 'headline', 'New'), tl, 'scene-2', 'headline', 'Old');
    expect(countEdits(e)).toBe(0);
  });
  // contract-test: direct surface=gui.web assertions=videos-generate.change.edit-mode
  it('never shortens below half a second', () => {
    let e = EMPTY_EDITS;
    for (let i = 0; i < 20; i++) e = withTrimStep(e, tl, 'scene-1', 'start', 1);
    expect(e.trims[0].fromStartFrames).toBe(135);
    expect(canShorten(e, tl, 'scene-1', 'end')).toBe(false);
  });
  // contract-test: direct surface=gui.web assertions=videos-generate.change.edit-mode
  it('does not remove the last remaining part', () => {
    const e = toggleRemoved(EMPTY_EDITS, tl, 'scene-1');
    expect(e.removed).toEqual(['scene-1']);
    expect(canRemovePart(e, tl, 'scene-2')).toBe(false);
    expect(toggleRemoved(e, tl, 'scene-2')).toBe(e);
    expect(resultingDurationFrames(tl, e)).toBe(150);
    expect(buildEditRequestText(e, tl, t)).toContain('- Remove part "Opening" (id scene-1)');
  });
  // contract-test: direct surface=gui.web assertions=videos-generate.change.edit-mode
  it('words a generative trim of the whole clip', () => {
    const gen = synthesizeTimeline(8, 'Clip');
    let e = withTrimStep(EMPTY_EDITS, gen, 'clip-1', 'start', 1);
    e = withTrimStep(e, gen, 'clip-1', 'end', 2);
    expect(buildEditRequestText(e, gen, t)).toBe('Apply these edits to this video:\n- Trim the video: remove 0.5 s from the start and 1.0 s from the end');
    expect(canRemovePart(EMPTY_EDITS, gen, 'clip-1')).toBe(false);
  });
});

describe('extend text', () => {
  // contract-test: direct surface=gui.web assertions=videos-generate.change.extend-generated-clip
  it('starts with the exact marker', () => {
    expect(buildExtendRequestText('end', ' waves roll in ')).toBe('Extend this video at the end: waves roll in');
    expect(buildExtendRequestText('start', 'dawn')).toBe('Extend this video at the start: dawn');
  });
});
