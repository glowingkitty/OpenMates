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


def create_github_repo(repo_name: str, private: bool = True, description: str = "") -> dict:
    """
    Creates a new repository on GitHub.

    Args:
        repo_name (str): Name of the repository to create.
        private (bool, optional): Whether the repository should be private. Defaults to True.
        description (str, optional): A short description of the repository. Defaults to "".

    Returns:
        dict: The response from GitHub API.
    """
    try:
        add_to_log(module_name="GitHub", color="blue", state="start")
        add_to_log("Creating a new GitHub repository...")

        secrets = load_secrets()

        url = "https://api.github.com/user/repos"
        headers = {
            "Authorization": f"token {secrets['GITHUB_TOKEN']}",
            "Accept": "application/vnd.github.v3+json",
        }
        data = {
            "name": repo_name,
            "private": private,
            "description": description,
        }
        response = requests.post(url, headers=headers, json=data)
        if response.status_code == 201:
            add_to_log(f"Successfully created the repository: {repo_name}", state="success")
            response_json = response.json()

            created_repo = {
                "id": response_json["id"],
                "owner_name": response_json["owner"]["login"],
                "repo_name": response_json["name"],
                "description": response_json["description"],
                "private": response_json["private"],
                "url": response_json["html_url"]
            }

            # add repo to profile details
            profile_details = load_profile_details()
            if "ai_managed_git_repos" not in profile_details:
                profile_details["ai_managed_git_repos"] = []

            profile_details["ai_managed_git_repos"].append(created_repo)
            save_profile_details(profile_details)

            return created_repo
        else:
            add_to_log(f"Failed to create the repository. Status code: {response.status_code}", state="error")
            return None

    except KeyboardInterrupt:
        shutdown()

    except Exception as e:
        process_error(f"Failed to create GitHub repository '{repo_name}'", traceback=traceback.format_exc())
        return {"error": str(e)}

if __name__ == "__main__":
    repo_name = "NewRepository"
    private = True
    description = "This is a new repository created via the GitHub API."
    response = create_github_repo(repo_name, private, description)
    print(response)