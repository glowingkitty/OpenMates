from typing import List

def generate_file_links(modified_files: List[str]) -> List[str]:
    """
    Generate a list of file links for the user to check.

    Args:
        modified_files (List[str]): A list of files that were created or modified.

    Returns:
        List[str]: A list of file links.
    """
    return [f"file://{file_path}" for file_path in modified_files]