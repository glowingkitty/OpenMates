import os
import re
from typing import Dict, List

class FileProcessor:
    def __init__(self):
        self.created_files = []
        self.updated_files = []

    def process_llm_response(self, response: Dict):
        """
        Process the LLM response and create or modify files accordingly.

        Args:
            response (Dict): The response from the LLM containing file changes.
        """
        for file_info in response.get("files", []):
            file_path = file_info.get("path")
            action = file_info.get("action")

            if action == "new_file":
                content = file_info.get("full_content", "")
                self.create_or_update_file(file_path, content)
            elif action == "update_add":
                self.update_file(file_path, file_info)

    def create_or_update_file(self, file_path: str, content: str):
        directory = os.path.dirname(file_path)
        if not os.path.exists(directory):
            os.makedirs(directory)

        is_new_file = not os.path.exists(file_path)
        with open(file_path, "w") as file:
            file.write(content)
        
        if is_new_file:
            print(f"Created file: {file_path}")
            self.created_files.append(file_path)
        else:
            print(f"Updated file: {file_path}")
            self.updated_files.append(file_path)

    def update_file(self, file_path: str, file_info: Dict):
        if not os.path.exists(file_path):
            print(f"Warning: File not found for modification: {file_path}")
            return

        with open(file_path, "r") as file:
            content = file.read()

        reference_snippet = file_info.get("reference_snippet")
        position = file_info.get("position")
        new_content = file_info.get("snippet_new")

        updated_content = self._update_content(content, reference_snippet, position, new_content)

        if updated_content != content:
            with open(file_path, "w") as file:
                file.write(updated_content)
            print(f"Modified file: {file_path}")
            self.updated_files.append(file_path)
        else:
            print(f"Warning: Reference snippet not found in file: {file_path}")

    def _update_content(self, content: str, reference_snippet: str, position: str, new_content: str) -> str:
        if reference_snippet in content:
            if position == "before":
                return content.replace(reference_snippet, f"{new_content}\n{reference_snippet}")
            elif position == "after":
                return content.replace(reference_snippet, f"{reference_snippet}\n{new_content}")
        return content

    def apply_changes(self, original_content: str, changes: Dict[str, str]) -> str:
        """
        Apply changes to the original content.

        Args:
            original_content (str): The original file content.
            changes (Dict[str, str]): A dictionary of changes to apply.

        Returns:
            str: The modified content.
        """
        # This is a simplified implementation. You might need a more sophisticated
        # approach depending on how your LLM specifies changes.
        modified_content = original_content
        for location, new_content in changes.items():
            modified_content = modified_content.replace(location, new_content)
        return modified_content

    def get_created_files(self) -> List[str]:
        return list(set(self.created_files))

    def get_updated_files(self) -> List[str]:
        return list(set(self.updated_files))
