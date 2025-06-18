import tree_sitter_python as tspython
import tree_sitter_typescript as tstype
import tree_sitter_javascript as tsjs
import pathspec
import subprocess
import re
import os
import json
import time
from tree_sitter import Language, Parser

# --- Tree-sitter Language Setup ---
PY_LANGUAGE = Language(tspython.language())
TS_LANGUAGE = Language(tstype.language_typescript())
JS_LANGUAGE = Language(tsjs.language())

# --- Tree-sitter Element Extraction ---
def extract_python_elements(source_code, language):
    parser = Parser(language)
    tree = parser.parse(source_code)
    functions, classes = {}, {}
    def traverse_tree(node):
        if node.type == 'function_definition':
            name_node = node.child_by_field_name('name')
            if name_node:
                functions[source_code[name_node.start_byte:name_node.end_byte].decode('utf-8')] = {}
        elif node.type == 'class_definition':
            name_node = node.child_by_field_name('name')
            if name_node:
                classes[source_code[name_node.start_byte:name_node.end_byte].decode('utf-8')] = {}
        for child in node.children:
            traverse_tree(child)
    traverse_tree(tree.root_node)
    return {'functions': functions} if functions else {}, {'classes': classes} if classes else {}

def extract_js_ts_elements(source_code, language):
    parser = Parser(language)
    tree = parser.parse(source_code)
    functions = {}
    def traverse_tree(node):
        func_name = None
        if node.type in ['function_declaration', 'method_definition']:
            name_node = node.child_by_field_name('name')
            if name_node:
                func_name = source_code[name_node.start_byte:name_node.end_byte].decode('utf-8')
        elif node.type == 'arrow_function' and node.parent and node.parent.type == 'variable_declarator':
            name_node = node.parent.child_by_field_name('name')
            if name_node:
                func_name = source_code[name_node.start_byte:name_node.end_byte].decode('utf-8')
        if func_name:
            functions[func_name] = {}
        for child in node.children:
            traverse_tree(child)
    traverse_tree(tree.root_node)
    return {'functions': functions} if functions else {}

# --- Linter Integrations ---

def process_ruff_results(linter_json_output, root_path):
    """
    Processes raw Ruff JSON to create a token-efficient list of errors per file.
    Example output: {"path/to/file.py": ["L10: E722 do not use bare 'except'"]}
    """
    linter_errors = {}
    for error in linter_json_output:
        file_path = os.path.relpath(error['filename'], root_path)
        # Create a compact error message, optimized for LLM context
        error_message = f"L{error['location']['row']}: {error['code']} {error['message']}"
        linter_errors.setdefault(file_path, []).append(error_message)
    return linter_errors

def process_eslint_results(linter_json_output, root_path):
    """
    Processes raw ESLint JSON to create a token-efficient list of errors per file.
    """
    linter_errors = {}
    for file_report in linter_json_output:
        # file_report['filePath'] is an absolute path from the eslint command.
        # We make it relative to the project root for consistent reporting.
        file_path = os.path.relpath(file_report['filePath'], root_path)
        if not file_report['messages']:
            continue
        errors = []
        for error in file_report['messages']:
            rule_id = error.get('ruleId', 'unknown')
            error_message = f"L{error['line']}: {rule_id} {error['message']}"
            errors.append(error_message)
        if errors:
            linter_errors[file_path] = errors
    return linter_errors

def run_ruff_linter(root_path):
    """
    Runs Ruff, ignoring 'imported but unused' errors, and returns structured findings.
    """
    print("Running Ruff linter for Python files...")
    try:
        command = ['ruff', 'check', root_path, '--ignore', 'F401', '--output-format=json', '--exit-zero']
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode != 0 and not result.stdout:
             print(f"WARNING: Ruff command failed with return code {result.returncode}. Stderr: {result.stderr}")
             return {}
        linter_output = json.loads(result.stdout)
        return process_ruff_results(linter_output, root_path)
    except (FileNotFoundError, json.JSONDecodeError, subprocess.CalledProcessError) as e:
        print(f"WARNING: Could not run Ruff linter. Skipping. Error: {e}")
        return {}

def run_eslint_linter(root_path):
    """
    Runs ESLint on the project by iterating through known frontend directories
    that contain their own ESLint configurations.
    """
    print("Running ESLint for JavaScript/TypeScript files...")
    all_results = []
    eslint_dirs = [
        os.path.join(root_path, 'frontend', 'apps', 'web_app'),
        os.path.join(root_path, 'frontend', 'apps', 'website'),
        os.path.join(root_path, 'frontend', 'packages', 'ui')
    ]

    for eslint_dir in eslint_dirs:
        if os.path.exists(eslint_dir):
            print(f"Running ESLint in: {os.path.relpath(eslint_dir, root_path)}")
            try:
                # Run eslint from within the directory that has the config.
                # This ensures it picks up the correct configuration (e.g., eslint.config.js).
                command = ['npx', 'eslint', '.', '--ext', '.js,.jsx,.ts,.tsx', '--format', 'json', '--no-error-on-unmatched-pattern']
                result = subprocess.run(command, capture_output=True, text=True, check=False, cwd=eslint_dir)

                if result.stdout:
                    try:
                        linter_output = json.loads(result.stdout)
                        all_results.extend(linter_output)
                    except json.JSONDecodeError:
                        print(f"WARNING: Could not parse ESLint JSON output from {eslint_dir}.")
                # ESLint exit code 1 means linting errors were found, which is not a failure for us.
                # Exit codes > 1 indicate a fatal error.
                elif result.returncode > 1:
                    print(f"WARNING: ESLint command failed in {eslint_dir} with return code {result.returncode}. Stderr: {result.stderr}")

            except (FileNotFoundError, subprocess.SubprocessError) as e:
                print(f"WARNING: Could not run ESLint in {eslint_dir}. Skipping. Error: {e}")
                continue
    
    if all_results:
        return process_eslint_results(all_results, root_path)
    return {}

def run_linters_on_project(root_path):
    """
    Runs all configured linters on the project and merges the results.
    """
    print("Running linters on the entire project...")
    ruff_errors = run_ruff_linter(root_path)
    eslint_errors = run_eslint_linter(root_path)

    # Merge dictionaries
    merged_errors = ruff_errors.copy()
    for file_path, errors in eslint_errors.items():
        # Normalize path separators for consistency
        normalized_path = os.path.normpath(file_path)
        if normalized_path in merged_errors:
            merged_errors[normalized_path].extend(errors)
        else:
            merged_errors[normalized_path] = errors
            
    error_file_count = len(merged_errors)
    total_errors = sum(len(v) for v in merged_errors.values())
    print(f"Linters found {total_errors} issues across {error_file_count} files (ignoring unused imports for Python).")
    return merged_errors


# --- Core Analysis Logic ---

def analyze_file_structure(file_path, rel_path):
    """Analyzes a single file ONLY for its structure (functions, classes)."""
    try:
        file_info = get_file_info(file_path)
        with open(file_path, 'rb') as f: source_code = f.read()
        
        analysis = {}
        if rel_path.endswith('.py'):
            py_funcs, py_classes = extract_python_elements(source_code, PY_LANGUAGE)
            analysis = {**py_funcs, **py_classes, 'type': 'python'}
        elif rel_path.endswith(('.ts', '.tsx')):
            analysis = {**extract_js_ts_elements(source_code, TS_LANGUAGE), 'type': 'typescript'}
        elif rel_path.endswith(('.js', '.jsx')):
            analysis = {**extract_js_ts_elements(source_code, JS_LANGUAGE), 'type': 'javascript'}
        elif rel_path.endswith('.svelte'):
            analysis = {'type': 'svelte'}
            
        return {**file_info, **analysis}
    except Exception as e:
        return {**get_file_info(file_path), 'type': 'unknown', 'error': str(e)}

def get_file_info(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8') as f: content = f.read()
        return {'lines': len(content.splitlines()), 'size_bytes': len(content.encode('utf-8'))}
    except Exception: return {'lines': 0, 'size_bytes': 0}

def load_ignore_rules(root_path):
    """
    Loads ignore rules from both .gitignore and .overviewignore files.
    """
    ignore_patterns = []
    for ignore_file in ['.gitignore', '.overviewignore']:
        ignore_path = os.path.join(root_path, ignore_file)
        if os.path.exists(ignore_path):
            print(f"Reading ignore rules from {ignore_file}...")
            with open(ignore_path, 'r') as f:
                ignore_patterns.extend(f.readlines())
    
    if ignore_patterns:
        return pathspec.PathSpec.from_lines('gitwildmatch', ignore_patterns)
    return None

def analyze_project(root_path):
    spec = load_ignore_rules(root_path)
    
    # Initialize summary object
    project_summary = {
        'total_files': 0, 'total_lines': 0, 'total_size_bytes': 0,
        'by_language': {}, 'linter_errors': 0, 'total_functions': 0, 'total_classes': 0
    }
    
    # Pass 1: Collect files, respecting .gitignore and .overviewignore
    print("\nPass 1: Finding all relevant files...")
    all_files = []
    supported_extensions = ('.py', '.ts', '.tsx', '.js', '.jsx', '.svelte')
    for root, dirs, files in os.walk(root_path, topdown=True):
        paths_to_check = [os.path.relpath(os.path.join(root, name), root_path) for name in dirs + files]
        if spec:
            ignored_paths = set(spec.match_files(paths_to_check))
            dirs[:] = [d for d in dirs if os.path.relpath(os.path.join(root, d), root_path) not in ignored_paths]
            files = [f for f in files if os.path.relpath(os.path.join(root, f), root_path) not in ignored_paths]

        for file in files:
            if file.endswith(supported_extensions):
                all_files.append(os.path.join(root, file))
    
    project_summary['total_files'] = len(all_files)
    print(f"Found {project_summary['total_files']} files to analyze.")

    # Pass 2: Run Linters for general code quality analysis
    print("\nPass 2: Running project-wide linters...")
    linter_results = run_linters_on_project(root_path)
    project_summary['linter_errors'] = sum(len(v) for v in linter_results.values())

    # Pass 3: Analyze file structure and merge linter data
    print(f"\nPass 3: Analyzing {len(all_files)} files with tree-sitter...")
    overview = {'structure': {'files': {}, 'subdirs': {}}}
    symbol_maps = {'python': {}, 'typescript': {}, 'javascript': {}}
    file_lang_map = {}

    for file_path in all_files:
        rel_path = os.path.normpath(os.path.relpath(file_path, root_path))
        analysis = analyze_file_structure(file_path, rel_path)
        if not analysis: continue
        
        # Aggregate summary data
        project_summary['total_lines'] += analysis.get('lines', 0)
        project_summary['total_size_bytes'] += analysis.get('size_bytes', 0)
        project_summary['total_functions'] += len(analysis.get('functions', {}))
        project_summary['total_classes'] += len(analysis.get('classes', {}))
        lang = analysis.get('type', 'unknown')
        lang_stats = project_summary['by_language'].setdefault(lang, {'files': 0, 'lines': 0})
        lang_stats['files'] += 1
        lang_stats['lines'] += analysis.get('lines', 0)

        if rel_path in linter_results:
            analysis['linter_errors'] = linter_results[rel_path]

        file_lang_map[rel_path] = lang
        if lang in symbol_maps:
            for name in analysis.get('functions', {}): symbol_maps[lang][name] = rel_path
            for name in analysis.get('classes', {}): symbol_maps[lang][name] = rel_path
        
        path_parts = rel_path.split(os.sep)
        current_level = overview['structure']
        for part in path_parts[:-1]:
            current_level = current_level['subdirs'].setdefault(part, {'files': {}, 'subdirs': {}})
        current_level['files'][path_parts[-1]] = analysis

    # Pass 4: Cross-referencing to find unused functions/classes
    print("\nPass 4: Cross-referencing symbols to find unused functions/classes...")
    py_symbols = set(symbol_maps['python'].keys())
    ts_js_symbols = set(symbol_maps['typescript'].keys()) | set(symbol_maps['javascript'].keys())
    all_symbol_definers = {**symbol_maps['python'], **symbol_maps['typescript'], **symbol_maps['javascript']}
    word_regex = re.compile(r'\b[a-zA-Z_]\w*\b')

    for user_file_path in all_files:
        user_file_rel_path = os.path.normpath(os.path.relpath(user_file_path, root_path))
        user_lang = file_lang_map.get(user_file_rel_path)
        
        searchable_symbols = set()
        if user_lang == 'python': searchable_symbols = py_symbols
        elif user_lang in ['typescript', 'javascript', 'svelte']: searchable_symbols = ts_js_symbols
        if not searchable_symbols: continue

        try:
            with open(user_file_path, 'r', encoding='utf-8') as f: content = f.read()
        except (IOError, UnicodeDecodeError): continue

        words_in_file = set(word_regex.findall(content))
        used_symbols = searchable_symbols.intersection(words_in_file)

        for symbol in used_symbols:
            definer_file_rel_path = all_symbol_definers.get(symbol)
            if not definer_file_rel_path or user_file_rel_path == definer_file_rel_path:
                continue

            path_parts = definer_file_rel_path.split(os.sep)
            target_level = overview['structure']
            try:
                for part in path_parts[:-1]:
                    target_level = target_level['subdirs'][part]
                target_file = target_level['files'][path_parts[-1]]

                for element_type in ['functions', 'classes']:
                    if symbol in target_file.get(element_type, {}):
                        element = target_file[element_type][symbol]
                        used_in_list = element.setdefault('used_in', [])
                        if user_file_rel_path not in used_in_list:
                             used_in_list.append(user_file_rel_path)
            except KeyError:
                continue
    
    return {'summary': project_summary, **overview}

def generate_simple_overview(detailed_overview):
    def simplify_level(level):
        simple_node = {}
        if level.get('files'):
            simple_node['files'] = list(level['files'].keys())
        if level.get('subdirs'):
            simple_node['subdirs'] = {name: simplify_level(subdir) for name, subdir in level['subdirs'].items()}
        return simple_node
    return simplify_level(detailed_overview['structure'])

def print_summary(summary):
    """Prints a formatted summary of the project analysis to the console."""
    print("\n--- Project Summary ---")
    print(f"  Total Files Analyzed: {summary['total_files']:,}")
    print(f"  Total Lines of Code:  {summary['total_lines']:,}")
    print(f"  Total Size:           {summary['total_size_bytes'] / 1024:.2f} KB")
    
    print("\n  Code Breakdown by Language:")
    for lang, stats in sorted(summary['by_language'].items()):
        print(f"    - {lang.capitalize():<12} {stats['files']:>4} files, {stats['lines']:>7,} lines")
        
    print("\n  Code Structure:")
    print(f"    - Functions Found:    {summary['total_functions']:,}")
    print(f"    - Classes Found:      {summary['total_classes']:,}")
    
    print("\n  Code Quality:")
    print(f"    - Linter Issues Found: {summary['linter_errors']:,} (ignoring unused imports for Python)")
    print("-----------------------")

def main():
    start_time = time.time()
    print("Starting project analysis...")
    
    detailed_overview = analyze_project('.')
    
    if not os.path.exists('.context'):
        os.makedirs('.context')
        
    detailed_path = '.context/project_overview_detailed.json'
    with open(detailed_path, 'w') as f:
        json.dump(detailed_overview, f, indent=2)
    
    simple_overview = generate_simple_overview(detailed_overview)
    simple_path = '.context/project_overview.json'
    with open(simple_path, 'w') as f:
        json.dump(simple_overview, f, indent=2)

    # Print the summary to the console before finishing
    if 'summary' in detailed_overview:
        print_summary(detailed_overview['summary'])

    end_time = time.time()
    print("\n=== Project Analysis Complete! ===")
    print(f"Total time taken: {end_time - start_time:.2f} seconds")
    print(f"Detailed analysis saved to: {detailed_path}")
    print(f"Simple file structure saved to: {simple_path}")

if __name__ == "__main__":
    main()
