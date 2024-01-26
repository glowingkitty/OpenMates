################
# Default Imports
################
import sys
import os
import re
import requests

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('skills.*', '', full_current_path)
sys.path.append(main_directory)
from server import *

################

from server.setup.save_profile_details import save_profile_details

def delete_github_repo(owner_name: str, repo_name: str) -> dict:
    """
    Deletes a repository on GitHub.

    Args:
        owner_name (str): The owner of the repository.
        repo_name (str): Name of the repository to delete.

    Returns:
        dict: The response from GitHub API.
    """
    try:
        add_to_log(module_name="GitHub", color="blue", state="start")
        add_to_log(f"Deleting the GitHub repository: {repo_name}...")

        secrets = load_secrets()
        profile_details = load_profile_details()

        # check if the repository is managed by the AI
        allowed_to_delete = False
        for repo in profile_details.get('ai_managed_git_repos', []):
            if repo.get('owner_name') == owner_name and repo.get('repo_name') == repo_name:
                allowed_to_delete = True
        
        if not allowed_to_delete:
            add_to_log(f"Deleting the repository '{repo_name}' is not allowed, since it's not managed by the AI.", state="error")
            return False

        url = f"https://api.github.com/repos/{owner_name}/{repo_name}"
        headers = {
            "Authorization": f"token {secrets['GITHUB_TOKEN']}",
            "Accept": "application/vnd.github.v3+json",
        }
        response = requests.delete(url, headers=headers)
        if response.status_code == 204:
            add_to_log(f"Successfully deleted the repository: {repo_name}", state="success")

            # remove repo from profile details
            profile_details = load_profile_details()
            if "ai_managed_git_repos" in profile_details:
                for repo in profile_details["ai_managed_git_repos"]:
                    if repo["owner_name"] == owner_name and repo["repo_name"] == repo_name:
                        profile_details["ai_managed_git_repos"].remove(repo)
                        break
                save_profile_details(profile_details)

            return True
        else:
            add_to_log(f"Failed to delete the repository. Status code: {response.status_code}", state="error")
            return False

    except KeyboardInterrupt:
        shutdown()

    except Exception as e:
        process_error(f"Failed to delete GitHub repository '{repo_name}'", traceback=traceback.format_exc())
        return False

if __name__ == "__main__":
    owner_name = ""
    repo_name = "NewRepository"
    response = delete_github_repo(owner_name, repo_name)
    print(response)