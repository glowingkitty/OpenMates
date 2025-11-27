#!/usr/bin/env node

/**
 * Validation script to ensure all required locale JSON files exist
 * 
 * This script:
 * 1. Reads LANGUAGE_CODES from languages.json (single source of truth)
 * 2. Checks if each required locale JSON file exists
 * 3. Validates that the JSON files are valid JSON
 * 4. Exits with error code if any files are missing or invalid
 * 
 * This ensures the build fails early if locale files are missing,
 * preventing runtime errors in production.
 * 
 * Usage: node scripts/validate-locales.js
 */

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// Import language codes from single source of truth
import { LANGUAGE_CODES } from './languages-config.js';

// Path to locales directory
const LOCALES_DIR = path.join(__dirname, '../src/i18n/locales');

/**
 * Validate that all required locale JSON files exist and are valid
 */
function validateLocales() {
    console.log('🔍 Validating locale JSON files...\n');
    
    // Check if locales directory exists
    if (!fs.existsSync(LOCALES_DIR)) {
        console.error(`❌ Locales directory does not exist: ${LOCALES_DIR}`);
        console.error('   Run "npm run build:translations" first to generate locale files.');
        process.exit(1);
    }
    
    const missingFiles = [];
    const invalidFiles = [];
    
    // Check each required locale file
    for (const langCode of LANGUAGE_CODES) {
        const filePath = path.join(LOCALES_DIR, `${langCode}.json`);
        
        // Check if file exists
        if (!fs.existsSync(filePath)) {
            missingFiles.push(langCode);
            console.error(`❌ Missing locale file: ${langCode}.json`);
            continue;
        }
        
        // Validate JSON syntax
        try {
            const fileContent = fs.readFileSync(filePath, 'utf-8');
            JSON.parse(fileContent);
            console.log(`✓ ${langCode}.json exists and is valid`);
        } catch (error) {
            invalidFiles.push({ langCode, error: error.message });
            console.error(`❌ Invalid JSON in ${langCode}.json: ${error.message}`);
        }
    }
    
    // Fail if any files are missing or invalid
    if (missingFiles.length > 0 || invalidFiles.length > 0) {
        console.error('\n❌ Validation failed!');
        
        if (missingFiles.length > 0) {
            console.error(`\n   Missing files (${missingFiles.length}):`);
            missingFiles.forEach(lang => {
                console.error(`     - ${lang}.json`);
            });
        }
        
        if (invalidFiles.length > 0) {
            console.error(`\n   Invalid files (${invalidFiles.length}):`);
            invalidFiles.forEach(({ langCode, error }) => {
                console.error(`     - ${langCode}.json: ${error}`);
            });
        }
        
        console.error('\n⚠️  The build cannot proceed without all required locale files.');
        console.error('   Run "npm run build:translations" to regenerate locale files.');
        process.exit(1);
    }
    
    console.log(`\n✅ Validation passed! All ${LANGUAGE_CODES.length} locale files exist and are valid.`);
}

// Run validation
validateLocales();

