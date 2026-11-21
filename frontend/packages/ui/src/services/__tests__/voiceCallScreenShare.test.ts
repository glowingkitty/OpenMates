import { describe, expect, it } from 'vitest';
import { isScreenShareSupported } from '../voiceCallScreenShare';

const media = (queries: Record<string, boolean>) => (query: string) => ({ matches: queries[query] === true });
const display = { getDisplayMedia: () => Promise.resolve(null) };

describe('isScreenShareSupported', () => {
  // contract-test: supporting surface=gui.web assertions=video-call.video.web-screen-share
  it('is offered on a desktop browser with display capture', () => {
    expect(isScreenShareSupported({ mediaDevices: display, matchMedia: media({ '(pointer: fine)': true, '(hover: hover)': true }) })).toBe(true);
  });
  // contract-test: supporting surface=gui.web assertions=video-call.video.web-screen-share
  it('is hidden where getDisplayMedia is absent (iOS, iPadOS, Android)', () => {
    expect(isScreenShareSupported({ mediaDevices: {}, matchMedia: media({ '(pointer: coarse)': true, '(hover: none)': true }) })).toBe(false);
    expect(isScreenShareSupported({ mediaDevices: null, matchMedia: media({}) })).toBe(false);
  });
  // contract-test: supporting surface=gui.web assertions=video-call.video.web-screen-share
  it('is hidden on a touch-only device even if it exposes getDisplayMedia', () => {
    expect(isScreenShareSupported({ mediaDevices: display, matchMedia: media({ '(pointer: coarse)': true, '(hover: none)': true }) })).toBe(false);
  });
  // contract-test: supporting surface=gui.web assertions=video-call.video.web-screen-share
  it('stays on a touch laptop whose primary pointer hovers', () => {
    expect(isScreenShareSupported({ mediaDevices: display, matchMedia: media({ '(pointer: coarse)': true, '(hover: hover)': true }) })).toBe(true);
  });
});
