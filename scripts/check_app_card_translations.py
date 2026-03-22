#!/usr/bin/env python3
"""
Check app card translations for text that's too long to fit in 2 lines.

App cards are 223px wide with 1rem (16px) padding on each side = 191px text width.
At 14px font size, approximately 28-30 characters fit per line.
With 2 lines, max ~56-60 characters should be safe.

This script checks:
- App descriptions (apps.yml)
- Skill descriptions (apps.yml and app_skills/*.yml)
- Settings/memories descriptions (app_settings_memories/*.yml)
- Focus mode descriptions (app_focus_modes/*.yml)
"""

import os
import sys
import yaml
from pathlib import Path

# Maximum characters for 2 lines at 14px font on 191px width
# Being conservative: ~28 chars per line * 2 lines = 56 chars
MAX_CHARS = 55

# Languages to check (all supported languages)
LANGUAGES = ['en', 'de', 'zh', 'es', 'fr', 'pt', 'ru', 'ja', 'ko', 'it', 'tr', 'vi', 'id', 'pl', 'nl', 'ar', 'hi', 'th', 'cs', 'sv']

# Color codes for terminal output
RED = '\033[91m'
YELLOW = '\033[93m'
GREEN = '\033[92m'
RESET = '\033[0m'
BOLD = '\033[1m'


def load_yaml_file(filepath: Path) -> dict:
    """Load a YAML file and return its contents."""
    with open(filepath, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f) or {}


def check_translation_length(key: str, translations: dict, source_file: str) -> list:
    """Check if any translation for a key exceeds MAX_CHARS."""
    issues = []
    
    for lang in LANGUAGES:
        if lang in translations:
            text = translations[lang]
            if isinstance(text, str) and len(text) > MAX_CHARS:
                issues.append({
                    'key': key,
                    'lang': lang,
                    'text': text,
                    'length': len(text),
                    'file': source_file
                })
    
    return issues


def find_description_keys(data: dict, prefix: str = '') -> list:
    """Find all keys ending with .description or that are description keys."""
    description_entries = []
    
    for key, value in data.items():
        full_key = f"{prefix}{key}" if prefix else key
        
        # Check if this is a description key (ends with .description or is a flat key with description)
        if key.endswith('.description') or key == 'description':
            if isinstance(value, dict):
                description_entries.append((full_key, value))
        elif isinstance(value, dict):
            # Check if it's a translation entry (has 'en' key)
            if 'en' in value and isinstance(value.get('en'), str):
                # This might be a description entry
                if 'description' in full_key.lower():
                    description_entries.append((full_key, value))
            else:
                # Recurse into nested dicts
                description_entries.extend(find_description_keys(value, f"{full_key}."))
    
    return description_entries


def check_apps_yml(i18n_dir: Path) -> list:
    """Check apps.yml for long descriptions."""
    issues = []
    apps_file = i18n_dir / 'sources' / 'apps.yml'
    
    if not apps_file.exists():
        print(f"{YELLOW}Warning: {apps_file} not found{RESET}")
        return issues
    
    data = load_yaml_file(apps_file)
    
    # Find all description keys
    for key, translations in data.items():
        if '.description' in key and isinstance(translations, dict):
            issues.extend(check_translation_length(key, translations, 'apps.yml'))
    
    return issues


def check_app_skills(i18n_dir: Path) -> list:
    """Check app_skills/*.yml for long descriptions."""
    issues = []
    skills_dir = i18n_dir / 'sources' / 'app_skills'
    
    if not skills_dir.exists():
        print(f"{YELLOW}Warning: {skills_dir} not found{RESET}")
        return issues
    
    for yml_file in skills_dir.glob('*.yml'):
        data = load_yaml_file(yml_file)
        
        for key, translations in data.items():
            if '.description' in key and isinstance(translations, dict):
                issues.extend(check_translation_length(key, translations, f'app_skills/{yml_file.name}'))
    
    return issues


def check_app_settings_memories(i18n_dir: Path) -> list:
    """Check app_settings_memories/*.yml for long descriptions."""
    issues = []
    settings_dir = i18n_dir / 'sources' / 'app_settings_memories'
    
    if not settings_dir.exists():
        print(f"{YELLOW}Warning: {settings_dir} not found{RESET}")
        return issues
    
    for yml_file in settings_dir.glob('*.yml'):
        data = load_yaml_file(yml_file)
        
        for key, translations in data.items():
            if '.description' in key and isinstance(translations, dict):
                issues.extend(check_translation_length(key, translations, f'app_settings_memories/{yml_file.name}'))
    
    return issues


def check_app_focus_modes(i18n_dir: Path) -> list:
    """Check app_focus_modes/*.yml for long descriptions."""
    issues = []
    focus_dir = i18n_dir / 'sources' / 'app_focus_modes'
    
    if not focus_dir.exists():
        print(f"{YELLOW}Warning: {focus_dir} not found{RESET}")
        return issues
    
    for yml_file in focus_dir.glob('*.yml'):
        data = load_yaml_file(yml_file)
        
        for key, translations in data.items():
            if '.description' in key and isinstance(translations, dict):
                issues.extend(check_translation_length(key, translations, f'app_focus_modes/{yml_file.name}'))
    
    return issues


def main():
    # Find i18n directory
    script_dir = Path(__file__).parent
    repo_root = script_dir.parent
    i18n_dir = repo_root / 'frontend' / 'packages' / 'ui' / 'src' / 'i18n'
    
    if not i18n_dir.exists():
        print(f"{RED}Error: i18n directory not found at {i18n_dir}{RESET}")
        sys.exit(1)
    
    print(f"{BOLD}Checking app card translations for text > {MAX_CHARS} characters...{RESET}\n")
    
    all_issues = []
    
    # Check all sources
    print("Checking apps.yml...")
    all_issues.extend(check_apps_yml(i18n_dir))
    
    print("Checking app_skills/*.yml...")
    all_issues.extend(check_app_skills(i18n_dir))
    
    print("Checking app_settings_memories/*.yml...")
    all_issues.extend(check_app_settings_memories(i18n_dir))
    
    print("Checking app_focus_modes/*.yml...")
    all_issues.extend(check_app_focus_modes(i18n_dir))
    
    print()
    
    if not all_issues:
        print(f"{GREEN}✓ All translations are within {MAX_CHARS} characters!{RESET}")
        return
    
    # Group issues by key
    issues_by_key = {}
    for issue in all_issues:
        key = f"{issue['file']}:{issue['key']}"
        if key not in issues_by_key:
            issues_by_key[key] = []
        issues_by_key[key].append(issue)
    
    print(f"{RED}Found {len(all_issues)} translations that are too long:{RESET}\n")
    
    for key, issues in sorted(issues_by_key.items()):
        file_path, trans_key = key.split(':', 1)
        print(f"{BOLD}{file_path}{RESET}")
        print(f"  Key: {trans_key}")
        
        for issue in sorted(issues, key=lambda x: -x['length']):
            color = RED if issue['length'] > MAX_CHARS + 20 else YELLOW
            print(f"  {color}[{issue['lang']}] {issue['length']} chars:{RESET} {issue['text'][:80]}{'...' if len(issue['text']) > 80 else ''}")
        print()
    
    # Summary by file
    print(f"{BOLD}Summary by file:{RESET}")
    files_count = {}
    for issue in all_issues:
        files_count[issue['file']] = files_count.get(issue['file'], 0) + 1
    
    for file, count in sorted(files_count.items(), key=lambda x: -x[1]):
        print(f"  {file}: {count} issues")
    
    print(f"\n{BOLD}Total: {len(all_issues)} translations need shortening{RESET}")


if __name__ == '__main__':
    main()
