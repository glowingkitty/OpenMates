import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFileSync, readdirSync, existsSync } from 'node:fs';
import { resolve } from 'node:path';
import yaml from 'yaml';
import { parseSkillMd, focusTranslationContent } from './generate-apps-metadata.js';

const root = resolve(import.meta.dirname, '../../../..');
const source = resolve(root, 'frontend/packages/ui/src/i18n/sources/focus_modes');

// contract-test: supporting surface=gui.web assertions=settings-ui.localization.visible-content-resolves,focus-modes.full-instruction
test('every generated focus instruction key has real authored source content', () => {
  for (const app of readdirSync(resolve(root, 'backend/apps'), { withFileTypes: true }).filter(item => item.isDirectory())) {
    const dir = resolve(root, 'backend/apps', app.name, 'focus_modes');
    if (!existsSync(dir)) continue;
    for (const focus of readdirSync(dir)) {
      const path = resolve(dir, focus, 'SKILL.md');
      if (!existsSync(path)) continue;
      const parsed = parseSkillMd(path, app.name, focus);
      for (const [field, key] of [['systemprompt', 'systemprompt_translation_key'], ['process', 'process_translation_key']]) {
        if (parsed[key]) {
          const values = yaml.parse(readFileSync(resolve(source, `${app.name}_${parsed.id}.yml`), 'utf8'));
          assert.equal(typeof values[field]?.en, 'string');
          assert.ok(values[field].en.trim());
          assert.ok(!values[field].en.includes('[T:'));
        }
      }
    }
  }
});

// contract-test: supporting surface=gui.web assertions=settings-ui.localization.visible-content-resolves,focus-modes.full-instruction
test('social calendar recovers its complete authored prompt while empty modes remain empty', () => {
  const social = parseSkillMd(resolve(root, 'backend/apps/social_media/focus_modes/content-calendar-strategist/SKILL.md'), 'social_media', 'content-calendar-strategist');
  assert.equal(social.systemprompt_translation_key, 'focus_modes.social_media_content_calendar_strategist.systemprompt');
  assert.equal(social.systemprompt, focusTranslationContent('social_media', 'content_calendar_strategist').systemprompt);
  const empty = parseSkillMd(resolve(root, 'backend/apps/code/focus_modes/analyze-logs/SKILL.md'), 'code', 'analyze-logs');
  assert.equal(empty.systemprompt, undefined);
  assert.equal(empty.systemprompt_translation_key, undefined);
  assert.equal(empty.process_translation_key, undefined);
});
