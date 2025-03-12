import os
import json
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

class TranslationService:
    def __init__(self):
        # Try to get translations directory from environment variable first
        self.translations_dir = os.getenv("TRANSLATIONS_DIR")
        
        if not self.translations_dir:
            # Fallback to the relative path
            self.translations_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))),
                "frontend", "packages", "ui", "src", "i18n", "locales"
            )
        
        # Cache for loaded translations
        self._translations_cache = {}
        
        logger.info(f"Translation service initialized with directory: {self.translations_dir}")
    
    def get_translations(self, lang: str = "en") -> Dict[str, Any]:
        """
        Get translations for the specified language
        
        Args:
            lang: Language code (default: "en")
            
        Returns:
            Dictionary of translations
        """
        # Check if translations are already cached
        if lang in self._translations_cache:
            return self._translations_cache[lang]
        
        try:
            # Load translations from file
            translation_file = os.path.join(self.translations_dir, f"{lang}.json")
            
            with open(translation_file, 'r', encoding='utf-8') as f:
                translations = json.load(f)
            
            # Cache the translations
            self._translations_cache[lang] = translations
            
            return translations
            
        except FileNotFoundError:
            logger.warning(f"Translation file for language '{lang}' not found in path '{translation_file}'. Falling back to English.")
            # If language file is not found, fall back to English
            if lang != "en":
                return self.get_translations("en")
            else:
                # If English file is missing, return empty dict
                logger.error("English translation file not found")
                return {}
        except Exception as e:
            logger.error(f"Error loading translations for language '{lang}': {str(e)}")
            return {}
    
    def get_nested_translation(self, key: str, lang: str = "en") -> str:
        """
        Get a specific translation by nested key (e.g., "email.confirm_your_email.text")
        
        Args:
            key: Nested key path separated by dots
            lang: Language code
            
        Returns:
            Translated string or key if not found
        """
        translations = self.get_translations(lang)
        
        # Navigate through nested keys
        keys = key.split('.')
        value = translations
        
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                logger.warning(f"Translation key '{key}' not found for language '{lang}'")
                return key
                
        return value if isinstance(value, str) else key
