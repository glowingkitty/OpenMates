import os
import re
from typing import List, Dict


def load_markdown_file(file_path: str) -> str:
    """
    Load the content of a markdown file.

    Args:
        file_path (str): The path to the markdown file.

    Returns:
        str: The content of the markdown file.

    Raises:
        FileNotFoundError: If the file is not found.
        IOError: If there's an error reading the file.
    """
    try:
        # Get the directory of add_api_endpoint.py
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        # Construct the full path to the markdown file
        full_path = os.path.join(base_dir, file_path)

        with open(full_path, 'r', encoding='utf-8') as file:
            content = file.read()
        return content
    except FileNotFoundError:
        raise FileNotFoundError(f"The file {file_path} was not found.")
    except IOError as e:
        raise IOError(f"Error reading the file {file_path}: {str(e)}")


def extract_numbered_list_items(content: str) -> List[str]:
    """
    Extract numbered list items from the content.

    Args:
        content (str): The content to parse.

    Returns:
        List[str]: A list of numbered list items.
    """
    pattern = r'^\d+\.\s+(.+)$'
    items = re.findall(pattern, content, re.MULTILINE)
    return items


def extract_linked_filepaths(content: str) -> List[str]:
    """
    Extract linked file paths from markdown content.

    Args:
        content (str): The markdown content to parse.

    Returns:
        List[str]: A list of file paths extracted from the content.
    """
    # Regular expression to match markdown links with file paths
    # This pattern looks for [text](file_path.ext) or [text](./file_path.ext) or [text](../file_path.ext)
    pattern = r'\[([^\]]+)\]\((\.{0,2}/[^)]+\.\w+)\)'

    # Find all matches in the content
    matches = re.findall(pattern, content)

    # Extract just the file paths (second group in each match)
    file_paths = [match[1] for match in matches]

    # Remove any duplicate paths
    unique_file_paths = list(set(file_paths))

    return unique_file_paths


def load_linked_files(filepaths: List[str]) -> Dict[str, str]:
    """
    Load the content of linked files.

    Args:
        filepaths (List[str]): A list of file paths to load.

    Returns:
        Dict[str, str]: A dictionary where keys are file paths and values are file contents.
    """
    linked_files_content = {}
    for filepath in filepaths:
        try:
            content = load_markdown_file(filepath)
            linked_files_content[filepath] = content
        except (FileNotFoundError, IOError) as e:
            print(f"Warning: Could not load file {filepath}. Error: {str(e)}")

    return linked_files_content