import os
from typing import Dict, List

class FileProcessor:
    def __init__(self):
        self.modified_files = []

    def process_llm_response(self, response: Dict):
        """
        Process the LLM response and create or modify files accordingly.

        Args:
            response (Dict): The response from the LLM containing file changes.
        """
        for file_path, content in response.get("files", {}).items():
            directory = os.path.dirname(file_path)
            if not os.path.exists(directory):
                os.makedirs(directory)

            with open(file_path, "w") as file:
                file.write(content)
            print(f"Created/Updated file: {file_path}")
            self.modified_files.append(file_path)

        for file_path, changes in response.get("modifications", {}).items():
            if os.path.exists(file_path):
                with open(file_path, "r") as file:
                    original_content = file.read()

                modified_content = self.apply_changes(original_content, changes)

                with open(file_path, "w") as file:
                    file.write(modified_content)
                print(f"Modified file: {file_path}")
                self.modified_files.append(file_path)
            else:
                print(f"Warning: File not found for modification: {file_path}")

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

    def get_modified_files(self) -> List[str]:
        """
        Get the list of files that were created or modified.

        Returns:
            List[str]: A list of file paths.
        """
        return self.modified_files