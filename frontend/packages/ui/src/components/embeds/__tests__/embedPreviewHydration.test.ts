// frontend/packages/ui/src/components/embeds/__tests__/embedPreviewHydration.test.ts
// Unit coverage for bounded embed preview hydration decisions.
// Large chat tests use synthetic carousel/child-id data only; these assertions
// must never trigger embed decryption, provider calls, or AI inference.
// Architecture: docs/specs/scalable-chat-embed-loading/spec.yml

import { describe, expect, it } from 'vitest';
import {
  limitLegacyPreviewChildIds,
  shouldHydrateCarouselSlide,
} from '../embedPreviewHydration';

describe('embed preview hydration bounds', () => {
  it('hydrates only active and adjacent carousel slides by default', () => {
    const hydrated = Array.from({ length: 20 }, (_, index) => index).filter((index) =>
      shouldHydrateCarouselSlide(8, index, 20),
    );

    expect(hydrated).toEqual([7, 8, 9]);
  });

  it('wraps carousel hydration at the run boundary', () => {
    const hydrated = Array.from({ length: 5 }, (_, index) => index).filter((index) =>
      shouldHydrateCarouselSlide(0, index, 5),
    );

    expect(hydrated).toEqual([0, 1, 4]);
  });

  it('caps legacy child embed preview hydration', () => {
    const childIds = ['child-1', '', 'child-2', 'child-3', 'child-4'];

    expect(limitLegacyPreviewChildIds(childIds, 3)).toEqual(['child-1', 'child-2', 'child-3']);
  });
});
