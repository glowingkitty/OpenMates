/**
 * Single source of truth for supported languages (JavaScript version for scripts)
 * This file reads from languages.json which is the actual source of truth.
 * Both frontend (TypeScript/JavaScript) and backend (Python) read from the same JSON file.
 */

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// Load from JSON file (single source of truth)
const languagesJsonPath = path.join(__dirname, '../src/i18n/languages.json');
const languagesData = JSON.parse(fs.readFileSync(languagesJsonPath, 'utf-8'));

export const LANGUAGE_CODES = languagesData.languages.map(lang => lang.code);

export const LANGUAGE_NAMES = Object.fromEntries(
    languagesData.languages.map(lang => [lang.code, lang.name])
);

