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

def process_ruff_results(ruff_json_output, root_path):
    """
    Processes raw Ruff JSON to create dedicated lists for unused imports/variables,
    mimicking the simple output of the original script.
    """
    processed_findings = {}
    name_regex = re.compile(r"`(.+?)`")

    for error in ruff_json_output:
        # We only care about these specific codes for this function's purpose
        if error['code'] not in ['F401', 'F841']:
            continue

        file_path = os.path.relpath(error['filename'], root_path)
        file_findings = processed_findings.setdefault(file_path, {})
        
        match = name_regex.search(error['message'])
        if match:
            name = match.group(1)
            if error['code'] == 'F401': # Unused import
                file_findings.setdefault('unused_imports', []).append(name)
            elif error['code'] == 'F841': # Unused local variable
                file_findings.setdefault('unused_variables', []).append(name)

    return processed_findings

def run_ruff_on_project(root_path):
    """Runs Ruff once and returns processed, structured findings for specific issues."""
    print("Running Ruff on the entire project...")
    try:
        # Select only the codes we are interested in for this analysis
        command = ['ruff', 'check', root_path, '--select', 'F401,F841', '--output-format=json', '--exit-zero']
        result = subprocess.run(command, capture_output=True, text=True, check=True)
        ruff_errors = json.loads(result.stdout)
        
        processed = process_ruff_results(ruff_errors, root_path)
        print(f"Ruff found unused imports/variables in {len(processed)} files.")
        return processed
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"WARNING: Could not run Ruff. Skipping Python linting. Error: {e}")
        return {}

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

def load_gitignore_rules(root_path):
    gitignore_path = os.path.join(root_path, '.gitignore')
    if os.path.exists(gitignore_path):
        with open(gitignore_path, 'r') as f:
            return pathspec.PathSpec.from_lines('gitwildmatch', f)
    return None

def analyze_project(root_path):
    spec = load_gitignore_rules(root_path)
    
    # Pass 1: Collect files
    print("Pass 1: Finding all relevant files...")
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
    print(f"Found {len(all_files)} files to analyze.")

    # Pass 2: Run Ruff for specific unused code analysis
    print("\nPass 2: Running project-wide analysis for unused imports/variables...")
    ruff_results = run_ruff_on_project(root_path)

    # Pass 3: Analyze file structure and merge linter data
    print(f"\nPass 3: Analyzing {len(all_files)} files with tree-sitter...")
    overview = {'structure': {'files': {}, 'subdirs': {}}}
    symbol_maps = {'python': {}, 'typescript': {}, 'javascript': {}}
    file_lang_map = {}

    for file_path in all_files:
        rel_path = os.path.normpath(os.path.relpath(file_path, root_path))
        analysis = analyze_file_structure(file_path, rel_path)
        if not analysis: continue
        
        # Merge the pre-processed linter data
        if rel_path in ruff_results:
            analysis.update(ruff_results[rel_path])

        lang = analysis.get('type')
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
            definer_file_rel_path = all_symbol_definers[symbol]
            if user_file_rel_path == definer_file_rel_path: continue

            path_parts = definer_file_rel_path.split(os.sep)
            target_level = overview['structure']
            for part in path_parts[:-1]:
                target_level = target_level['subdirs'][part]
            target_file = target_level['files'][path_parts[-1]]

            for element_type in ['functions', 'classes']:
                if symbol in target_file.get(element_type, {}):
                    element = target_file[element_type][symbol]
                    used_in_list = element.setdefault('used_in', [])
                    if user_file_rel_path not in used_in_list:
                         used_in_list.append(user_file_rel_path)
    
    return overview

def generate_simple_overview(detailed_overview):
    def simplify_level(level):
        simple_node = {}
        if level.get('files'):
            simple_node['files'] = list(level['files'].keys())
        if level.get('subdirs'):
            simple_node['subdirs'] = {name: simplify_level(subdir) for name, subdir in level['subdirs'].items()}
        return simple_node
    return simplify_level(detailed_overview['structure'])

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

    end_time = time.time()
    print("\n=== Project Analysis Complete! ===")
    print(f"Total time taken: {end_time - start_time:.2f} seconds")
    print(f"Detailed analysis saved to: {detailed_path}")
    print(f"Simple file structure saved to: {simple_path}")

if __name__ == "__main__":
    main()