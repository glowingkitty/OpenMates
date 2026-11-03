// Unit checks for the composer interaction focus hold used by PII highlight,
// PII banner and suggestion-rail taps.
import { describe, expect, it } from 'vitest';
import { createComposerInteractionFocusHold } from '../composerInteractionFocusHold';

describe('createComposerInteractionFocusHold', () => {
  // contract-test: supporting surface=gui.web assertions=pii.composer.detect-redact-exclude
  it('is inactive until started and expires after the hold duration', () => {
    let now = 1_000;
    const hold = createComposerInteractionFocusHold(800, () => now);
    expect(hold.isHeld()).toBe(false);
    hold.start();
    expect(hold.isHeld()).toBe(true);
    now += 799;
    expect(hold.isHeld()).toBe(true);
    now += 1;
    expect(hold.isHeld()).toBe(false);
  });

  // contract-test: supporting surface=gui.web assertions=pii.composer.detect-redact-exclude
  it('extends the hold when restarted', () => {
    let now = 0;
    const hold = createComposerInteractionFocusHold(800, () => now);
    hold.start();
    now = 600;
    hold.start();
    now = 1_300;
    expect(hold.isHeld()).toBe(true);
    now = 1_400;
    expect(hold.isHeld()).toBe(false);
  });
});
