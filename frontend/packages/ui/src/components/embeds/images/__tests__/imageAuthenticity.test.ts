// frontend/packages/ui/src/components/embeds/images/__tests__/imageAuthenticity.test.ts
// Unit coverage for uploaded-image AI detection badge decisions.
// Keeps the UI contract testable without mounting Svelte components in Vitest.
// Covers authentic, AI-generated, uncertain, and provider-failure states.
// Source docs: https://sightengine.com/docs/ai-generated-image-detection

import { describe, expect, it } from 'vitest';
import {
  SIGHTENGINE_URL,
  buildAuthenticityBadgeViewModel,
  formatAIGeneratedPercentage,
  getImageAuthenticityStatus,
} from '../imageAuthenticity';

const TRANSLATIONS: Record<string, string> = {
  'app_skills.images.view.ai_generated': 'AI generated',
  'app_skills.images.view.authentic': 'Authentic',
  'app_skills.images.view.ai_generated_chance': "{percentage} chance it's AI generated",
  'app_skills.images.view.via_provider': 'via {provider}',
  'app_skills.images.view.detection_limitations':
    'Pixel-based detection is useful for photos and art, including many compressed or re-shared images. It is not definitive; heavy degradation, UI-heavy screenshots, screen or print recaptures, and new generators may need human judgment.',
  'app_skills.images.view.detection_failed_title': 'AI detection unavailable',
  'app_skills.images.view.detection_failed_retry': 'AI detection failed temporarily. Try again later.',
  'app_skills.images.view.detection_failed_description':
    'The image upload succeeded, but Sightengine did not return a usable AI-detection score for this attempt.',
};

function translate(key: string, vars: Record<string, unknown> = {}): string {
  let value = TRANSLATIONS[key] ?? key;
  for (const [name, replacement] of Object.entries(vars)) {
    value = value.replace(`{${name}}`, String(replacement));
  }
  return value;
}

describe('image authenticity badge helpers', () => {
  it('classifies high scores as AI-generated and low scores as authentic', () => {
    expect(getImageAuthenticityStatus({ ai_generated: 0.98, provider: 'sightengine' })).toBe(
      'ai_generated',
    );
    expect(getImageAuthenticityStatus({ ai_generated: 0, provider: 'sightengine' })).toBe(
      'authentic',
    );
  });

  it('does not badge uncertain middle scores', () => {
    expect(getImageAuthenticityStatus({ ai_generated: 0.55, provider: 'sightengine' })).toBeNull();
  });

  it('formats bounded probability labels', () => {
    expect(formatAIGeneratedPercentage(0.984)).toBe('98%');
    expect(formatAIGeneratedPercentage(-0.4)).toBe('0%');
    expect(formatAIGeneratedPercentage(2)).toBe('100%');
  });

  it('builds an authentic Sightengine view model with source link and limitation copy', () => {
    const viewModel = buildAuthenticityBadgeViewModel(
      { ai_generated: 0.001, provider: 'sightengine' },
      translate,
    );

    expect(viewModel).toMatchObject({
      status: 'authentic',
      probabilityLabel: "0% chance it's AI generated",
      providerLabel: 'Sightengine',
      providerUrl: SIGHTENGINE_URL,
    });
    expect(viewModel?.ariaLabel).toContain('via Sightengine');
    expect(viewModel?.explanationLabel).toContain('human judgment');
  });

  it('builds a temporary-failure view model instead of treating failure as authentic', () => {
    const viewModel = buildAuthenticityBadgeViewModel(
      { ai_generated: 0, provider: 'sightengine', status: 'failed', error: 'timeout' },
      translate,
    );

    expect(viewModel).toMatchObject({
      status: 'failed',
      probabilityLabel: 'AI detection failed temporarily. Try again later.',
      providerLabel: 'Sightengine',
      providerUrl: SIGHTENGINE_URL,
    });
    expect(viewModel?.ariaLabel).toContain('AI detection unavailable');
    expect(viewModel?.explanationLabel).toContain('did not return a usable AI-detection score');
  });
});
