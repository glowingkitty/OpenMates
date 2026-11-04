/**
 * Translation-key gate for app metadata and focus modes.
 *
 * Called by validate-locales.js (Step 8), which runs in `npm run prepare` and in the
 * `sessions.py deploy` translation gate, so a missing key blocks the deploy instead of
 * rendering as a `[T:key]` placeholder.
 *
 * Checks:
 *  A. Every `*_translation_key` / `*_translation_keys` value in the app metadata that
 *     generate-apps-metadata.js would emit (app.yml + focus_modes/<id>/SKILL.md, after
 *     prefix normalisation such as `business.price_products` →
 *     `app_focus_modes.business.price_products`) resolves to a `.text` string in en.json.
 *     This covers the dynamic `app_focus_modes.<app>.<mode>` keys used by the focus pill,
 *     the activation embed and the chat context menu.
 *  B. Every enabled focus mode has a non-empty name and description in EVERY supported
 *     locale (these strings are shown in the UI in the user's language).
 *  C. Focus `process_translation_key` / `systemprompt_translation_key` declared in app.yml
 *     resolve in en.json (the generator would otherwise silently drop them).
 *  D. Static literal keys in frontend source assigned to `labelKey`, `titleKey`,
 *     `descriptionKey`, `placeholderKey`, `i18nKey`, `messageKey` or `*_translation_key`
 *     resolve in en.json. ($text('...') literals are covered by validate-locales Step 4.)
 *
 * Limits: keys built at runtime from arbitrary template strings are only covered when they
 * come from app metadata (A); other translation helpers (`t('...')` with a caller-specific
 * prefix, `translationKey` fields that are later prefixed) are not analysed.
 *
 * Usage (standalone): node scripts/validate-app-translation-keys.js
 */

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import yaml from 'yaml';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const UI_DIR = path.join(__dirname, '..');
const LOCALES_DIR = path.join(UI_DIR, 'src/i18n/locales');
const BACKEND_APPS_DIR = path.resolve(UI_DIR, '../../../backend/apps');
const SOURCE_DIRS = [path.join(UI_DIR, 'src'), path.resolve(UI_DIR, '../../apps/web_app/src')];

const STATIC_KEY_REGEX =
    /\b(?:labelKey|titleKey|descriptionKey|placeholderKey|i18nKey|messageKey|\w*_translation_key)\s*[:=]\s*['"]([a-z0-9_]+\.[a-z0-9_.]+)['"]/g;
const SKIPPED_SOURCE = /(\.test\.ts|\.spec\.ts|\.preview\.ts|\.d\.ts)$|[\\/](__tests__|generated)[\\/]|appsMetadata\.ts$/;

/** True when `key` resolves to a node with a string `.text` leaf (and, if required, non-empty). */
export function resolvesToText(locale, key, { nonEmpty = false } = {}) {
    let current = locale;
    for (const part of key.split('.')) {
        if (current == null || typeof current !== 'object') return false;
        current = current[part];
    }
    if (current == null || typeof current !== 'object' || typeof current.text !== 'string') return false;
    return !nonEmpty || current.text.trim() !== '';
}

/** Collect every translation key referenced by generated app metadata, with a readable location. */
export function collectMetadataKeyRefs(appsMetadata) {
    const refs = [];
    const visit = (node, where) => {
        if (Array.isArray(node)) {
            node.forEach((item, index) => visit(item, `${where}[${item?.id ?? index}]`));
            return;
        }
        if (node == null || typeof node !== 'object') return;
        for (const [field, value] of Object.entries(node)) {
            if (field.endsWith('_translation_key') && typeof value === 'string' && value.trim()) {
                refs.push({ key: value.trim(), where: `${where}.${field}` });
            } else if (field.endsWith('_translation_keys') && Array.isArray(value)) {
                value.filter(v => typeof v === 'string' && v.trim()).forEach(v => refs.push({ key: v.trim(), where: `${where}.${field}` }));
            } else if (typeof value === 'object') {
                visit(value, `${where}.${field}`);
            }
        }
    };
    for (const [appId, app] of Object.entries(appsMetadata)) visit(app, appId);
    return refs;
}

/** Focus `process`/`systemprompt` keys declared inline in app.yml focuses (raw, before the generator filters them). */
export function collectDeclaredFocusInstructionKeys(backendAppsDir = BACKEND_APPS_DIR) {
    const refs = [];
    if (!fs.existsSync(backendAppsDir)) return refs;
    for (const entry of fs.readdirSync(backendAppsDir, { withFileTypes: true })) {
        const appYml = path.join(backendAppsDir, entry.name, 'app.yml');
        if (!entry.isDirectory() || !fs.existsSync(appYml)) continue;
        const data = yaml.parse(fs.readFileSync(appYml, 'utf-8')) || {};
        for (const focus of data.focuses || data.focus_modes || []) {
            if (focus?.default_enabled === false) continue;
            for (const field of ['process_translation_key', 'systemprompt_translation_key']) {
                if (typeof focus?.[field] === 'string' && focus[field].trim()) {
                    refs.push({ key: focus[field].trim(), where: `backend/apps/${entry.name}/app.yml focuses[${focus.id}].${field}` });
                }
            }
        }
    }
    return refs;
}

/** Scan frontend source text for literal keys assigned to known label/translation-key fields. */
export function scanStaticKeyRefs(files, readFile = file => fs.readFileSync(file, 'utf-8')) {
    const refs = [];
    for (const file of files) {
        if (SKIPPED_SOURCE.test(file)) continue;
        const lines = readFile(file).split('\n');
        lines.forEach((line, index) => {
            STATIC_KEY_REGEX.lastIndex = 0;
            let match;
            while ((match = STATIC_KEY_REGEX.exec(line)) !== null) {
                refs.push({ key: match[1], where: `${path.relative(UI_DIR, file)}:${index + 1}` });
            }
        });
    }
    return refs;
}

/**
 * Pure validation core (unit-tested with fixtures).
 * @returns {string[]} error messages; empty means the gate passes
 */
export function validateAppTranslationKeys({ locales, languageCodes, appsMetadata, declaredFocusKeys = [], staticRefs = [] }) {
    const en = locales.en;
    if (!en) return ['en locale is missing'];
    const errors = [];
    const seen = new Set();
    const requireEn = (refs, label) => {
        for (const { key, where } of refs) {
            if (seen.has(`${label}:${key}`) || resolvesToText(en, key, { nonEmpty: true })) continue;
            seen.add(`${label}:${key}`);
            errors.push(`${label}: '${key}' (${where}) is missing in en.json → would render as [T:${key}]`);
        }
    };
    requireEn(collectMetadataKeyRefs(appsMetadata), 'app metadata');
    requireEn(declaredFocusKeys, 'focus instructions');
    requireEn(staticRefs, 'static key');

    for (const [appId, app] of Object.entries(appsMetadata)) {
        for (const focus of app.focus_modes || []) {
            for (const field of ['name_translation_key', 'description_translation_key']) {
                const key = focus[field];
                if (!key) {
                    errors.push(`focus mode ${appId}.${focus.id}: ${field} is not set`);
                    continue;
                }
                const missing = languageCodes.filter(lang => !locales[lang] || !resolvesToText(locales[lang], key, { nonEmpty: true }));
                if (missing.length && !missing.includes('en')) {
                    errors.push(`focus mode ${appId}.${focus.id}: '${key}' has no translation for ${missing.join(', ')}`);
                }
            }
        }
    }
    return errors;
}

function walkSourceFiles(dir, out = []) {
    if (!fs.existsSync(dir)) return out;
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        if (entry.name === 'node_modules' || entry.name.startsWith('.')) continue;
        const full = path.join(dir, entry.name);
        if (entry.isDirectory()) walkSourceFiles(full, out);
        else if (/\.(svelte|ts)$/.test(entry.name)) out.push(full);
    }
    return out;
}

/** Build the generated app metadata in memory without the generator's per-app logging. */
export async function loadAppsMetadataQuietly() {
    const { buildAppsMetadata } = await import('./generate-apps-metadata.js');
    const { log, warn } = console;
    console.log = () => {};
    console.warn = () => {};
    try {
        return buildAppsMetadata();
    } finally {
        console.log = log;
        console.warn = warn;
    }
}

/** Full repository check against built locale JSON. */
export async function runAppTranslationKeyCheck({ locales, languageCodes }) {
    return validateAppTranslationKeys({
        locales,
        languageCodes,
        appsMetadata: await loadAppsMetadataQuietly(),
        declaredFocusKeys: collectDeclaredFocusInstructionKeys(),
        staticRefs: scanStaticKeyRefs(SOURCE_DIRS.flatMap(dir => walkSourceFiles(dir))),
    });
}

if (process.argv[1] && path.resolve(process.argv[1]) === __filename) {
    const { LANGUAGE_CODES } = await import('./languages-config.js');
    const locales = Object.fromEntries(LANGUAGE_CODES.flatMap(lang => {
        const file = path.join(LOCALES_DIR, `${lang}.json`);
        return fs.existsSync(file) ? [[lang, JSON.parse(fs.readFileSync(file, 'utf-8'))]] : [];
    }));
    const errors = await runAppTranslationKeyCheck({ locales, languageCodes: LANGUAGE_CODES });
    errors.forEach(error => console.error(`❌ ${error}`));
    if (errors.length) process.exit(1);
    console.log('✓ App metadata, focus mode and static label translation keys resolve');
}
