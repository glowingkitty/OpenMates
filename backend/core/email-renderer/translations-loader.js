import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import { dirname } from 'path';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

// Path to UI translations - this should match the path in the docker-compose volume mount
const TRANSLATIONS_PATH = path.join(__dirname, 'shared-ui/src/i18n/locales');

/**
 * Load translations for a specific language
 * @param {string} lang - Language code (e.g., 'en', 'de')
 * @returns {object} - Translation dictionary for the requested language
 */
function loadTranslations(lang) {
  try {
    const translationFile = path.join(TRANSLATIONS_PATH, `${lang}.json`);
    
    // Check if translation file exists
    if (!fs.existsSync(translationFile)) {
        console.warn(`Path: ${translationFile}`);
        console.warn(`Translation file  for ${lang} not found, falling back to English`);
        // Fall back to English if requested language isn't available
        if (lang !== 'en') {
            return loadTranslations('en');
        }
        // If English doesn't exist either, return empty object
        return {};
    }
    
    // Read and parse the translation file
    const translationData = fs.readFileSync(translationFile, 'utf8');
    return JSON.parse(translationData);
  } catch (error) {
    console.error(`Error loading translations for ${lang}:`, error);
    return {};
  }
}

/**
 * Get a translated string for a key in a specific language
 * 
 * @param {string} key - Translation key
 * @param {string} lang - Language code
 * @param {object} vars - Variables to interpolate
 * @returns {string} - Translated string
 */
function getTranslation(key, lang = 'en', vars = {}) {
  const translations = loadTranslations(lang);
  let text = translations[key] || key;
  
  // Replace variables in the translation string
  Object.entries(vars).forEach(([varName, value]) => {
    text = text.replace(new RegExp(`{${varName}}`, 'g'), value);
  });
  
  return text;
}

/**
 * Get list of available languages based on translation files
 * @returns {string[]} - Array of language codes
 */
function getAvailableLanguages() {
  try {
    return fs.readdirSync(TRANSLATIONS_PATH)
      .filter(file => file.endsWith('.json'))
      .map(file => file.replace('.json', ''));
  } catch (error) {
    console.error('Error listing languages:', error);
    return ['en']; // Default to English if directory can't be read
  }
}

export { loadTranslations, getTranslation, getAvailableLanguages };
