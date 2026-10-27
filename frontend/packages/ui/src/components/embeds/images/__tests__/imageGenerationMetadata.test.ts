/**
 * Checks generated image attribution and stable asset naming.
 * Covers actual serving providers and historical indexed filenames.
 * Ensures original asset formats determine the filename extension.
 * This unit coverage uses no provider calls or encrypted storage access.
 */
import { describe, expect, it } from 'vitest';
import { imageGenerationAttribution, imageGenerationFilename } from '../imageGenerationMetadata';
describe('generated image metadata', () => {
  // contract-test: supporting surface=gui.web assertions=app-skills.media.visible-assistant-results,app-skills.media.parent-children-and-attribution
  it('keeps the actual serving provider even when the model has another owner', () => {
    expect(imageGenerationAttribution('unregistered-model', 'fal.ai')).toBe('unregistered-model · fal.ai');
    expect(imageGenerationAttribution('recraftv4_1_vector')).toMatch(/Recraft/);
  });
  // contract-test: supporting surface=gui.web assertions=app-skills.media.visible-assistant-results,app-skills.media.parent-children-and-attribution
  it('uses the saved filename and matches historical original asset names', () => {
    expect(imageGenerationFilename({ filename: 'minimalist_icon.svg' }, 'unused')).toBe('minimalist_icon.svg');
    expect(imageGenerationFilename({ output_filetype: 'svg' }, '22222222-2222-4222-8222-222222222222')).toBe('openmates_generated_image_22222222.svg');
    expect(imageGenerationFilename({ output_filetype: 'png', files: { original: { format: 'svg' } } }, '22222222')).toBe('openmates_generated_image_22222222.svg');
  });
});
