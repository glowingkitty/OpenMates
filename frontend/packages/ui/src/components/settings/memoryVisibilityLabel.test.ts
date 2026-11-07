import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

const read = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8');

describe('Public memory card label', () => {
  // contract-test: supporting surface=gui.web assertions=app-memories.discovery.visibility-cards
  it('marks app-provided Memory cards public and renders the localized label on every memory card', () => {
    expect(read('./SettingsMemoriesHub.svelte')).toContain("memoryVisibility={entry.published ? 'public' : 'private'}");
    const card = read('./AppStoreCard.svelte');
    expect(card).toContain('data-testid="memory-card-visibility"');
    expect(card).toContain('$text(`memories.visibility_${memoryVisibility}`)');
  });

  // contract-test: supporting surface=gui.web assertions=app-memories.discovery.visibility-cards
  it('provides English and German text for the Public label source key', () => {
    const source = read('../../i18n/sources/memories.yml');
    const block = source.slice(source.indexOf('visibility_public:'), source.indexOf('visibility_private:'));
    expect(block).toMatch(/en: Public\n/);
    expect(block).toMatch(/de: Öffentlich\n/);
  });
});
