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

def git_pull_glowos():
    try:
        # Get the full path of the current file
        full_current_path = os.path.realpath(__file__)

        # Replace "OpenMates" and everything that follows with "GlowOS"
        glowos_dir = re.sub('OpenMates.*', 'GlowOS', full_current_path)

        if not os.path.exists(glowos_dir):
            raise Exception(glowos_dir+" not found")

        # Pull the changes from the remote repository
        pull_result = subprocess.run(['git', 'pull', 'origin', 'glowos'], cwd=glowos_dir, capture_output=True)
        if pull_result.returncode != 0:
            print(f'Error pulling changes from remote repository: {pull_result.stderr.decode()}')
            return
        else:
            print(f'Changes pulled from GlowOS repository (branch: glowos)')


    except Exception:
        process_error(f"While pulling changes from the GlowOS repository", traceback=traceback.format_exc())


if __name__ == "__main__":
    git_pull_glowos()