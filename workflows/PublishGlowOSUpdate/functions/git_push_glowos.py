import subprocess
import os
import re
import traceback
import sys
import os
import re


# fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('workflows.*', '', full_current_path)
sys.path.append(main_directory)

from server.error.process_error import process_error

def git_push_glowos(commit_message):
    try:
        # Get the full path of the current file
        full_current_path = os.path.realpath(__file__)

        # Replace "OpenMates" and everything that follows with "GlowOS"
        glowos_dir = re.sub('OpenMates.*', 'GlowOS', full_current_path)

        if not os.path.exists(glowos_dir):
            raise Exception(glowos_dir+" not found")
        
        # Add the manifest folder and devices.json to the staging area
        add_result = subprocess.run(['git', 'add', 'usermods/GlowOS/releases.json'], cwd=glowos_dir, capture_output=True)
        if add_result.returncode != 0:
            raise Exception (f'Error adding changes to the staging area: {add_result.stderr.decode()}')
        
        # Commit the changes with the specified message
        commit_result = subprocess.run(['git', 'commit', '-m', commit_message], cwd=glowos_dir, capture_output=True)
        if commit_result.returncode != 0:
            raise Exception(f'Error committing changes: {commit_result.stderr.decode()}')
        
        # Push the changes to the remote repository
        push_result = subprocess.run(['git', 'push', 'origin', 'glowos'], cwd=glowos_dir, capture_output=True)
        if push_result.returncode != 0:
            raise Exception(f'Error pushing changes to remote repository: {push_result.stderr.decode()}')
        else:
            print(f'Changes pushed to GlowOS repository (branch: glowos)')
    
    except Exception:
        process_error(f"While pushing changes to the GlowOS repository", traceback=traceback.format_exc())


if __name__ == "__main__":
    git_push_glowos("Just a test")