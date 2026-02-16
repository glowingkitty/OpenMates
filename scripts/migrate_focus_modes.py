#!/usr/bin/env python3
"""
Migrate focus mode translations from app.yml files to separate YML files.

This script:
1. Reads all backend/apps/*/app.yml files
2. Extracts focus modes with systemprompt and process fields
3. Creates separate YML files in frontend/packages/ui/src/i18n/sources/focus_modes/
4. Copies translations from frontend/packages/ui/src/i18n/sources/app_focus_modes/
5. Adds systemprompt and process fields to the new files

Usage: python scripts/migrate_focus_modes.py
"""

import os
import yaml
from pathlib import Path
from typing import Dict, List, Any

# Paths
REPO_ROOT = Path(__file__).parent.parent
APPS_DIR = REPO_ROOT / "backend" / "apps"
OLD_TRANSLATIONS_DIR = REPO_ROOT / "frontend" / "packages" / "ui" / "src" / "i18n" / "sources" / "app_focus_modes"
NEW_TRANSLATIONS_DIR = REPO_ROOT / "frontend" / "packages" / "ui" / "src" / "i18n" / "sources" / "focus_modes"

# Language codes (same as in frontend/packages/ui/scripts/languages-config.js)
LANGUAGES = [
    "en", "de", "zh", "es", "fr", "pt", "ru", "ja", "ko", "it", "tr", "vi", "id", "pl", "nl", "ar", "hi", "th", "cs", "sv"
]


def load_yaml_file(file_path: Path) -> Dict[str, Any]:
    """Load a YAML file and return its contents."""
    with open(file_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f) or {}


def save_yaml_file(file_path: Path, data: Dict[str, Any]) -> None:
    """Save data to a YAML file with proper formatting."""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with open(file_path, 'w', encoding='utf-8') as f:
        # Use explicit YAML dumper for better control
        yaml.dump(data, f, 
                 default_flow_style=False, 
                 allow_unicode=True, 
                 sort_keys=False,
                 width=120,
                 indent=2)


def extract_focus_modes_from_apps() -> Dict[str, List[Dict[str, Any]]]:
    """
    Extract all focus modes from app.yml files.
    Returns: {app_id: [focus_mode_definitions]}
    """
    focus_modes_by_app = {}
    
    for app_dir in APPS_DIR.iterdir():
        if not app_dir.is_dir():
            continue
            
        app_yml_path = app_dir / "app.yml"
        if not app_yml_path.exists():
            continue
            
        app_id = app_dir.name
        app_data = load_yaml_file(app_yml_path)
        
        focuses = app_data.get('focuses', [])
        if focuses and isinstance(focuses, list):
            focus_modes_by_app[app_id] = focuses
            
    return focus_modes_by_app


def load_old_translations(app_id: str, focus_id: str) -> Dict[str, Dict[str, str]]:
    """
    Load translations from the old app_focus_modes structure.
    Returns: {
        'text': {lang: value},
        'description': {lang: value}
    }
    """
    old_file = OLD_TRANSLATIONS_DIR / f"{app_id}.yml"
    
    if not old_file.exists():
        print(f"  ⚠️  No old translation file found: {old_file}")
        return {}
    
    old_data = load_yaml_file(old_file)
    
    # Extract translations for this specific focus mode
    translations = {}
    
    # Look for focus_id key and focus_id.description key
    for key_suffix in ['', '.description']:
        lookup_key = f"{focus_id}{key_suffix}"
        
        if lookup_key in old_data:
            entry = old_data[lookup_key]
            if isinstance(entry, dict):
                # Extract language translations
                lang_translations = {}
                for lang in LANGUAGES:
                    if lang in entry:
                        lang_translations[lang] = entry[lang]
                
                # Determine the field name (text or description)
                field_name = 'description' if key_suffix else 'text'
                translations[field_name] = lang_translations
                
    return translations


def create_focus_mode_translation_file(app_id: str, focus_mode: Dict[str, Any]) -> None:
    """
    Create a new translation file for a focus mode.
    """
    focus_id = focus_mode.get('id')
    if not focus_id:
        print(f"  ⚠️  Skipping focus mode without ID in app {app_id}")
        return
    
    print(f"  Processing {app_id}/{focus_id}...")
    
    # Load old translations
    old_translations = load_old_translations(app_id, focus_id)
    
    # Build new translation structure
    new_structure = {}
    
    # Text (display name)
    if 'text' in old_translations:
        new_structure['text'] = {
            'context': f"Focus mode display name for {focus_id} in {app_id} app",
            **old_translations['text'],
            'verified_by_human': ['en'] if 'en' in old_translations['text'] else []
        }
    else:
        # Fallback: create placeholder with focus_id as display name
        display_name = focus_id.replace('_', ' ').title()
        new_structure['text'] = {
            'context': f"Focus mode display name for {focus_id} in {app_id} app",
            'en': display_name,
            'verified_by_human': []
        }
    
    # Description
    if 'description' in old_translations:
        new_structure['description'] = {
            'context': f"Focus mode description for {focus_id}",
            **old_translations['description'],
            'verified_by_human': ['en'] if 'en' in old_translations['description'] else []
        }
    else:
        # Fallback: create placeholder
        new_structure['description'] = {
            'context': f"Focus mode description for {focus_id}",
            'en': f"Focus mode for {display_name}",
            'verified_by_human': []
        }
    
    # System prompt (from app.yml)
    systemprompt = focus_mode.get('systemprompt', '').strip()
    if systemprompt:
        new_structure['systemprompt'] = {
            'context': f"System prompt for the LLM when {focus_id} focus mode is active",
            'en': systemprompt,
            'verified_by_human': ['en']
        }
    
    # Process (from app.yml)
    process = focus_mode.get('process')
    if process:
        if isinstance(process, list):
            process_text = '\n'.join(f"- {item}" for item in process if item)
        elif isinstance(process, str):
            process_text = process.strip()
        else:
            process_text = str(process)
        
        if process_text:
            new_structure['process'] = {
                'context': f"Step-by-step process description for {focus_id} focus mode",
                'en': process_text,
                'verified_by_human': ['en']
            }
    
    # Save to new location
    output_file = NEW_TRANSLATIONS_DIR / f"{app_id}_{focus_id}.yml"
    save_yaml_file(output_file, new_structure)
    print(f"    ✓ Created {output_file.relative_to(REPO_ROOT)}")


def main():
    print("🚀 Starting focus mode translation migration...\n")
    
    # Create output directory
    NEW_TRANSLATIONS_DIR.mkdir(parents=True, exist_ok=True)
    
    # Extract focus modes from all apps
    print("📖 Loading focus modes from app.yml files...")
    focus_modes_by_app = extract_focus_modes_from_apps()
    
    if not focus_modes_by_app:
        print("❌ No focus modes found in any app.yml files")
        return
    
    total_focus_modes = sum(len(modes) for modes in focus_modes_by_app.values())
    print(f"Found {total_focus_modes} focus modes across {len(focus_modes_by_app)} apps\n")
    
    # Process each app's focus modes
    for app_id, focus_modes in sorted(focus_modes_by_app.items()):
        print(f"📝 Processing {app_id} ({len(focus_modes)} focus modes):")
        for focus_mode in focus_modes:
            create_focus_mode_translation_file(app_id, focus_mode)
        print()
    
    print(f"✅ Migration complete! Created {total_focus_modes} translation files in {NEW_TRANSLATIONS_DIR.relative_to(REPO_ROOT)}")
    print("\n📌 Next steps:")
    print("1. Review the generated files")
    print("2. Run: cd frontend/packages/ui && npm run build:translations")
    print("3. Update backend code to load systemprompt and process from translation service")
    print("4. Remove systemprompt and process fields from app.yml files")


if __name__ == "__main__":
    main()
