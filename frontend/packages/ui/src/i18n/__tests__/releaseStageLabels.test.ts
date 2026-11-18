// frontend/packages/ui/src/i18n/__tests__/releaseStageLabels.test.ts
//
// Guard: OpenMates does not call itself "alpha" or "beta" anywhere users read it,
// and no text claims the project is closed source. Version numbers, the npm
// prerelease tag and internal identifiers are not user-facing text and are not
// checked here. The Apple app's TestFlight newsletter category is the one
// product decision that keeps the word "beta" (the Apple app really is in
// TestFlight testing).

import { describe, expect, it } from 'vitest';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { parse } from 'yaml';

// Vitest runs from the ui package directory (same convention as the legal copy tests).
const SOURCES_DIR = resolve(process.cwd(), 'src/i18n/sources');
const README = resolve(process.cwd(), '../../../README.md');

// Example chats contain unrelated user content (Greek letters, sample data).
const SKIPPED_SOURCE_DIRS = new Set(['example_chats']);
// Keys that deliberately keep the word: the Apple TestFlight newsletter category.
const ALLOWED_KEY = /(^|\.)(apple_beta|newsletter_public_apple_beta)|apple_beta_updates/;

const STAGE_LABEL = new RegExp(
  [
    '\\balpha\\b', '\\bbeta\\b', '\\balfa\\b', '\\bb[êé]ta\\b',
    'альфа', 'бета', 'アルファ', 'ベータ', '알파', '베타', '测试版', '内测', '公测',
    'אלפא', 'בטא', 'ألفا', 'بيتا', 'अल्फा', 'बीटा', 'อัลฟา', 'เบต้า',
  ].join('|'),
  'i',
);
const CLOSED_SOURCE = /closed[- ]?source|código cerrado|code source fermé|クローズドソース|闭源|封闭源/i;

function ymlFiles(dir: string): string[] {
  const files: string[] = [];
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) {
      if (!SKIPPED_SOURCE_DIRS.has(name)) files.push(...ymlFiles(path));
    } else if (name.endsWith('.yml')) {
      files.push(path);
    }
  }
  return files;
}

type Entry = { file: string; key: string; lang: string; text: string };

let cachedEntries: Entry[] | null = null;

function entries(): Entry[] {
  if (cachedEntries) return cachedEntries;
  const found: Entry[] = [];
  for (const file of ymlFiles(SOURCES_DIR)) {
    const doc = parse(readFileSync(file, 'utf8')) as Record<string, unknown> | null;
    for (const [key, value] of Object.entries(doc ?? {})) {
      if (!value || typeof value !== 'object') continue;
      for (const [lang, text] of Object.entries(value as Record<string, unknown>)) {
        if (lang === 'context' || lang === 'verified_by_human' || typeof text !== 'string') continue;
        found.push({ file: file.slice(SOURCES_DIR.length + 1), key, lang, text });
      }
    }
  }
  cachedEntries = found;
  return found;
}

// Parsing every YAML source takes a few seconds on the first call.
const PARSE_TIMEOUT_MS = 60_000;

describe('release stage labels', () => {
  // contract-test: supporting surface=gui.web assertions=auth.signup.current-flow
  it('keeps alpha and beta out of every user-facing translation, in every language', () => {
    const offenders = entries()
      .filter(({ key }) => !ALLOWED_KEY.test(key))
      .filter(({ text }) => STAGE_LABEL.test(text))
      .map(({ file, key, lang }) => `${file}:${key}:${lang}`);

    expect(offenders).toEqual([]);
  }, PARSE_TIMEOUT_MS);

  // contract-test: supporting surface=gui.web assertions=auth.signup.current-flow
  it('never says OpenMates is closed source, and the Terms about text is the open-source text in every language', () => {
    const closed = entries()
      .filter(({ text }) => CLOSED_SOURCE.test(text))
      .map(({ file, key, lang }) => `${file}:${key}:${lang}`);
    expect(closed).toEqual([]);

    const about = entries().filter(({ file, key }) => file === 'legal/terms.yml' && key === 'about.description');
    expect(about.length).toBeGreaterThanOrEqual(21);
    for (const { lang, text } of about) {
      expect(text, `terms about.description (${lang})`).toContain('AGPL-3.0');
      expect(text, `terms about.description (${lang})`).toContain('https://github.com/glowingkitty/OpenMates');
    }
  }, PARSE_TIMEOUT_MS);

  // contract-test: supporting surface=gui.web assertions=auth.signup.current-flow
  it('removed the signup disclaimer texts together with the step', () => {
    const signupKeys = new Set(entries().filter(({ file }) => file === 'signup/main.yml').map(({ key }) => key));
    for (const removed of [
      'is_alpha_disclaimer', 'decent_stable', 'not_all_core_features_implemented',
      'expect_bugs_and_missing_features', 'continue_with_alpha',
    ]) {
      expect(signupKeys.has(removed), removed).toBe(false);
    }
    // The product version stays visible in the header.
    expect(signupKeys.has('version_title')).toBe(true);
  }, PARSE_TIMEOUT_MS);

  // contract-test: supporting surface=gui.web assertions=auth.signup.current-flow
  it('shows the honest status line in the README instead of an alpha label', () => {
    const readme = readFileSync(README, 'utf8');
    expect(readme).toContain('OpenMates is under active development, and new functions arrive regularly.');
    expect(readme).not.toMatch(/alpha software/i);
    expect(readme).toMatch(/\*\*v\d+\.\d+\*\*/);
  });
});
