// frontend/packages/ui/src/components/embeds/slides/slidesPresentation.test.ts
import { describe, expect, it } from 'vitest';
import { actionForKey, formatElapsed, isPresentMessage, lastPosition, nextPosition, previousPosition } from './slidesPresentation';
import { parseSlidesMarkup } from './slidesMarkup';
import { sampleDeck } from './slidesPreviewFixture';

const parsed = parseSlidesMarkup(sampleDeck());
const slides = parsed.ok ? parsed.deck.slides : [];

describe('presentation position', () => {
  // contract-test: supporting surface=gui.web assertions=slides.present.presenter-view
  it('advances build steps before the slide', () => {
    expect(nextPosition(slides, { index: 2, step: 0 })).toEqual({ index: 2, step: 1 });
    expect(nextPosition(slides, { index: 2, step: 1 })).toEqual({ index: 3, step: 0 });
  });
  // contract-test: supporting surface=gui.web assertions=slides.present.presenter-view
  it('stops at the ends and goes back through build steps', () => {
    expect(nextPosition(slides, lastPosition(slides))).toEqual(lastPosition(slides));
    expect(previousPosition(slides, { index: 3, step: 0 })).toEqual({ index: 2, step: 1 });
    expect(previousPosition(slides, { index: 0, step: 0 })).toEqual({ index: 0, step: 0 });
  });
  // contract-test: supporting surface=gui.web assertions=slides.present.presenter-view
  it('maps keys and validates messages', () => {
    expect(actionForKey(' ')).toBe('next');
    expect(actionForKey('PageUp')).toBe('previous');
    expect(actionForKey('x')).toBeNull();
    expect(isPresentMessage({ type: 'goto', index: 1, step: 0 })).toBe(true);
    expect(isPresentMessage({ type: 'deck', index: 1, step: 0 })).toBe(false);
    expect(isPresentMessage('x')).toBe(false);
  });
  // contract-test: supporting surface=gui.web assertions=slides.present.presenter-view
  it('formats the timer', () => {
    expect(formatElapsed(65)).toBe('01:05');
    expect(formatElapsed(3725)).toBe('1:02:05');
  });
});
