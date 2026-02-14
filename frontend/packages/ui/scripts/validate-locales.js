#!/usr/bin/env node

/**
 * Validation script for locale JSON files and translation integrity
 * 
 * This script:
 * 1. Reads LANGUAGE_CODES from languages.json (single source of truth)
 * 2. Checks if each required locale JSON file exists and is valid JSON
 * 3. Validates that all .text leaf values are strings (catches [object Object] bugs)
 * 4. Validates YAML source files for non-string language values
 * 5. Scans .svelte/.ts files for $text() calls and validates keys exist in en.json
 * 
 * This ensures the build fails early if locale files are missing, malformed,
 * or would produce [object Object] at runtime.
 * 
 * Usage: node scripts/validate-locales.js
 */

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import yaml from 'yaml';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// Import language codes from single source of truth
import { LANGUAGE_CODES } from './languages-config.js';

// Paths
const LOCALES_DIR = path.join(__dirname, '../src/i18n/locales');
const SOURCES_DIR = path.join(__dirname, '../src/i18n/sources');
const SRC_DIR = path.join(__dirname, '../src');

// ─── Helper: walk a directory tree ──────────────────────────────────────────

/**
 * Recursively list all files matching a predicate
 * @param {string} dir - Root directory
 * @param {(name: string) => boolean} filter - Filter function for filenames
 * @returns {string[]} Array of absolute file paths
 */
function walkFiles(dir, filter) {
    const results = [];
    if (!fs.existsSync(dir)) return results;
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        const full = path.join(dir, entry.name);
        if (entry.isDirectory()) {
            // Skip node_modules and hidden directories
            if (entry.name === 'node_modules' || entry.name.startsWith('.')) continue;
            results.push(...walkFiles(full, filter));
        } else if (entry.isFile() && filter(entry.name)) {
            results.push(full);
        }
    }
    return results;
}

// ─── 1. Validate locale JSON files exist and are valid ──────────────────────

/**
 * Validate that all required locale JSON files exist and are valid
 * @returns {{ missingFiles: string[], invalidFiles: Array<{langCode: string, error: string}>, parsedLocales: Object }}
 */
function validateLocaleFiles() {
    console.log('🔍 Validating locale JSON files...\n');

    if (!fs.existsSync(LOCALES_DIR)) {
        console.error(`❌ Locales directory does not exist: ${LOCALES_DIR}`);
        console.error('   Run "npm run build:translations" first to generate locale files.');
        process.exit(1);
    }

    const missingFiles = [];
    const invalidFiles = [];
    const parsedLocales = {};

    for (const langCode of LANGUAGE_CODES) {
        const filePath = path.join(LOCALES_DIR, `${langCode}.json`);

        if (!fs.existsSync(filePath)) {
            missingFiles.push(langCode);
            console.error(`❌ Missing locale file: ${langCode}.json`);
            continue;
        }

        try {
            const fileContent = fs.readFileSync(filePath, 'utf-8');
            parsedLocales[langCode] = JSON.parse(fileContent);
            console.log(`✓ ${langCode}.json exists and is valid`);
        } catch (error) {
            invalidFiles.push({ langCode, error: error.message });
            console.error(`❌ Invalid JSON in ${langCode}.json: ${error.message}`);
        }
    }

    return { missingFiles, invalidFiles, parsedLocales };
}

// ─── 2. Validate .text leaf values are strings ──────────────────────────────

/**
 * Recursively walk the JSON locale tree and ensure every `.text` leaf is a string.
 * Non-string .text values would render as [object Object] in the UI.
 *
 * @param {Object} obj - The locale JSON object
 * @param {string} dotPath - Current dot-notation path for error messages
 * @returns {string[]} Array of error messages
 */
function findNonStringTextLeaves(obj, dotPath = '') {
    const errors = [];
    if (obj == null || typeof obj !== 'object') return errors;

    for (const [key, value] of Object.entries(obj)) {
        const currentPath = dotPath ? `${dotPath}.${key}` : key;

        if (key === 'text') {
            // .text must always be a string
            if (typeof value !== 'string') {
                errors.push(`${currentPath} is ${typeof value} (expected string) → would render as [object Object]`);
            }
        } else if (typeof value === 'object' && value !== null) {
            errors.push(...findNonStringTextLeaves(value, currentPath));
        }
    }
    return errors;
}

// ─── 3. Validate YAML source files ─────────────────────────────────────────

/**
 * Scan all YAML source files and ensure language values (en, de, …) are strings.
 * A non-string value (e.g., a nested object) would propagate into the JSON and
 * eventually render as [object Object].
 *
 * @returns {string[]} Array of error messages
 */
function validateYamlSources() {
    const errors = [];
    const yamlFiles = walkFiles(SOURCES_DIR, name => name.endsWith('.yml'));

    for (const filePath of yamlFiles) {
        const relativePath = path.relative(SOURCES_DIR, filePath);
        let parsed;
        try {
            parsed = yaml.parse(fs.readFileSync(filePath, 'utf-8'));
        } catch (e) {
            errors.push(`${relativePath}: YAML parse error — ${e.message}`);
            continue;
        }
        if (parsed == null || typeof parsed !== 'object') continue;

        for (const [key, entry] of Object.entries(parsed)) {
            if (entry == null || typeof entry !== 'object') continue;

            // Check every language code value in this entry
            for (const lang of LANGUAGE_CODES) {
                if (!(lang in entry)) continue;
                const val = entry[lang];
                if (val !== null && val !== undefined && typeof val !== 'string' && typeof val !== 'number' && typeof val !== 'boolean') {
                    errors.push(
                        `${relativePath} → key "${key}" → ${lang}: value is ${typeof val} (expected string) → would cause [object Object]`
                    );
                }
            }
        }
    }
    return errors;
}

// ─── 4. Validate $text() keys against en.json ──────────────────────────────

/**
 * Resolve a dot-notation key inside a nested object.
 * Returns the value at the path, or undefined if any segment is missing.
 *
 * @param {Object} obj - Root object
 * @param {string} dotKey - Dot-notation key (e.g., "login.loading")
 * @returns {any}
 */
function resolveDotKey(obj, dotKey) {
    const parts = dotKey.split('.');
    let current = obj;
    for (const part of parts) {
        if (current == null || typeof current !== 'object') return undefined;
        current = current[part];
    }
    return current;
}

/**
 * Scan .svelte and .ts source files for $text('...') calls and validate that
 * each referenced key resolves to a node with a .text string in en.json.
 *
 * This catches:
 *  - Typos in translation keys (key doesn't exist)
 *  - Intermediate node references (key exists but has no .text leaf)
 *
 * @param {Object} enLocale - Parsed en.json
 * @returns {{ missingKeys: Array<{key: string, file: string, line: number}>, objectKeys: Array<{key: string, file: string, line: number}> }}
 */
function validateTextKeysInSource(enLocale) {
    const missingKeys = [];
    const objectKeys = [];
    const seenKeys = new Set(); // deduplicate per-key (still report file:line for first occurrence)

    const sourceFiles = walkFiles(SRC_DIR, name =>
        name.endsWith('.svelte') || (name.endsWith('.ts') && !name.endsWith('.d.ts'))
    );

    // Regex matches $text('some.key') and $text("some.key") — single or double quotes.
    // It also matches the store-access form: $text('key', { vars }).
    // The key is captured in group 1.
    const textCallRegex = /\$text\(\s*['"]([^'"]+)['"]/g;

    // Skip files that reference $text() for non-lookup purposes (e.g., the translation helper itself)
    const SKIP_FILES = new Set(['src/i18n/translations.ts']);

    for (const filePath of sourceFiles) {
        const relFile = path.relative(path.join(__dirname, '..'), filePath);

        // Skip files that aren't actual translation consumers
        if (SKIP_FILES.has(relFile)) continue;

        const content = fs.readFileSync(filePath, 'utf-8');
        const lines = content.split('\n');

        for (let lineIdx = 0; lineIdx < lines.length; lineIdx++) {
            const line = lines[lineIdx];
            let match;
            textCallRegex.lastIndex = 0;

            while ((match = textCallRegex.exec(line)) !== null) {
                const key = match[1];

                // Skip dynamic keys (template fragments, incomplete keys ending with .)
                if (key.includes('${') || key.endsWith('.') || key === '') continue;

                // The runtime $text() appends ".text" to the key before lookup.
                // So we need to check if <namespace>.<key>.text exists.
                // The key format is "namespace.subkey" → in JSON it's namespace.subkey.text
                const resolved = resolveDotKey(enLocale, key);

                if (resolved === undefined) {
                    // Key doesn't exist at all in en.json
                    if (!seenKeys.has(`missing:${key}`)) {
                        seenKeys.add(`missing:${key}`);
                        missingKeys.push({ key, file: relFile, line: lineIdx + 1 });
                    }
                } else if (typeof resolved === 'object' && resolved !== null) {
                    // Key resolves to a node — check if it has a .text string leaf
                    if (!('text' in resolved) || typeof resolved.text !== 'string') {
                        if (!seenKeys.has(`object:${key}`)) {
                            seenKeys.add(`object:${key}`);
                            objectKeys.push({ key, file: relFile, line: lineIdx + 1 });
                        }
                    }
                    // If it has .text and it's a string, that's fine (collision node with valid text)
                }
            }
        }
    }

    return { missingKeys, objectKeys };
}

// ─── Main ───────────────────────────────────────────────────────────────────

function validateLocales() {
    let hasErrors = false;

    // ── Step 1: Check locale files exist and are valid JSON ──
    const { missingFiles, invalidFiles, parsedLocales } = validateLocaleFiles();

    if (missingFiles.length > 0 || invalidFiles.length > 0) {
        hasErrors = true;
    }

    // ── Step 2: Check .text leaves are strings in every locale ──
    console.log('\n🔍 Checking .text leaf values in locale JSON files...\n');
    let textLeafErrors = 0;
    for (const [langCode, locale] of Object.entries(parsedLocales)) {
        const errors = findNonStringTextLeaves(locale);
        if (errors.length > 0) {
            hasErrors = true;
            textLeafErrors += errors.length;
            for (const err of errors) {
                console.error(`❌ [${langCode}.json] ${err}`);
            }
        }
    }
    if (textLeafErrors === 0) {
        console.log('✓ All .text leaf values are strings in every locale file');
    }

    // ── Step 3: Check YAML source files for non-string language values ──
    console.log('\n🔍 Checking YAML source files for non-string values...\n');
    const yamlErrors = validateYamlSources();
    if (yamlErrors.length > 0) {
        hasErrors = true;
        for (const err of yamlErrors) {
            console.error(`❌ ${err}`);
        }
    } else {
        console.log('✓ All YAML language values are strings');
    }

    // ── Step 4: Validate $text() keys against en.json ──
    console.log('\n🔍 Validating $text() keys in source code against en.json...\n');
    const enLocale = parsedLocales['en'];
    if (enLocale) {
        const { missingKeys, objectKeys } = validateTextKeysInSource(enLocale);

        if (objectKeys.length > 0) {
            // Object keys reference intermediate nodes (no .text leaf).
            // At runtime, the typeof guard in translations.ts catches these and
            // shows [T:key] placeholder instead of [object Object]. Warn so
            // developers fix them, but don't block the build.
            console.warn(`⚠️  Found ${objectKeys.length} $text() call(s) referencing keys that resolve to objects (broken translation — shows placeholder):\n`);
            for (const { key, file, line } of objectKeys) {
                console.warn(`   $text('${key}')  →  ${file}:${line}`);
            }
        }

        if (missingKeys.length > 0) {
            // Missing keys show [T:key] placeholder — warn but don't fail the build
            // (they might be dynamically constructed keys or not yet added)
            console.warn(`\n⚠️  Found ${missingKeys.length} $text() call(s) referencing keys not found in en.json (will show [T:key] placeholder):\n`);
            for (const { key, file, line } of missingKeys) {
                console.warn(`   $text('${key}')  →  ${file}:${line}`);
            }
        }

        if (objectKeys.length === 0 && missingKeys.length === 0) {
            console.log('✓ All static $text() keys resolve to valid translations');
        } else if (objectKeys.length === 0) {
            console.log('\n✓ No [object Object] risks found in $text() calls');
        }
    } else {
        console.warn('⚠️  en.json not available — skipping $text() key validation');
    }

    // ── Summary ──
    if (hasErrors) {
        console.error('\n' + '═'.repeat(70));
        console.error('❌ Validation FAILED!');

        if (missingFiles.length > 0) {
            console.error(`\n   Missing locale files (${missingFiles.length}):`);
            missingFiles.forEach(lang => console.error(`     - ${lang}.json`));
        }
        if (invalidFiles.length > 0) {
            console.error(`\n   Invalid locale files (${invalidFiles.length}):`);
            invalidFiles.forEach(({ langCode, error }) => console.error(`     - ${langCode}.json: ${error}`));
        }
        if (textLeafErrors > 0) {
            console.error(`\n   Non-string .text values: ${textLeafErrors}`);
        }
        if (yamlErrors.length > 0) {
            console.error(`\n   YAML source errors: ${yamlErrors.length}`);
        }

        console.error('\n⚠️  The build cannot proceed with translation errors.');
        console.error('   Fix the issues above, then run "npm run build:translations && npm run validate:locales".');
        console.error('═'.repeat(70));
        process.exit(1);
    }

    console.log(`\n✅ Validation passed! All ${LANGUAGE_CODES.length} locale files are valid and translation keys are correct.`);
}

// Run validation
validateLocales();

