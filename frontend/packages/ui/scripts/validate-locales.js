#!/usr/bin/env node

/**
 * Validation script for locale JSON files and translation integrity
 * 
 * This script performs 7 validation steps:
 * 1. Checks if each required locale JSON file exists and is valid JSON
 * 2. Validates that all .text leaf values are strings (catches [object Object] bugs)
 * 3. Validates YAML source files for non-string language values
 * 4. Scans .svelte/.ts files for $text() calls and validates keys exist in en.json
 *    — scans both packages/ui/src AND apps/web_app/src
 * 5. Validates translation keys in matesMetadata.ts against en.json
 * 6. Validates legal document builder keys against en.json
 * 7. Cross-locale completeness: checks all non-English locales have the same keys as en.json
 * 
 * This ensures the build fails early if locale files are missing, malformed,
 * contain broken translation keys, or have missing translations in any locale.
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
// Also scan the web_app source directory for $text() calls (routes, pages, etc.)
const WEB_APP_SRC_DIR = path.join(__dirname, '../../apps/web_app/src');
const LEGAL_CONTENT_PATH = path.join(SRC_DIR, 'legal', 'buildLegalContent.ts');

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
    console.log('🔍 Step 1: Validating locale JSON files...\n');

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
 * Scans both packages/ui/src AND apps/web_app/src to catch all translation
 * key usages across the entire frontend.
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

    // File filter: .svelte and .ts files (excluding .d.ts declaration files)
    const fileFilter = name =>
        name.endsWith('.svelte') || (name.endsWith('.ts') && !name.endsWith('.d.ts'));

    // Collect source files from both directories
    const sourceFiles = [
        ...walkFiles(SRC_DIR, fileFilter),
        ...walkFiles(WEB_APP_SRC_DIR, fileFilter)
    ];

    // Regex matches $text('some.key') and $text("some.key") — single or double quotes.
    // It also matches the store-access form: $text('key', { vars }).
    // The key is captured in group 1.
    const textCallRegex = /\$text\(\s*['"]([^'"]+)['"]/g;

    // Skip files that reference $text() for non-lookup purposes (e.g., the translation helper itself)
    const SKIP_FILES = new Set(['src/i18n/translations.ts']);

    // Base directory for relative path computation (packages/ui/)
    const uiBaseDir = path.join(__dirname, '..');

    for (const filePath of sourceFiles) {
        const relFile = path.relative(uiBaseDir, filePath);

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

// ─── 5. Validate matesMetadata.ts translation keys ─────────────────────────

/**
 * Extract translation keys from matesMetadata.ts and validate them against en.json.
 * Mates define name_translation_key and description_translation_key properties.
 *
 * @param {Object} enLocale - Parsed en.json
 * @returns {{ missingKeys: Array<{key: string, file: string, property: string}> }}
 */
function validateMatesMetadataKeys(enLocale) {
    const missingKeys = [];
    const matesMetadataPath = path.join(SRC_DIR, 'data', 'matesMetadata.ts');

    if (!fs.existsSync(matesMetadataPath)) {
        console.warn('⚠️  matesMetadata.ts not found — skipping mates key validation');
        return { missingKeys };
    }

    const content = fs.readFileSync(matesMetadataPath, 'utf-8');

    // Extract all translation key string values from *_translation_key properties.
    // Matches patterns like: name_translation_key: "mates.software_development"
    // or: description_translation_key: 'mate_descriptions.software_development'
    const keyRegex = /(\w+_translation_key)\s*:\s*['"]([^'"]+)['"]/g;
    let match;

    while ((match = keyRegex.exec(content)) !== null) {
        const property = match[1];
        const key = match[2];

        const resolved = resolveDotKey(enLocale, key);

        if (resolved === undefined) {
            missingKeys.push({ key, file: 'src/data/matesMetadata.ts', property });
        } else if (typeof resolved === 'object' && resolved !== null) {
            // Key exists but needs a .text leaf
            if (!('text' in resolved) || typeof resolved.text !== 'string') {
                missingKeys.push({ key, file: 'src/data/matesMetadata.ts', property });
            }
        }
    }

    return { missingKeys };
}

// ─── 6. Validate legal content translation keys ─────────────────────────────

/**
 * Legal documents build markdown from a translation function passed into
 * buildLegalContent.ts. Some keys are dynamic provider bases, so static $text()
 * scanning cannot see them.
 *
 * @param {Object} enLocale - Parsed en.json
 * @returns {{ missingKeys: Array<{key: string, file: string, line: number}>, objectKeys: Array<{key: string, file: string, line: number}> }}
 */
function validateLegalContentKeys(enLocale) {
    const missingKeys = [];
    const objectKeys = [];

    if (!fs.existsSync(LEGAL_CONTENT_PATH)) {
        console.warn('⚠️  buildLegalContent.ts not found — skipping legal content key validation');
        return { missingKeys, objectKeys };
    }

    const content = fs.readFileSync(LEGAL_CONTENT_PATH, 'utf-8');
    const lines = content.split('\n');
    const keys = new Map();

    function addKey(key, line) {
        if (!keys.has(key)) {
            keys.set(key, line);
        }
    }

    for (let lineIdx = 0; lineIdx < lines.length; lineIdx++) {
        const line = lines[lineIdx];
        const lineNumber = lineIdx + 1;

        const tCallRegex = /\bt\(\s*['"]([^'"$]+)['"]/g;
        let tMatch;
        while ((tMatch = tCallRegex.exec(line)) !== null) {
            addKey(tMatch[1], lineNumber);
        }

        const providerRegex = /\brenderProvider\(\s*['"]([^'"]+)['"]/g;
        let providerMatch;
        while ((providerMatch = providerRegex.exec(line)) !== null) {
            const baseKey = providerMatch[1];
            addKey(`${baseKey}.heading`, lineNumber);
            addKey(`${baseKey}.description`, lineNumber);
        }
    }

    for (const [key, line] of keys.entries()) {
        const resolved = resolveDotKey(enLocale, key);
        if (resolved === undefined) {
            missingKeys.push({ key, file: 'src/legal/buildLegalContent.ts', line });
        } else if (
            typeof resolved !== 'object' ||
            resolved === null ||
            !('text' in resolved) ||
            typeof resolved.text !== 'string'
        ) {
            objectKeys.push({ key, file: 'src/legal/buildLegalContent.ts', line });
        }
    }

    return { missingKeys, objectKeys };
}

// ─── 7. Cross-locale completeness check ─────────────────────────────────────

/**
 * Collect all leaf key paths (dot-notation paths ending in .text) from a locale object.
 *
 * @param {Object} obj - The locale JSON object
 * @param {string} prefix - Current dot-notation prefix
 * @returns {Set<string>} Set of dot-notation key paths (e.g., "signup.sign_up.text")
 */
function collectLeafPaths(obj, prefix = '') {
    const paths = new Set();
    if (obj == null || typeof obj !== 'object') return paths;

    for (const [key, value] of Object.entries(obj)) {
        const currentPath = prefix ? `${prefix}.${key}` : key;

        if (key === 'text' && typeof value === 'string') {
            // This is a valid translation leaf
            paths.add(currentPath);
        } else if (typeof value === 'object' && value !== null) {
            for (const subPath of collectLeafPaths(value, currentPath)) {
                paths.add(subPath);
            }
        }
    }
    return paths;
}

/**
 * Check that all non-English locales contain the same .text leaf keys as en.json.
 * Missing keys in a locale mean that language will show [T:key] placeholders at runtime.
 *
 * @param {Object} parsedLocales - Map of language code to parsed JSON
 * @returns {{ missingByLocale: Object<string, string[]>, totalMissing: number }}
 */
function validateCrossLocaleCompleteness(parsedLocales) {
    const enLocale = parsedLocales['en'];
    if (!enLocale) {
        return { missingByLocale: {}, totalMissing: 0 };
    }

    const enPaths = collectLeafPaths(enLocale);
    const missingByLocale = {};
    let totalMissing = 0;

    for (const langCode of LANGUAGE_CODES) {
        if (langCode === 'en') continue;
        const locale = parsedLocales[langCode];
        if (!locale) continue; // already reported as missing file in step 1

        const localePaths = collectLeafPaths(locale);
        const missing = [];

        for (const enPath of enPaths) {
            if (!localePaths.has(enPath)) {
                // Convert .text leaf path back to the $text() key format for readability
                // e.g., "signup.sign_up.text" → "signup.sign_up"
                const displayKey = enPath.endsWith('.text')
                    ? enPath.slice(0, -5)
                    : enPath;
                missing.push(displayKey);
            }
        }

        if (missing.length > 0) {
            missingByLocale[langCode] = missing;
            totalMissing += missing.length;
        }
    }

    return { missingByLocale, totalMissing };
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
    console.log('\n🔍 Step 2: Checking .text leaf values in locale JSON files...\n');
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
    console.log('\n🔍 Step 3: Checking YAML source files for non-string values...\n');
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
    // Scans both packages/ui/src AND apps/web_app/src
    console.log('\n🔍 Step 4: Validating $text() keys in source code against en.json...\n');
    const enLocale = parsedLocales['en'];
    let missingKeyCount = 0;
    let objectKeyCount = 0;

    if (enLocale) {
        const { missingKeys, objectKeys } = validateTextKeysInSource(enLocale);
        missingKeyCount = missingKeys.length;
        objectKeyCount = objectKeys.length;

        if (objectKeys.length > 0) {
            // Object keys reference intermediate nodes (no .text leaf).
            // At runtime, the typeof guard in translations.ts catches these and
            // shows [T:key] placeholder instead of [object Object].
            // This is a build-breaking error — these keys will never render correctly.
            hasErrors = true;
            console.error(`❌ Found ${objectKeys.length} $text() call(s) referencing keys that resolve to objects (broken translation — shows [T:] placeholder):\n`);
            for (const { key, file, line } of objectKeys) {
                console.error(`   $text('${key}')  →  ${file}:${line}`);
            }
        }

        if (missingKeys.length > 0) {
            // Missing keys will show [T:key] placeholder in the UI.
            // This is a build-breaking error — every static $text() key must exist.
            hasErrors = true;
            console.error(`\n❌ Found ${missingKeys.length} $text() call(s) referencing keys not found in en.json (will show [T:key] placeholder):\n`);
            for (const { key, file, line } of missingKeys) {
                console.error(`   $text('${key}')  →  ${file}:${line}`);
            }
        }

        if (objectKeys.length === 0 && missingKeys.length === 0) {
            console.log('✓ All static $text() keys resolve to valid translations');
        }
    } else {
        console.warn('⚠️  en.json not available — skipping $text() key validation');
    }

    // ── Step 5: Validate matesMetadata.ts translation keys ──
    console.log('\n🔍 Step 5: Validating matesMetadata.ts translation keys against en.json...\n');
    if (enLocale) {
        const { missingKeys: matesMissing } = validateMatesMetadataKeys(enLocale);
        if (matesMissing.length > 0) {
            hasErrors = true;
            console.error(`❌ Found ${matesMissing.length} missing translation key(s) in matesMetadata.ts:\n`);
            for (const { key, property } of matesMissing) {
                console.error(`   ${property}: '${key}'  →  not found in en.json`);
            }
        } else {
            console.log('✓ All matesMetadata.ts translation keys resolve to valid translations');
        }
    } else {
        console.warn('⚠️  en.json not available — skipping matesMetadata key validation');
    }

    // ── Step 6: Validate legal content translation keys ──
    console.log('\n🔍 Step 6: Validating legal content translation keys against en.json...\n');
    let legalMissingKeyCount = 0;
    let legalObjectKeyCount = 0;
    if (enLocale) {
        const { missingKeys: legalMissing, objectKeys: legalObjects } = validateLegalContentKeys(enLocale);
        legalMissingKeyCount = legalMissing.length;
        legalObjectKeyCount = legalObjects.length;

        if (legalObjects.length > 0) {
            hasErrors = true;
            console.error(`❌ Found ${legalObjects.length} legal content key(s) that do not resolve to string .text leaves:\n`);
            for (const { key, file, line } of legalObjects) {
                console.error(`   '${key}'  →  ${file}:${line}`);
            }
        }

        if (legalMissing.length > 0) {
            hasErrors = true;
            console.error(`\n❌ Found ${legalMissing.length} legal content key(s) not found in en.json:\n`);
            for (const { key, file, line } of legalMissing) {
                console.error(`   '${key}'  →  ${file}:${line}`);
            }
        }

        if (legalObjects.length === 0 && legalMissing.length === 0) {
            console.log('✓ All legal content translation keys resolve to valid translations');
        }
    } else {
        console.warn('⚠️  en.json not available — skipping legal content key validation');
    }

    // ── Step 7: Cross-locale completeness check ──
    // Verifies that every key present in en.json also exists in all other locales.
    // Missing keys in non-English locales cause [T:key] placeholders for those languages.
    console.log('\n🔍 Step 7: Checking cross-locale completeness (all locales vs en.json)...\n');
    if (enLocale) {
        const { missingByLocale, totalMissing } = validateCrossLocaleCompleteness(parsedLocales);

        if (totalMissing > 0) {
            // Report as warnings (not build-breaking errors) because:
            // 1. New translations take time to be translated to all languages
            // 2. svelte-i18n falls back to the English value when a key is missing in a locale
            // 3. Making this a hard error would block builds whenever new keys are added
            // Once translation coverage is high enough, this can be upgraded to an error.
            const localesAffected = Object.keys(missingByLocale).length;
            console.warn(`⚠️  ${totalMissing} translation(s) missing across ${localesAffected} locale(s):\n`);

            for (const [langCode, missing] of Object.entries(missingByLocale)) {
                // Show count and first few examples per locale to keep output manageable
                const MAX_EXAMPLES = 5;
                const shown = missing.slice(0, MAX_EXAMPLES);
                const remaining = missing.length - MAX_EXAMPLES;
                console.warn(`   ${langCode}: ${missing.length} missing key(s)`);
                for (const key of shown) {
                    console.warn(`      - ${key}`);
                }
                if (remaining > 0) {
                    console.warn(`      ... and ${remaining} more`);
                }
            }
            console.warn('');
        } else {
            console.log('✓ All locales have complete translations matching en.json');
        }
    } else {
        console.warn('⚠️  en.json not available — skipping cross-locale completeness check');
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
        if (missingKeyCount > 0) {
            console.error(`\n   Missing $text() keys in source code: ${missingKeyCount}`);
        }
        if (objectKeyCount > 0) {
            console.error(`\n   Broken $text() keys (resolve to objects): ${objectKeyCount}`);
        }
        if (legalMissingKeyCount > 0) {
            console.error(`\n   Missing legal content keys: ${legalMissingKeyCount}`);
        }
        if (legalObjectKeyCount > 0) {
            console.error(`\n   Broken legal content keys: ${legalObjectKeyCount}`);
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
