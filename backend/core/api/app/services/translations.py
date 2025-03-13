import os
import json
import logging
import re
from typing import Dict, Any, Optional

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
    
    def get_translations(self, lang: str = "en", variables: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Get translations for the specified language with variable replacements
        
        Args:
            lang: Language code (default: "en")
            variables: Optional dictionary of variables to replace in translations
            
        Returns:
            Dictionary of translations with variables replaced
        """
        # Load raw translations
        raw_translations = self._load_raw_translations(lang)
        
        # If no variables provided, return raw translations
        if not variables:
            return raw_translations
        
        # Process variables in translations
        processed_translations = self._replace_variables_in_translations(raw_translations, variables)
        
        return processed_translations
    
    def _load_raw_translations(self, lang: str) -> Dict[str, Any]:
        """
        Load raw translations from file or cache
        
        Args:
            lang: Language code
            
        Returns:
            Dictionary of raw translations
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
                return self._load_raw_translations("en")
            else:
                # If English file is missing, return empty dict
                logger.error("English translation file not found")
                return {}
        except Exception as e:
            logger.error(f"Error loading translations for language '{lang}': {str(e)}")
            return {}
    
    def _replace_variables_in_translations(self, translations: Dict[str, Any], variables: Dict[str, Any]) -> Dict[str, Any]:
        """
        Replace variables in all translation strings
        
        Args:
            translations: Dictionary of translations
            variables: Dictionary of variables to replace
            
        Returns:
            Dictionary of processed translations
        """
        processed_translations = {}
        
        # Pattern to match {variable} style placeholders
        pattern = r'\{([a-zA-Z0-9_]+)\}'
        
        def replace_string_variables(text: str) -> str:
            """Replace variables in a single string"""
            if not isinstance(text, str):
                return text
                
            # Function to replace each matched variable
            def replace_var(match):
                var_name = match.group(1)
                if var_name in variables:
                    replacement = variables.get(var_name, '')
                    logger.debug(f"Replacing variable {{{var_name}}} with: {replacement}")
                    return str(replacement if replacement is not None else '')
                else:
                    # If variable not found in context, leave it unchanged
                    logger.debug(f"Variable {{{var_name}}} not found in context, leaving unchanged")
                    return match.group(0)
            
            # Perform the replacement
            return re.sub(pattern, replace_var, text)
        
        # Process each translation entry
        for key, value in translations.items():
            if isinstance(value, str):
                processed_translations[key] = replace_string_variables(value)
            elif isinstance(value, dict):
                # Recursively process nested dictionaries
                processed_translations[key] = self._replace_variables_in_translations(value, variables)
            else:
                # Keep other types unchanged
                processed_translations[key] = value
                
        return processed_translations
    
    def get_nested_translation(self, key: str, lang: str = "en", variables: Optional[Dict[str, Any]] = None) -> str:
        """
        Get a specific translation by nested key with variable replacement
        
        Args:
            key: Nested key path separated by dots
            lang: Language code
            variables: Optional dictionary of variables to replace
            
        Returns:
            Translated string or key if not found
        """
        translations = self.get_translations(lang, variables)
        
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
