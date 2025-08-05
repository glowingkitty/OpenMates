#!/usr/bin/env python3
import subprocess
import argparse
from datetime import datetime

def get_uncommitted_changes():
    """Get all uncommitted changes in the repository."""
    # Get staged and unstaged changes
    try:
        # Show modified files
        files_output = subprocess.check_output(
            ["git", "status", "-s"], 
            universal_newlines=True
        )
        
        # Get detailed diff
        diff_output = subprocess.check_output(
            ["git", "diff", "HEAD"], 
            universal_newlines=True
        )
        
        return files_output, diff_output
    except subprocess.CalledProcessError as e:
        print(f"Error getting uncommitted changes: {e}")
        return "", ""

def get_commit_changes(num_commits):
    """Get changes from the last N commits."""
    commits = []
    
    try:
        # Get the last N commit hashes
        commit_hashes = subprocess.check_output(
            ["git", "log", "--pretty=format:%H", f"-{num_commits}"],
            universal_newlines=True
        ).splitlines()
        
        for i, commit_hash in enumerate(commit_hashes):
            if i < len(commit_hashes) - 1:
                # Get commit message
                commit_msg = subprocess.check_output(
                    ["git", "log", "--format=%B", "-n", "1", commit_hash],
                    universal_newlines=True
                ).strip()
                
                # Get files changed
                files_changed = subprocess.check_output(
                    ["git", "show", "--name-status", "--format=", commit_hash],
                    universal_newlines=True
                ).strip()
                
                # Get detailed diff
                diff = subprocess.check_output(
                    ["git", "show", commit_hash],
                    universal_newlines=True
                )
                
                commits.append({
                    "hash": commit_hash,
                    "message": commit_msg,
                    "files": files_changed,
                    "diff": diff
                })
    except subprocess.CalledProcessError as e:
        print(f"Error getting commit history: {e}")
    
    return commits

def generate_markdown(files_output, diff_output, commits=None):
    """Generate markdown content with the changes."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    markdown = f"# Code Changes Report\n\nGenerated: {now}\n\n"
    
    # Uncommitted changes
    markdown += "## Uncommitted Changes\n\n"
    
    if files_output.strip():
        markdown += "### Modified Files\n\n"
        markdown += "```\n" + files_output + "```\n\n"
    else:
        markdown += "No uncommitted changes found.\n\n"
    
    if diff_output.strip():
        markdown += "### Diff\n\n"
        markdown += "```diff\n" + diff_output + "```\n\n"
    
    # Commit history changes if requested
    if commits:
        markdown += "## Recent Commits\n\n"
        
        for commit in commits:
            markdown += f"### Commit: {commit['hash'][:7]}\n\n"
            markdown += f"**Message:** {commit['message']}\n\n"
            
            markdown += "**Files Changed:**\n\n"
            markdown += "```\n" + commit['files'] + "```\n\n"
            
            markdown += "**Diff:**\n\n"
            markdown += "```diff\n" + commit['diff'] + "```\n\n"
    
    return markdown

def main():
    parser = argparse.ArgumentParser(description='Generate a markdown report of code changes.')
    parser.add_argument('-lastcommits', type=int, help='Include changes from the last N commits')
    parser.add_argument('-o', '--output', default='changes_report.md', help='Output markdown file')
    
    args = parser.parse_args()
    
    # Get uncommitted changes
    files_output, diff_output = get_uncommitted_changes()
    
    # Get commit history if requested
    commits = None
    if args.lastcommits:
        commits = get_commit_changes(args.lastcommits)
    
    # Generate markdown
    markdown = generate_markdown(files_output, diff_output, commits)
    
    # Write to file
    with open(args.output, 'w') as f:
        f.write(markdown)
    
    print(f"Report generated: {args.output}")

if __name__ == "__main__":
    main()