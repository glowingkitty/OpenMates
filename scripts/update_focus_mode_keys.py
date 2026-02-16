#!/usr/bin/env python3
"""
Update focus mode translation keys in app.yml files to point to the new focus_modes namespace.

This script:
1. Reads all backend/apps/*/app.yml files
2. Updates name_translation_key and description_translation_key for focus modes
3. Optionally removes systemprompt and process fields (with --remove-prompts flag)

Usage: 
    python scripts/update_focus_mode_keys.py           # Update keys only
    python scripts/update_focus_mode_keys.py --remove-prompts  # Update keys and remove prompts
"""

import os
import sys
import yaml
from pathlib import Path
from typing import Dict, Any

# Paths
REPO_ROOT = Path(__file__).parent.parent
APPS_DIR = REPO_ROOT / "backend" / "apps"


def load_yaml_with_comments(file_path: Path) -> tuple[str, Dict[str, Any]]:
    """
    Load a YAML file preserving comments and structure.
    Returns: (original_content, parsed_data)
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    data = yaml.safe_load(content) or {}
    return content, data


def update_focus_mode_keys(app_yml_path: Path, remove_prompts: bool = False) -> bool:
    """
    Update focus mode translation keys in an app.yml file.
    Returns: True if changes were made, False otherwise.
    """
    app_id = app_yml_path.parent.name
    
    with open(app_yml_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    updated = False
    in_focuses_section = False
    current_focus_id = None
    indent_level = 0
    
    for i, line in enumerate(lines):
        if line is None:
            continue
        stripped = line.lstrip()
        
        # Track when we enter the focuses section
        if stripped.startswith('focuses:'):
            in_focuses_section = True
            indent_level = len(line) - len(stripped)
            continue
        
        if not in_focuses_section:
            continue
        
        # Exit focuses section if we encounter a top-level key
        current_indent = len(line) - len(stripped)
        if current_indent <= indent_level and stripped and not stripped.startswith('#'):
            in_focuses_section = False
            current_focus_id = None
            continue
        
        # Track current focus ID
        if stripped.startswith('- id:'):
            current_focus_id = stripped.split(':', 1)[1].strip()
            continue
        
        if not current_focus_id:
            continue
        
        # Update name_translation_key
        if stripped.startswith('name_translation_key:'):
            old_value = stripped.split(':', 1)[1].strip()
            new_value = f"focus_modes.{app_id}_{current_focus_id}.text"
            
            if old_value != new_value:
                # Preserve indentation and update the value
                indent = line[:len(line) - len(stripped)]
                lines[i] = f"{indent}name_translation_key: {new_value}\n"
                updated = True
                print(f"    Updated name_translation_key: {old_value} → {new_value}")
        
        # Update description_translation_key
        elif stripped.startswith('description_translation_key:'):
            old_value = stripped.split(':', 1)[1].strip()
            new_value = f"focus_modes.{app_id}_{current_focus_id}.description"
            
            if old_value != new_value:
                indent = line[:len(line) - len(stripped)]
                lines[i] = f"{indent}description_translation_key: {new_value}\n"
                updated = True
                print(f"    Updated description_translation_key: {old_value} → {new_value}")
        
        # Optionally remove systemprompt field
        elif remove_prompts and (stripped.startswith('systemprompt:') or stripped.startswith('systemprompt: |')):
            # Mark line for removal
            lines[i] = None
            updated = True
            print(f"    Removed systemprompt for {current_focus_id}")
            
            # Remove subsequent lines if it's a multiline block
            if '|' in line:
                j = i + 1
                while j < len(lines):
                    next_line = lines[j]
                    next_stripped = next_line.lstrip()
                    next_indent = len(next_line) - len(next_stripped)
                    
                    # Stop if we hit a line at the same or lower indentation level (not part of the block)
                    if next_stripped and not next_stripped.startswith('#') and next_indent <= current_indent + 2:
                        break
                    
                    lines[j] = None
                    j += 1
        
        # Optionally remove process field
        elif remove_prompts and (stripped.startswith('process:') or stripped.startswith('process: |')):
            # Mark line for removal
            lines[i] = None
            updated = True
            print(f"    Removed process for {current_focus_id}")
            
            # Remove subsequent lines if it's a multiline block or list
            if '|' in line or ':' in line:
                j = i + 1
                while j < len(lines):
                    next_line = lines[j]
                    next_stripped = next_line.lstrip()
                    next_indent = len(next_line) - len(next_stripped)
                    
                    # Stop if we hit a line at the same or lower indentation level
                    if next_stripped and not next_stripped.startswith('#') and not next_stripped.startswith('-') and next_indent <= current_indent + 2:
                        break
                    
                    lines[j] = None
                    j += 1
    
    if updated:
        # Filter out removed lines and write back
        lines = [line for line in lines if line is not None]
        with open(app_yml_path, 'w', encoding='utf-8') as f:
            f.writelines(lines)
    
    return updated


def main():
    remove_prompts = '--remove-prompts' in sys.argv
    
    print("🚀 Updating focus mode translation keys in app.yml files...\n")
    
    if remove_prompts:
        print("⚠️  --remove-prompts flag detected: Will also remove systemprompt and process fields\n")
    
    updated_count = 0
    
    for app_dir in sorted(APPS_DIR.iterdir()):
        if not app_dir.is_dir():
            continue
        
        app_yml_path = app_dir / "app.yml"
        if not app_yml_path.exists():
            continue
        
        app_id = app_dir.name
        
        # Check if this app has focus modes
        with open(app_yml_path, 'r', encoding='utf-8') as f:
            content = f.read()
            if 'focuses:' not in content:
                continue
        
        print(f"📝 Processing {app_id}...")
        
        if update_focus_mode_keys(app_yml_path, remove_prompts):
            updated_count += 1
            print(f"  ✓ Updated {app_yml_path.relative_to(REPO_ROOT)}\n")
        else:
            print(f"  ⊘ No changes needed\n")
    
    if updated_count > 0:
        print(f"✅ Updated {updated_count} app.yml files")
    else:
        print("✅ All app.yml files are already up to date")


if __name__ == "__main__":
    main()
