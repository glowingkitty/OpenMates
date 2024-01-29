################
# Default Imports
################
import sys
import os
import re

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('OpenMates.*', '', full_current_path)
sys.path.append(main_directory)

from server import *
################

from skills.intelligence.costs.count_tokens import count_tokens

import os
import ast
import json



def should_ignore(path, ignore_folders, ignore_files):
    for folder in ignore_folders:
        if f"/{folder}/" in path or path.endswith(f"/{folder}"):
            return True
    for file in ignore_files:
        if path.endswith(file):
            return True
    return False

def get_func_defs(file_path):
    try:
        with open(file_path, 'r') as file:
            tree = ast.parse(file.read())
    except SyntaxError:
        print(f"Skipping file due to SyntaxError: {file_path}")
        return []
    functions = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            func_name = node.name
            args = []
            for arg in node.args.args:
                arg_name = arg.arg
                arg_type = ast.unparse(arg.annotation) if arg.annotation else None
                args.append(f"{arg_name}: {arg_type}" if arg_type else arg_name)
            return_type = ast.unparse(node.returns) if node.returns else None
            func_def = f"def {func_name}({', '.join(args)})"
            if return_type:
                func_def += f" -> {return_type}"
            functions.append(func_def)
    return functions



def create_tree_structure(startpath, ignore_folders, ignore_files):
    token_counts = {'files': {}, 'folders': {}, 'total': 0}
    with open('tree_structure.md', 'w') as file:
        for root, dirs, files in os.walk(startpath):
            dirs[:] = [d for d in dirs if not should_ignore(os.path.join(root, d), ignore_folders, ignore_files)]
            level = root.replace(startpath, '').count(os.sep)
            indent = ' ' * 4 * (level - 1) + '├── ' if level > 0 else ''
            file.write(f"{indent}{os.path.basename(root)}/\n")
            subindent = ' ' * 4 * level + ('├── ' if files else '└── ')
            for i, f in enumerate(sorted(files)):
                if should_ignore(os.path.join(root, f), ignore_folders, ignore_files):
                    continue
                is_last = i == len(files) - 1
                file.write(f"{subindent if not is_last else subindent.replace('├', '└')}{f}\n")
                if f.endswith(('.py', '.txt', '.md', '.js', '.html', '.css')):
                    with open(os.path.join(root, f), 'r') as text_file:
                        tokens = count_tokens(text_file.read())
                        token_counts['files'][os.path.join(root, f)] = tokens
                        if root in token_counts['folders']:
                            token_counts['folders'][root] += tokens
                        else:
                            token_counts['folders'][root] = tokens
                        token_counts['total'] += tokens
                if f.endswith('.py'):
                    functions = get_func_defs(os.path.join(root, f))
                    func_indent = ' ' * 4 * (level + 1) + ('├── ' if functions else '└── ')
                    for j, func in enumerate(sorted(functions)):
                        is_last_func = j == len(functions) - 1
                        file.write(f"{func_indent if not is_last_func else func_indent.replace('├', '└')}{func}\n")
    with open('token_counts.json', 'w') as file:
        json.dump(token_counts, file, indent=4)

    with open('tree_structure.md', 'r') as md_file:
        md_content = md_file.read()
        tokens = count_tokens(md_content)
        token_counts['files']['tree_structure.md'] = tokens
        token_counts['total'] += tokens

    with open('token_counts.json', 'w') as file:
        json.dump(token_counts, file, indent=4)

def main():
    startpath = '.'  # Replace with the path to the directory you want to scan
    ignore_folders = ['secrets', 'venv', '__pycache__', 'temp_data',".git"]
    ignore_files = ['.env',"__init__.py",".DS_Store","readme.md","README.md","tree_structure.json"]
    create_tree_structure(startpath, ignore_folders, ignore_files)

if __name__ == "__main__":
    main()