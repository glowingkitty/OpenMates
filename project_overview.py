import tree_sitter_python as tspython
import tree_sitter_typescript as tstype
import tree_sitter_javascript as tsjs
import pathspec
import subprocess
import re
import os
import json
import time
import sys
import requests
from datetime import datetime
from collections import defaultdict
from typing import Dict, List, Optional, Any, Tuple
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

# --- GitHub Issues Report Generation ---

class GitHubIssuesReport:
    def __init__(self, owner: str, repo: str, token: Optional[str] = None, delay: float = 0.1):
        """
        Initialize the GitHub Issues Report Generator.
        
        Args:
            owner: GitHub repository owner/organization
            repo: GitHub repository name
            token: GitHub personal access token (optional but recommended to avoid rate limits)
            delay: Delay between API requests in seconds to avoid rate limits
        """
        self.owner = owner
        self.repo = repo
        self.base_url = f"https://api.github.com/repos/{owner}/{repo}"
        self.headers = {
            "Accept": "application/vnd.github.v3+json"
        }
        
        # Add token to headers if provided
        if token:
            self.headers["Authorization"] = f"Bearer {token}"
            
        # Delay between requests to avoid rate limits
        self.delay = delay
        
        # Store rate limit information
        self.rate_limit_remaining = None
        self.rate_limit_reset = None
        
        # Store for milestones and issues
        self.milestones = []
        self.issues_by_milestone = defaultdict(list)
        self.issues_without_milestone = []

    def _make_request(self, url: str, params: Dict = None) -> Tuple[int, Any]:
        """
        Make a request to the GitHub API with rate limit handling.
        
        Args:
            url: The URL to request
            params: Query parameters
            
        Returns:
            Tuple of (status_code, response_json)
        """
        # Check if we need to wait for rate limit reset
        if self.rate_limit_remaining is not None and self.rate_limit_remaining < 5:
            current_time = time.time()
            if self.rate_limit_reset > current_time:
                wait_time = self.rate_limit_reset - current_time + 1
                print(f"Rate limit almost exhausted. Waiting for {wait_time:.1f} seconds...")
                time.sleep(wait_time)
        
        # Make the request
        response = requests.get(url, headers=self.headers, params=params)
        
        # Update rate limit information
        if 'X-RateLimit-Remaining' in response.headers:
            self.rate_limit_remaining = int(response.headers['X-RateLimit-Remaining'])
            self.rate_limit_reset = int(response.headers['X-RateLimit-Reset'])
            
        # Handle rate limiting
        if response.status_code == 403 and 'X-RateLimit-Remaining' in response.headers and int(response.headers['X-RateLimit-Remaining']) == 0:
            reset_time = int(response.headers['X-RateLimit-Reset'])
            wait_time = reset_time - time.time() + 1
            
            if wait_time > 0 and wait_time < 3600:  # Only wait if less than an hour
                print(f"Rate limit exceeded. Waiting for {wait_time:.1f} seconds...")
                time.sleep(wait_time)
                # Retry the request
                return self._make_request(url, params)
        
        # Add delay between requests only if we're not using a token or if explicitly set
        if not self.headers.get("Authorization") or self.delay > 0:
            time.sleep(self.delay)
        
        return response.status_code, response.json() if response.status_code != 204 else None

    def fetch_milestones(self) -> None:
        """Fetch all milestones from the repository."""
        url = f"{self.base_url}/milestones"
        params = {"state": "all", "per_page": 100}
        
        all_milestones = []
        page = 1
        
        while True:
            params["page"] = page
            status_code, response_json = self._make_request(url, params)
            
            if status_code != 200:
                print(f"Error fetching milestones: {status_code}")
                print(response_json)
                sys.exit(1)
                
            all_milestones.extend(response_json)
            
            # Check if we've reached the last page
            if len(response_json) < params["per_page"]:
                break
                
            page += 1
        
        # Sort milestones by due date (closest first)
        def get_due_date(milestone):
            if milestone["due_on"]:
                return datetime.strptime(milestone["due_on"], "%Y-%m-%dT%H:%M:%SZ")
            return datetime.max  # Put milestones without due dates at the end
        
        self.milestones = sorted(all_milestones, key=get_due_date)
        
        print(f"Fetched {len(self.milestones)} milestones")

    def fetch_issues(self) -> None:
        """Fetch all issues from the repository."""
        url = f"{self.base_url}/issues"
        params = {"state": "open", "per_page": 100}
        
        all_issues = []
        page = 1
        
        while True:
            params["page"] = page
            status_code, response_json = self._make_request(url, params)
            
            if status_code != 200:
                print(f"Error fetching issues: {status_code}")
                print(response_json)
                sys.exit(1)
                
            all_issues.extend(response_json)
            
            # Check if we've reached the last page
            if len(response_json) < params["per_page"]:
                break
                
            page += 1
        
        print(f"Fetched {len(all_issues)} issues")
        
        # Group issues by milestone
        for issue in all_issues:
            # Skip pull requests
            if "pull_request" in issue:
                continue
                
            if issue["milestone"]:
                milestone_id = issue["milestone"]["id"]
                self.issues_by_milestone[milestone_id].append(issue)
            else:
                self.issues_without_milestone.append(issue)

    def fetch_comments_for_issue(self, issue_number: int) -> List[Dict[str, Any]]:
        """
        Fetch all comments for a specific issue.
        
        Args:
            issue_number: The issue number
            
        Returns:
            List of comment objects
        """
        url = f"{self.base_url}/issues/{issue_number}/comments"
        params = {"per_page": 100}
        
        all_comments = []
        page = 1
        max_retries = 3
        
        try:
            while True:
                params["page"] = page
                retry_count = 0
                
                while retry_count < max_retries:
                    status_code, response_json = self._make_request(url, params)
                    
                    if status_code == 200:
                        break
                    elif status_code == 403 or status_code == 429:
                        # Rate limit exceeded, try to wait and retry
                        if 'X-RateLimit-Reset' in response_json and retry_count < max_retries - 1:
                            reset_time = int(response_json['X-RateLimit-Reset'])
                            wait_time = reset_time - time.time() + 1
                            
                            if wait_time > 0 and wait_time < 300:  # Only wait if less than 5 minutes
                                print(f"Rate limit reached for issue #{issue_number}. Waiting {wait_time:.1f} seconds...")
                                time.sleep(wait_time)
                                retry_count += 1
                                continue
                        
                        # If we can't wait or have retried too many times, return what we have
                        print(f"Rate limit reached when fetching comments for issue #{issue_number}: {status_code}")
                        return all_comments
                    else:
                        print(f"Error fetching comments for issue #{issue_number}: {status_code}")
                        return all_comments
                
                # If we've exhausted retries without success
                if retry_count >= max_retries:
                    print(f"Max retries reached for issue #{issue_number}. Returning partial results.")
                    return all_comments
                
                all_comments.extend(response_json)
                
                # Check if we've reached the last page
                if len(response_json) < params["per_page"]:
                    break
                    
                page += 1
                
        except Exception as e:
            print(f"Exception when fetching comments for issue #{issue_number}: {str(e)}")
            return all_comments
        
        return all_comments

    def generate_markdown(self, output_file: str = "github_issues_report.md") -> None:
        """
        Generate a markdown file with all issues sorted by milestones.
        
        Args:
            output_file: Path to the output markdown file
        """
        # Count total number of issues (excluding PRs)
        total_issues = sum(len(issues) for issues in self.issues_by_milestone.values()) + len(self.issues_without_milestone)
        
        # Get current time for both start and end of document
        generation_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(f"# GitHub Issues Report for {self.owner}/{self.repo}\n\n")
            f.write(f"Generated on: {generation_time}\n\n")
            f.write(f"**Total open issues: {total_issues}**\n\n")
            
            # Write issues grouped by milestones
            f.write("## Issues by Milestone\n\n")
            
            # First, write issues with milestones (sorted by due date)
            for milestone in self.milestones:
                milestone_id = milestone["id"]
                milestone_title = milestone["title"]
                due_date = "No due date"
                
                if milestone["due_on"]:
                    due_date = datetime.strptime(
                        milestone["due_on"], "%Y-%m-%dT%H:%M:%SZ"
                    ).strftime("%Y-%m-%d")
                
                issues = self.issues_by_milestone.get(milestone_id, [])
                
                if not issues:
                    continue
                
                f.write(f"### Milestone: {milestone_title} (Due: {due_date})\n\n")
                f.write(f"Description: {milestone['description'] or 'No description'}\n\n")
                
                for issue in issues:
                    self._write_issue_details(f, issue)
            
            # Then, write issues without milestones
            if self.issues_without_milestone:
                f.write("### Issues without Milestone\n\n")
                
                for issue in self.issues_without_milestone:
                    self._write_issue_details(f, issue)
            
            # Add last updated date at the end
            f.write(f"\n\n---\n\nLast updated: {generation_time}\n")
        
        print(f"Markdown report generated: {output_file}")
        print(f"Total open issues processed: {total_issues}")

    def _write_issue_details(self, file, issue: Dict[str, Any]) -> None:
        """
        Write details of a single issue to the markdown file.
        
        Args:
            file: File object to write to
            issue: Issue object
        """
        issue_number = issue["number"]
        issue_title = issue["title"]
        issue_state = issue["state"]
        issue_created_at = datetime.strptime(
            issue["created_at"], "%Y-%m-%dT%H:%M:%SZ"
        ).strftime("%Y-%m-%d")
        
        # Write issue header
        file.write(f"#### [{issue_number}] {issue_title} ({issue_state})\n\n")
        file.write(f"Created on: {issue_created_at} by @{issue['user']['login']}\n\n")
        
        # Write issue body only if it exists
        if issue["body"]:
            file.write("**Description:**\n\n")
            file.write(f"{issue['body']}\n\n")
        
        # Fetch and write comments
        comments = self.fetch_comments_for_issue(issue_number)
        
        if comments:
            file.write(f"**Comments ({len(comments)}):**\n\n")
            
            for comment in comments:
                comment_author = comment["user"]["login"]
                comment_date = datetime.strptime(
                    comment["created_at"], "%Y-%m-%dT%H:%M:%SZ"
                ).strftime("%Y-%m-%d %H:%M:%S")
                
                file.write(f"*Comment by @{comment_author} on {comment_date}:*\n\n")
                file.write(f"{comment['body']}\n\n")
        # No "No comments" text if there are no comments
        
        file.write("---\n\n")

def generate_github_issues_report(owner: str, repo: str, token: Optional[str] = None, output_file: str = None) -> None:
    """
    Generate a GitHub issues report for the specified repository.
    
    Args:
        owner: GitHub repository owner/organization
        repo: GitHub repository name
        token: GitHub personal access token (optional but recommended to avoid rate limits)
        output_file: Path to the output markdown file (optional)
    """
    if not output_file:
        # Ensure .tempcontext directory exists
        if not os.path.exists('.tempcontext'):
            os.makedirs('.tempcontext')
        output_file = '.tempcontext/github_issues_report.md'
    
    delay = 0.1 if token else 1.0  # Lower delay with token
    
    if not token:
        print("\n" + "="*80)
        print("WARNING: No GitHub token provided. You will likely encounter rate limits.")
        print("To set a GitHub token:")
        print("  1. Create a token at: https://github.com/settings/tokens")
        print("     - For public repos: select 'public_repo' scope")
        print("     - For private repos: select 'repo' scope")
        print("  2. Provide the token as an environment variable:")
        print("     Linux/macOS: export GITHUB_TOKEN=YOUR_TOKEN_HERE")
        print("     Windows:     set GITHUB_TOKEN=YOUR_TOKEN_HERE")
        print("="*80 + "\n")
    
    # Create report generator
    report = GitHubIssuesReport(owner, repo, token, delay)
    
    print(f"Generating issues report for {owner}/{repo}...")
    
    # Fetch data and generate report
    report.fetch_milestones()
    report.fetch_issues()
    report.generate_markdown(output_file)
    
    print(f"GitHub issues report generated: {output_file}")

def main():
    start_time = time.time()
    print("Starting project analysis...")
    
    detailed_overview = analyze_project('.')
    
    if not os.path.exists('.tempcontext'):
        os.makedirs('.tempcontext')
        
    detailed_path = '.tempcontext/project_overview_detailed.json'
    with open(detailed_path, 'w') as f:
        json.dump(detailed_overview, f, indent=2)
    
    simple_overview = generate_simple_overview(detailed_overview)
    simple_path = '.tempcontext/project_overview.json'
    with open(simple_path, 'w') as f:
        json.dump(simple_overview, f, indent=2)

    # Print the summary to the console before finishing
    if 'summary' in detailed_overview:
        print_summary(detailed_overview['summary'])
    
    # Check if GitHub repository information is available in environment variables
    github_owner = os.environ.get("GITHUB_OWNER")
    github_repo = os.environ.get("GITHUB_REPO")
    github_token = os.environ.get("GITHUB_TOKEN")
    
    # Generate GitHub issues report if repository information is available
    if github_owner and github_repo:
        print("\nGenerating GitHub issues report...")
        generate_github_issues_report(github_owner, github_repo, github_token)

    end_time = time.time()
    print("\n=== Project Analysis Complete! ===")
    print(f"Total time taken: {end_time - start_time:.2f} seconds")
    print(f"Detailed analysis saved to: {detailed_path}")
    print(f"Simple file structure saved to: {simple_path}")

if __name__ == "__main__":
    main()
