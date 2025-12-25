import os
import json
import logging
import re
import yaml
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class TranslationService:
    # Class-level caches shared across all instances
    # These are loaded once on first access and reused for all subsequent requests
    _class_translations_cache: Dict[str, Dict[str, Any]] = {}  # Cache for loaded translations (per language)
    _class_yaml_cache: Dict[str, Dict[str, Any]] = {}  # Cache for loaded YAML files (shared across languages)
    
    def __init__(self):
        # Try to get translations directory from environment variable first
        # Default to YAML sources directory (source of truth)
        self.sources_dir = os.getenv("TRANSLATIONS_SOURCES_DIR")
        
        if not self.sources_dir:
            # Calculate path relative to project root
            # In Docker: /app/backend/core/api/app/services/translations.py -> /app/frontend/...
            # In local: backend/core/api/app/services/translations.py -> frontend/...
            current_file = os.path.abspath(__file__)
            
            # Check if we're in Docker (/app/backend/...) or local (backend/...)
            if current_file.startswith('/app/'):
                # Docker environment: /app/backend/core/api/app/services/translations.py
                # Project root is /app, so frontend is at /app/frontend
                self.sources_dir = "/app/frontend/packages/ui/src/i18n/sources"
            else:
                # Local environment: calculate relative to project root
                # Go up 6 levels: services -> app -> api -> core -> backend -> project root
                project_root = os.path.dirname(
                    os.path.dirname(
                        os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(current_file))))
                    )
                )
                self.sources_dir = os.path.join(
                    project_root,
                    "frontend", "packages", "ui", "src", "i18n", "sources"
                )
        
        logger.info(f"Translation service initialized with YAML sources directory: {self.sources_dir}")
    
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
    
    def _load_all_yaml_files(self) -> Dict[str, Dict[str, Any]]:
        """
        Recursively load all YAML source files from directory and subdirectories
        Handles both flat structure (settings.yml) and nested structure (settings/app_store.yml)
        
        Uses class-level cache so YAML files are loaded once and shared across all instances.
        
        Returns:
            Dictionary with namespace names as keys and parsed YAML as values
        """
        # Use class-level cache shared across all instances
        if TranslationService._class_yaml_cache:
            return TranslationService._class_yaml_cache
        
        yaml_files = {}
        
        if not os.path.exists(self.sources_dir):
            logger.error(f"YAML sources directory not found: {self.sources_dir}")
            return yaml_files
        
        # Recursively walk through the sources directory
        for root, dirs, files in os.walk(self.sources_dir):
            for file in files:
                if file.endswith('.yml'):
                    file_path = os.path.join(root, file)
                    relative_path = os.path.relpath(file_path, self.sources_dir)
                    
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            parsed = yaml.safe_load(f)
                        
                        if parsed is None:
                            continue
                        
                        # Determine namespace and key prefix
                        # Files in subdirectories contribute to the parent namespace
                        path_parts = relative_path.replace('\\', '/').split('/')
                        
                        if len(path_parts) == 1:
                            # Top-level file (e.g., "email.yml")
                            namespace = file.replace('.yml', '')
                            key_prefix = ''
                        else:
                            # File in subdirectory (e.g., "settings/app_store.yml")
                            namespace = path_parts[0]  # Parent directory name
                            if file == 'main.yml':
                                # main.yml keys go directly to the namespace (no prefix)
                                key_prefix = ''
                            else:
                                # Other files: prefix keys with filename (e.g., "app_store" from app_store.yml)
                                key_prefix = file.replace('.yml', '')
                        
                        # Prefix all keys if needed
                        processed_data = parsed
                        if key_prefix:
                            processed_data = {}
                            for key, value in parsed.items():
                                if key == key_prefix:
                                    # Key matches filename - don't prefix (it's the parent key itself)
                                    processed_data[key] = value
                                else:
                                    # Prefix with the filename
                                    processed_data[f"{key_prefix}.{key}"] = value
                        
                        # If namespace already exists, merge the data
                        if namespace in yaml_files:
                            yaml_files[namespace].update(processed_data)
                        else:
                            yaml_files[namespace] = processed_data
                            
                        logger.debug(f"Loaded YAML file: {relative_path} -> namespace: {namespace}")
                    except Exception as e:
                        logger.error(f"Error loading YAML file {file_path}: {str(e)}")
        
        # Store in class-level cache so it's shared across all instances
        TranslationService._class_yaml_cache = yaml_files
        logger.info(f"Loaded {len(yaml_files)} YAML namespaces into shared cache")
        return yaml_files
    
    def _convert_yaml_to_json_structure(self, yaml_files: Dict[str, Dict[str, Any]], lang: str) -> Dict[str, Any]:
        """
        Convert YAML structure to nested JSON structure for a specific language
        Similar to the build-translations.js script logic
        
        Args:
            yaml_files: All loaded YAML files (namespaces)
            lang: Language code
            
        Returns:
            Nested JSON structure for the language
        """
        json_structure = {}
        
        # Import supported languages from single source of truth (languages.json)
        # Both frontend and backend read from the same JSON file
        # NO FALLBACKS - fail hard if file is missing
        # Use the same path calculation logic as __init__ for sources_dir
        current_file = os.path.abspath(__file__)
        
        if current_file.startswith('/app/'):
            # Docker environment: /app/backend/core/api/app/services/translations.py
            # Project root is /app, so frontend is at /app/frontend
            languages_json_path = "/app/frontend/packages/ui/src/i18n/languages.json"
        else:
            # Local environment: calculate relative to project root
            # Go up 6 levels: services -> app -> api -> core -> backend -> project root
            project_root = os.path.dirname(
                os.path.dirname(
                    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(current_file))))
                )
            )
            languages_json_path = os.path.join(
                project_root,
                "frontend", "packages", "ui", "src", "i18n", "languages.json"
            )
        
        if not os.path.exists(languages_json_path):
            logger.error(f"CRITICAL: languages.json not found at {languages_json_path}")
            raise FileNotFoundError(f"languages.json not found at {languages_json_path}. This file is required and must exist.")
        
        with open(languages_json_path, 'r', encoding='utf-8') as f:
            languages_data = json.load(f)
        
        # Extract language codes in order
        supported_languages = [lang['code'] for lang in languages_data['languages']]
        
        if not supported_languages:
            logger.error("CRITICAL: languages.json contains no languages")
            raise ValueError("languages.json contains no languages. This file must contain at least one language.")
        
        if lang not in supported_languages:
            logger.warning(f"Language '{lang}' not in supported languages, falling back to 'en'")
            lang = 'en'
        
        for namespace, namespace_data in yaml_files.items():
            json_structure[namespace] = {}
            logger.debug(f"Processing namespace: {namespace}, keys: {list(namespace_data.keys())[:5]}")
            
            for key, value in namespace_data.items():
                if not isinstance(value, dict):
                    logger.debug(f"Skipping key '{key}' - not a dict")
                    continue
                
                # Get text value for this language
                text_value = value.get(lang, '')
                
                # Skip empty strings to keep JSON clean
                if not text_value:
                    logger.debug(f"Skipping key '{key}' - empty text for language '{lang}'")
                    continue
                
                # Trim trailing newlines (YAML literal block scalars add trailing newlines)
                # Preserve newlines as \n (not convert to <br>) for markdown compatibility
                if isinstance(text_value, str):
                    text_value = text_value.rstrip('\n')
                
                # Build nested structure using dot-notation key
                # Example: "at_missing" -> { at_missing: { text: "..." } }
                # Example: "signup.at_missing" -> { signup: { at_missing: { text: "..." } } }
                keys = key.split('.')
                current = json_structure[namespace]
                
                # Navigate/create nested structure
                for k in keys[:-1]:
                    if k not in current:
                        current[k] = {}
                    current = current[k]
                
                # Set the final value
                last_key = keys[-1]
                current[last_key] = {'text': text_value}
        
        logger.debug(f"Converted JSON structure for '{lang}': top-level keys: {list(json_structure.keys())}")
        if 'email' in json_structure:
            logger.debug(f"Email namespace has {len(json_structure['email'])} keys")
        else:
            logger.warning(f"Email namespace not found in JSON structure! Available namespaces: {list(json_structure.keys())}")
        
        return json_structure
    
    def _load_raw_translations(self, lang: str) -> Dict[str, Any]:
        """
        Load raw translations from YAML source files or cache
        
        Uses class-level cache so translations are loaded once per language and shared across all instances.
        
        Args:
            lang: Language code
            
        Returns:
            Dictionary of raw translations
        """
        # Check if translations are already cached in class-level cache
        if lang in TranslationService._class_translations_cache:
            return TranslationService._class_translations_cache[lang]
        
        try:
            # Load all YAML files
            yaml_files = self._load_all_yaml_files()
            
            if not yaml_files:
                logger.warning(f"No YAML files found in {self.sources_dir}")
                return {}
            
            # Convert YAML structure to nested JSON structure for this language
            translations = self._convert_yaml_to_json_structure(yaml_files, lang)
            
            # Cache the translations in class-level cache so it's shared across all instances
            TranslationService._class_translations_cache[lang] = translations
            logger.info(f"Loaded translations for language '{lang}' into shared cache")
            
            return translations
            
        except Exception as e:
            logger.error(f"Error loading translations for language '{lang}': {str(e)}")
            # If language file is not found or error occurs, fall back to English
            if lang != "en":
                logger.info(f"Falling back to English translations")
                return self._load_raw_translations("en")
            else:
                # If English file is missing, return empty dict
                logger.error("English translation file not found")
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
