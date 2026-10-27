import { describe, expect, it } from 'vitest';
import { resolveFocusInstructions } from './focusModeInstructions';
import type { FocusModeMetadata } from '../../types/apps';

const focus: FocusModeMetadata = {
  id: 'sample', name_translation_key: 'sample.name', description_translation_key: 'sample.description',
  system_prompt: 'Canonical English instructions.', system_prompt_translation_key: 'focus_modes.sample.systemprompt',
  process: ['Canonical process.'], process_translation_key: 'focus_modes.sample.process',
};

// contract-test: supporting surface=gui.web assertions=settings-ui.localization.visible-content-resolves,focus-modes.controls
describe('focus instructions', () => {
  // contract-test: supporting surface=gui.web assertions=settings-ui.localization.visible-content-resolves,focus-modes.controls
  it('shows the selected language before the canonical English fallback', () => {
    const value = resolveFocusInstructions(focus, key => key.endsWith('.systemprompt') ? 'Verwende die vorhandenen Angaben.' : '- Prüfe die Angaben.');
    expect(value.systemPrompt).toBe('Verwende die vorhandenen Angaben.');
    expect(value.processBullets).toEqual(['Prüfe die Angaben.']);
    expect(value.hasInstructions).toBe(true);
  });
  // contract-test: supporting surface=gui.web assertions=settings-ui.localization.visible-content-resolves,focus-modes.controls
  it('parses translated multiline process bullets while preserving authored fallback', () => {
    const translated = resolveFocusInstructions(focus, key => key.endsWith('.process')
      ? '- Prüfe die Angaben.\n\n  * Erstelle den Entwurf.\r\n-\tBesprich die nächsten Schritte.'
      : '[T:missing.prompt]');
    expect(translated.processBullets).toEqual([
      'Prüfe die Angaben.', 'Erstelle den Entwurf.', 'Besprich die nächsten Schritte.',
    ]);
    expect(translated.systemPrompt).toBe('Canonical English instructions.');
    const fallback = resolveFocusInstructions(focus, key => `[T:${key}]`);
    expect(fallback.processBullets).toEqual(['Canonical process.']);
  });
  // contract-test: supporting surface=gui.web assertions=settings-ui.localization.visible-content-resolves,focus-modes.controls
  it.each(['[T:focus_modes.sample.systemprompt]', 'focus_modes.sample.systemprompt', 'focus_modes.sample.systemprompt.text', ''])('uses real authored fallback when translation is missing: %s', missing => {
    const value = resolveFocusInstructions(focus, () => missing);
    expect(value.systemPrompt).toBe('Canonical English instructions.');
  });
  // contract-test: supporting surface=gui.web assertions=settings-ui.localization.visible-content-resolves,focus-modes.controls
  it('never treats a placeholder from persisted metadata as instructions', () => {
    const value = resolveFocusInstructions({ ...focus, system_prompt: '[T:old.prompt]', process: ['[T:old.process]'] }, key => `[T:${key}]`);
    expect(value).toEqual({ systemPrompt: '', processBullets: [], hasInstructions: false });
  });
  // contract-test: supporting surface=gui.web assertions=settings-ui.localization.visible-content-resolves,focus-modes.controls
  it('retains valid canonical process bullets without inventing a system prompt', () => {
    const value = resolveFocusInstructions({ ...focus, system_prompt: undefined, system_prompt_translation_key: undefined }, key => `[T:${key}]`);
    expect(value.systemPrompt).toBe('');
    expect(value.processBullets).toEqual(['Canonical process.']);
  });
  // contract-test: supporting surface=gui.web assertions=settings-ui.localization.visible-content-resolves,focus-modes.controls
  it('represents genuinely empty modes with the no-instructions state', () => {
    expect(resolveFocusInstructions(undefined, key => `[T:${key}]`).hasInstructions).toBe(false);
  });
});
