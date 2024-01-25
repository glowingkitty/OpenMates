import subprocess
import os

def generate_markdown_list_of_changed_files():
    # Get the list of changed files
    changed_files = subprocess.check_output(['git', 'diff', '--name-only', 'HEAD']).decode().splitlines()

    # Create or clear the markdown file
    markdown_file = 'CHANGED_FILES.md'
    with open(markdown_file, 'w') as md_file:
        md_file.write('# List of Changed Files\n\n')

    # Append the changed files and their content to the markdown file
    for file in changed_files:
        if file and os.path.isfile(file):
            with open(markdown_file, 'a') as md_file:
                md_file.write(f'## {file}\n\n')
                with open(file, 'r') as content_file:
                    file_content = content_file.read()
                    md_file.write('```' + os.path.splitext(file)[1][1:] + '\n')
                    md_file.write(file_content + '\n```\n\n')

    # Stage the markdown file
    subprocess.run(['git', 'add', markdown_file])

if __name__ == '__main__':
    generate_markdown_list_of_changed_files()