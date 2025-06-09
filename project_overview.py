import tree_sitter_python as tspython
import tree_sitter_typescript as tstype
import tree_sitter_javascript as tsjs
import pathspec
import subprocess
import re

from tree_sitter import Language, Parser
import os
import json

# Load languages
PY_LANGUAGE = Language(tspython.language())
TS_LANGUAGE = Language(tstype.language_typescript())
JS_LANGUAGE = Language(tsjs.language())

def extract_python_elements(source_code, language):
    parser = Parser(language)
    tree = parser.parse(source_code)
    
    functions = []
    classes = []
    
    def traverse_tree(node):
        if node.type == 'function_definition':
            # Find the function name
            for child in node.children:
                if child.type == 'identifier':
                    func_name = source_code[child.start_byte:child.end_byte].decode('utf-8')
                    functions.append(func_name)
                    break
        elif node.type == 'class_definition':
            # Find the class name
            for child in node.children:
                if child.type == 'identifier':
                    class_name = source_code[child.start_byte:child.end_byte].decode('utf-8')
                    classes.append(class_name)
                    break
        
        # Recursively traverse children
        for child in node.children:
            traverse_tree(child)
    
    traverse_tree(tree.root_node)
    
    result = {}
    if functions:
        result['functions'] = functions
    if classes:
        result['classes'] = classes
    return result

def extract_js_ts_elements(source_code, language):
    parser = Parser(language)
    tree = parser.parse(source_code)
    
    functions = []
    
    def traverse_tree(node):
        if node.type in ['function_declaration', 'method_definition', 'arrow_function']:
            if node.type == 'function_declaration':
                # Find function name
                for child in node.children:
                    if child.type == 'identifier':
                        func_name = source_code[child.start_byte:child.end_byte].decode('utf-8')
                        functions.append(func_name)
                        break
            elif node.type == 'method_definition':
                # Find method name
                for child in node.children:
                    if child.type == 'property_identifier':
                        method_name = source_code[child.start_byte:child.end_byte].decode('utf-8')
                        functions.append(method_name)
                        break
            elif node.type == 'arrow_function':
                functions.append('<arrow_function>')
        
        # Recursively traverse children
        for child in node.children:
            traverse_tree(child)
    
    traverse_tree(tree.root_node)
    
    result = {}
    if functions:
        result['functions'] = functions
    return result

def analyze_python_file_with_ruff(file_path):
    """Analyze a Python file with Ruff to find unused imports and variables."""
    try:
        # Ruff check for unused imports (F401) and unused variables (F841)
        command = ['ruff', 'check', '--select', 'F401,F841', file_path]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        
        unused_imports = []
        unused_variables = []

        if result.returncode != 0 and result.stdout:
            lines = result.stdout.strip().split('\n')
            for line in lines:
                if not line:
                    continue
                
                # Parsing ruff output, e.g., "path/to/file.py:1:1: F401 `os` imported but unused"
                parts = line.split(':')
                if len(parts) < 4:
                    continue

                message = ':'.join(parts[3:]).strip()
                if 'F401' in message:
                    match = re.search(r"`(.+?)`", message)
                    if match:
                        unused_imports.append(match.group(1))
                elif 'F841' in message:
                    match = re.search(r"`(.+?)`", message)
                    if match:
                        unused_variables.append(match.group(1))
        
        result_dict = {}
        if unused_imports:
            result_dict['unused_imports'] = unused_imports
        if unused_variables:
            result_dict['unused_variables'] = unused_variables
        return result_dict
    except FileNotFoundError:
        # Ruff not installed or not in PATH
        return {'ruff_error': 'Ruff not found'}
    except Exception as e:
        return {'ruff_error': str(e)}

def get_file_info(file_path):
    """Get basic file information"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            lines = len(content.splitlines())
            return {'lines': lines, 'size_bytes': len(content.encode('utf-8'))}
    except Exception:
        return {'lines': 0, 'size_bytes': 0}

def analyze_file(file_path):
    try:
        # Get basic file info
        file_info = get_file_info(file_path)
        
        with open(file_path, 'rb') as f:
            source_code = f.read()
        
        if file_path.endswith('.py'):
            parsed_info = extract_python_elements(source_code, PY_LANGUAGE)
            ruff_analysis = analyze_python_file_with_ruff(file_path)
            return {**file_info, **parsed_info, **ruff_analysis, 'type': 'python'}
        elif file_path.endswith(('.ts', '.tsx')):
            parsed_info = extract_js_ts_elements(source_code, TS_LANGUAGE)
            return {**file_info, **parsed_info, 'type': 'typescript'}
        elif file_path.endswith(('.js', '.jsx')):
            parsed_info = extract_js_ts_elements(source_code, JS_LANGUAGE)
            return {**file_info, **parsed_info, 'type': 'javascript'}
        elif file_path.endswith('.svelte'):
            return {**file_info, 'type': 'svelte'}
        else:
            return None
    except Exception as e:
        print(f"Error analyzing {file_path}: {e}")
        file_info = get_file_info(file_path)
        return {**file_info, 'type': 'unknown', 'error': str(e)}

def load_gitignore_rules(root_path):
    gitignore_path = os.path.join(root_path, '.gitignore')
    if os.path.exists(gitignore_path):
        with open(gitignore_path, 'r') as f:
            spec = pathspec.PathSpec.from_lines('gitwildmatch', f)
            return spec
    return None

def analyze_project(root_path):
    spec = load_gitignore_rules(root_path)
    
    overview = {
        'structure': {},
        'summary': {
            'total_files': 0, 
            'python_files': 0, 
            'typescript_files': 0, 
            'javascript_files': 0, 
            'svelte_files': 0,
            'total_lines': 0,
            'total_functions': 0,
            'total_classes': 0,
            'total_unused_imports': 0,
            'total_unused_variables': 0
        }
    }
    
    all_files = []
    for root, dirs, files in os.walk(root_path, topdown=True):
        # Filter directories and files using pathspec
        paths = [os.path.join(root, name) for name in dirs + files]
        if spec:
            ignored_paths = set(spec.match_files(paths))
            dirs[:] = [d for d in dirs if os.path.join(root, d) not in ignored_paths]
            files = [f for f in files if os.path.join(root, f) not in ignored_paths]

        for file in files:
            all_files.append(os.path.join(root, file))

    for file_path in all_files:
        if file_path.endswith(('.py', '.ts', '.tsx', '.js', '.jsx', '.svelte')):
            rel_path = os.path.relpath(file_path, root_path)
            rel_root, file = os.path.split(rel_path)
            if rel_root == '':
                rel_root = 'root'

            if rel_root not in overview['structure']:
                overview['structure'][rel_root] = {'files': {}, 'subdirs': []}

            analysis = analyze_file(file_path)
            
            if analysis:
                overview['structure'][rel_root]['files'][file] = analysis
                overview['summary']['total_files'] += 1
                overview['summary']['total_lines'] += analysis.get('lines', 0)
                
                # Update summary counts
                if file.endswith('.py'):
                    overview['summary']['python_files'] += 1
                    if 'functions' in analysis:
                        overview['summary']['total_functions'] += len(analysis['functions'])
                    if 'classes' in analysis:
                        overview['summary']['total_classes'] += len(analysis['classes'])
                    if 'unused_imports' in analysis:
                        overview['summary']['total_unused_imports'] += len(analysis['unused_imports'])
                    if 'unused_variables' in analysis:
                        overview['summary']['total_unused_variables'] += len(analysis['unused_variables'])
                elif file.endswith(('.ts', '.tsx')):
                    overview['summary']['typescript_files'] += 1
                    if 'functions' in analysis:
                        overview['summary']['total_functions'] += len(analysis['functions'])
                elif file.endswith(('.js', '.jsx')):
                    overview['summary']['javascript_files'] += 1
                    if 'functions' in analysis:
                        overview['summary']['total_functions'] += len(analysis['functions'])
                elif file.endswith('.svelte'):
                    overview['summary']['svelte_files'] += 1
    
    return overview

def main():
    print("Starting project analysis...")
    
    # Analyze current directory (your main project)
    project_overview = analyze_project('.')
    
    # Save to JSON file
    if not os.path.exists('.context'):
        os.makedirs('.context')
    with open('.context/project_overview.json', 'w') as f:
        json.dump(project_overview, f, indent=2)
    
    # Print summary
    print("\n=== Project Overview Generated! ===")
    print(f"Total files analyzed: {project_overview['summary']['total_files']}")
    print(f"Total lines of code: {project_overview['summary']['total_lines']}")
    print(f"Python files: {project_overview['summary']['python_files']}")
    print(f"TypeScript files: {project_overview['summary']['typescript_files']}")
    print(f"JavaScript files: {project_overview['summary']['javascript_files']}")
    print(f"Svelte files: {project_overview['summary']['svelte_files']}")
    print(f"Total functions found: {project_overview['summary']['total_functions']}")
    print(f"Total classes found: {project_overview['summary']['total_classes']}")
    print(f"Total unused imports (Python): {project_overview['summary']['total_unused_imports']}")
    print(f"Total unused variables (Python): {project_overview['summary']['total_unused_variables']}")
    print("\nDetailed overview saved to .context/project_overview.json")
    
    # Print some example findings
    print("\n=== Sample Findings ===")
    for folder, data in list(project_overview['structure'].items())[:3]:
        if data['files']:
            print(f"\nFolder: {folder}")
            for filename, filedata in list(data['files'].items())[:3]:
                print(f"  {filename} ({filedata.get('type', 'unknown')}) - {filedata.get('lines', 0)} lines")
                if 'functions' in filedata and filedata['functions']:
                    print(f"    Functions: {', '.join(filedata['functions'][:5])}{'...' if len(filedata['functions']) > 5 else ''}")
                if 'classes' in filedata and filedata['classes']:
                    print(f"    Classes: {', '.join(filedata['classes'][:3])}{'...' if len(filedata['classes']) > 3 else ''}")
                if 'unused_imports' in filedata and filedata['unused_imports']:
                    print(f"    Unused Imports: {', '.join(filedata['unused_imports'])}")
                if 'unused_variables' in filedata and filedata['unused_variables']:
                    print(f"    Unused Variables: {', '.join(filedata['unused_variables'])}")
                if 'ruff_error' in filedata:
                    print(f"    Ruff Error: {filedata['ruff_error']}")

if __name__ == "__main__":
    main()
