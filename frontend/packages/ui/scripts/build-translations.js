#!/usr/bin/env node

/**
 * Build script to convert YAML translation source files back to JSON locale files
 * 
 * This script:
 * 1. Reads all YAML files from sources/
 * 2. Converts multi-line YAML text back to <br> tags for JSON
 * 3. Reconstructs the nested JSON structure
 * 4. Creates JSON locale files (en.json, de.json, etc.) in locales/
 * 
 * Usage: node scripts/build-translations.js
 */

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import yaml from 'yaml';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// Import language codes from single source of truth
// Languages ordered: en, de, then by global speaker count (most to least)
import { LANGUAGE_CODES } from './languages-config.js';
const LANGUAGES = LANGUAGE_CODES;

// Paths
const SOURCES_DIR = path.join(__dirname, '../src/i18n/sources');
const LOCALES_DIR = path.join(__dirname, '../src/i18n/locales');

/**
 * Process newlines from YAML back to JSON format
 * 
 * NOTE: We preserve newlines as \n (not convert to <br>) because:
 * - Markdown content (like demo chats) needs \n for proper formatting
 * - The markdown parser expects \n newlines for paragraph breaks
 * - Only trim trailing newlines added by YAML literal block scalars
 * 
 * Content that needs <br> tags (like HTML emails) should have <br> tags
 * explicitly in the YAML source files.
 * 
 * @param {string} text - Text that may contain newlines from YAML
 * @returns {string} Text with newlines preserved as \n (trailing newlines trimmed)
 */
function convertNewlinesToBr(text) {
    if (typeof text !== 'string') {
        return text;
    }
    // Trim trailing newlines (YAML literal block scalars add trailing newlines)
    // This prevents extra newlines at the end of the text
    let trimmedText = text.replace(/\n+$/, '');
    
    // DON'T convert newlines to <br> - keep them as \n for markdown
    // Markdown content (like demo chats) needs \n for proper formatting
    // Content that needs <br> tags should have them explicitly in YAML
    return trimmedText;
}

/**
 * Set nested value in object using dot-notation path
 * Creates intermediate objects as needed
 * 
 * @param {Object} obj - The object to modify
 * @param {string} path - Dot-notation path (e.g., "at_missing.text")
 * @param {any} value - Value to set
 */
function setNestedValue(obj, path, value) {
    const keys = path.split('.');
    let current = obj;
    
    // Navigate/create path except for the last key
    for (let i = 0; i < keys.length - 1; i++) {
        const key = keys[i];
        if (!(key in current) || typeof current[key] !== 'object' || Array.isArray(current[key])) {
            current[key] = {};
        }
        current = current[key];
    }
    
    // Set the final value
    const lastKey = keys[keys.length - 1];
    current[lastKey] = value;
}

/**
 * Recursively load all YAML source files from directory and subdirectories
 * Handles both flat structure (settings.yml) and nested structure (settings/app_store.yml)
 * 
 * @param {string} dir - Directory to scan
 * @param {string} namespacePrefix - Prefix for namespace (e.g., "settings" for settings/app_store.yml)
 * @returns {Object} Object with namespace names as keys and parsed YAML as values
 */
function loadYamlFilesRecursive(dir, namespacePrefix = '') {
    const yamlFiles = {};
    
    if (!fs.existsSync(dir)) {
        return yamlFiles;
    }
    
    const entries = fs.readdirSync(dir, { withFileTypes: true });
    
    for (const entry of entries) {
        const fullPath = path.join(dir, entry.name);
        
        if (entry.isDirectory()) {
            // Recursively load from subdirectory
            // The directory name becomes part of the namespace
            const subNamespace = namespacePrefix ? `${namespacePrefix}.${entry.name}` : entry.name;
            const subFiles = loadYamlFilesRecursive(fullPath, subNamespace);
            Object.assign(yamlFiles, subFiles);
        } else if (entry.isFile() && entry.name.endsWith('.yml')) {
            // Load YAML file
            try {
                const content = fs.readFileSync(fullPath, 'utf-8');
                const parsed = yaml.parse(content);
                
                // Determine namespace and key prefix
                // Files in subdirectories contribute to the parent namespace
                // Keys from subdirectory files are prefixed with the subdirectory/file name
                let namespace;
                let keyPrefix = '';
                
                if (namespacePrefix) {
                    // We're in a subdirectory (e.g., settings/)
                    namespace = namespacePrefix; // Use parent namespace (e.g., "settings")
                    
                    if (entry.name === 'main.yml') {
                        // main.yml keys go directly to the namespace (no prefix)
                        keyPrefix = '';
                    } else {
                        // Other files: prefix keys with filename (e.g., "app_store" from app_store.yml)
                        keyPrefix = entry.name.replace('.yml', '');
                    }
                } else {
                    // Top-level file
                    namespace = entry.name.replace('.yml', '');
                    keyPrefix = '';
                }
                
                // Prefix all keys if needed
                // Exception: if a key matches the filename (e.g., "app_store" key in app_store.yml),
                // don't prefix it (it's the parent key itself)
                let processedData = parsed;
                if (keyPrefix) {
                    processedData = {};
                    for (const [key, value] of Object.entries(parsed)) {
                        if (key === keyPrefix) {
                            // Key matches filename - don't prefix (it's the parent key)
                            processedData[key] = value;
                        } else {
                            // Prefix with the filename
                            processedData[`${keyPrefix}.${key}`] = value;
                        }
                    }
                }
                
                // If namespace already exists, merge the data
                if (yamlFiles[namespace]) {
                    // Merge: keys from the new file are added to existing namespace
                    Object.assign(yamlFiles[namespace], processedData);
                } else {
                    yamlFiles[namespace] = processedData;
                }
                
                const relativePath = path.relative(SOURCES_DIR, fullPath);
                console.log(`✓ Loaded ${relativePath}`);
            } catch (error) {
                console.error(`Error loading ${fullPath}:`, error.message);
                process.exit(1);
            }
        }
    }
    
    return yamlFiles;
}

/**
 * Load all YAML source files
 * @returns {Object} Object with namespace names as keys and parsed YAML as values
 */
function loadAllYamlFiles() {
    if (!fs.existsSync(SOURCES_DIR)) {
        console.error(`Error: Sources directory not found: ${SOURCES_DIR}`);
        process.exit(1);
    }
    
    const yamlFiles = loadYamlFilesRecursive(SOURCES_DIR);
    
    if (Object.keys(yamlFiles).length === 0) {
        console.error(`Error: No YAML files found in ${SOURCES_DIR}`);
        process.exit(1);
    }
    
    return yamlFiles;
}

/**
 * Convert YAML structure back to nested JSON structure for a specific language
 * @param {Object} yamlFiles - All loaded YAML files (namespaces)
 * @param {string} lang - Language code
 * @returns {Object} Nested JSON structure for the language
 */
function convertYamlToJson(yamlFiles, lang) {
    const jsonStructure = {};
    
    // Process each namespace (YAML file)
    for (const [namespace, yamlData] of Object.entries(yamlFiles)) {
        // Initialize namespace in JSON structure
        jsonStructure[namespace] = {};
        
        // Special handling for metadata namespace: always create structure even if values are empty
        // This ensures meta.ts can always find metadata.default structure
        const isMetadataNamespace = namespace === 'metadata';
        
        // Process each key in the YAML file
        for (const [key, value] of Object.entries(yamlData)) {
            if (typeof value !== 'object' || value === null) {
                continue;
            }
            
            // Get text value for this language
            let textValue = value[lang] || '';
            
            // For metadata namespace, always create structure even with empty values
            // For other namespaces, skip empty strings to keep JSON files clean
            if (textValue === '' && !isMetadataNamespace) {
                continue;
            }
            
            // Convert newlines back to <br> tags
            // This reverses the conversion done when creating YAML files
            textValue = convertNewlinesToBr(textValue);
            
            // Build translation object
            // NOTE: We don't include 'context' in JSON output - it's only for YAML documentation
            // The JSON files are used at runtime and don't need context information
            const translationObj = {
                text: textValue
            };
            
            // Build nested structure using dot-notation key
            // Example: "at_missing" -> { at_missing: { text: "...", context: "..." } }
            // Example: "signup.at_missing" -> { signup: { at_missing: { text: "...", context: "..." } } }
            setNestedValue(jsonStructure[namespace], key, translationObj);
        }
    }
    
    return jsonStructure;
}

/**
 * Main build function
 */
function build() {
    console.log('🚀 Starting build from YAML to JSON structure...\n');
    
    // Create locales directory if it doesn't exist
    if (!fs.existsSync(LOCALES_DIR)) {
        fs.mkdirSync(LOCALES_DIR, { recursive: true });
        console.log(`✓ Created locales directory: ${LOCALES_DIR}`);
    }
    
    // Load all YAML files
    console.log('\n📖 Loading YAML source files...');
    const yamlFiles = loadAllYamlFiles();
    
    if (Object.keys(yamlFiles).length === 0) {
        console.error('Error: No YAML files found');
        process.exit(1);
    }
    
    // Convert to JSON for each language
    console.log('\n📝 Converting to JSON structure...');
    let successCount = 0;
    const errors = [];
    
    for (const lang of LANGUAGES) {
        try {
            const jsonStructure = convertYamlToJson(yamlFiles, lang);
            
            // Convert to JSON string with pretty formatting
            const jsonContent = JSON.stringify(jsonStructure, null, 2);
            
            // Write JSON file
            const filePath = path.join(LOCALES_DIR, `${lang}.json`);
            fs.writeFileSync(filePath, jsonContent + '\n', 'utf-8');
            console.log(`✓ Created ${lang}.json`);
            successCount++;
        } catch (error) {
            const errorMsg = `✗ Error creating ${lang}.json: ${error.message}`;
            console.error(errorMsg);
            errors.push({ lang, error: error.message });
        }
    }
    
    // Fail the build if any locale files failed to be created
    if (errors.length > 0) {
        console.error(`\n❌ Build failed! ${errors.length} locale file(s) could not be created:`);
        errors.forEach(({ lang, error }) => {
            console.error(`   - ${lang}.json: ${error}`);
        });
        console.error('\n⚠️  The build cannot proceed without all required locale files.');
        process.exit(1);
    }
    
    // Verify all files were created successfully
    if (successCount !== LANGUAGES.length) {
        console.error(`\n❌ Build failed! Expected ${LANGUAGES.length} locale files, but only ${successCount} were created.`);
        process.exit(1);
    }
    
    console.log(`\n✅ Build complete! Created ${successCount} JSON files in ${LOCALES_DIR}`);
}

// Run build
build();

