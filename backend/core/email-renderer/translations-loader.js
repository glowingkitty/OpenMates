import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import { dirname } from 'path';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

// Path to translations directory
const TRANSLATIONS_PATH = path.join(__dirname, 'shared-ui/src/i18n/locales');

// Store translations for all languages
const translations = {};

/**
 * Load all translation files at server startup
 */
function loadTranslations() {
  try {
    if (!fs.existsSync(TRANSLATIONS_PATH)) {
      console.warn(`Translations directory not found at ${TRANSLATIONS_PATH}`);
      translations['en'] = { email: {} }; // Default fallback
      return;
    }
    
    // Get all JSON files in the locales directory
    const files = fs.readdirSync(TRANSLATIONS_PATH)
      .filter(file => file.endsWith('.json'));
    
    if (files.length === 0) {
      console.warn('No translation files found');
      translations['en'] = { email: {} }; // Default fallback
      return;
    }
    
    // Load each translation file
    files.forEach(file => {
      try {
        const langCode = file.replace('.json', '');
        const filePath = path.join(TRANSLATIONS_PATH, file);
        const content = fs.readFileSync(filePath, 'utf8');
        const json = JSON.parse(content);
        
        // Store only the 'email' portion of translations
        if (json.email) {
          translations[langCode] = { email: json.email };
          console.log(`Loaded email translations for ${langCode}`);
        } else {
          console.warn(`No 'email' key found in translation file ${file}`);
          translations[langCode] = { email: {} };
        }
      } catch (err) {
        console.error(`Error loading translation file ${file}:`, err);
      }
    });
    
    console.log(`Loaded translations for ${Object.keys(translations).length} languages`);
  } catch (error) {
    console.error('Error loading translations:', error);
    translations['en'] = { email: {} }; // Default fallback
  }
}

// Load translations immediately when this module is imported
loadTranslations();

/**
 * Get translation for a specific key and language
 * 
 * @param {string} key - Translation key in dot notation (e.g., 'email.confirm_your_email.text')
 * @param {string} lang - Language code (e.g., 'en', 'fr')
 * @param {object} vars - Variables to interpolate in the translation
 * @returns {string} - The translated string or the key if not found
 */
function getTranslation(key, lang = 'en', vars = {}) {
  // Default to English if the requested language isn't available
  const langData = translations[lang] || translations['en'] || { email: {} };
  
  // Split the key by dots to navigate nested objects
  const parts = key.split('.');
  
  // Remove the first part 'email' since we already have the email subset
  if (parts[0] === 'email') {
    parts.shift();
  }
  
  // Navigate through the translation object
  let current = langData.email;
  for (const part of parts) {
    if (current && typeof current === 'object' && part in current) {
      current = current[part];
    } else {
      return key; // Key not found
    }
  }
  
  // If we found an object with a text property (like in the example)
  if (current && typeof current === 'object' && current.text) {
    current = current.text;
  }
  
  // If we don't have a string at this point, return the key
  if (typeof current !== 'string') {
    return key;
  }
  
  // Replace variables in the translation
  let result = current;
  for (const [varName, varValue] of Object.entries(vars)) {
    result = result.replace(new RegExp(`\\{${varName}\\}`, 'g'), varValue);
  }
  
  return result;
}

/**
 * Get all available languages
 * @returns {string[]} - Array of available language codes
 */
function getAvailableLanguages() {
  return Object.keys(translations);
}

export {
  getTranslation,
  getAvailableLanguages
};
