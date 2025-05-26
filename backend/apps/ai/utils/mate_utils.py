# backend/apps/ai/utils/mate_utils.py
# Utility functions for loading and handling Mate configurations.

import logging
from typing import List, Dict, Any, Optional
import yaml
from pydantic import BaseModel, ValidationError, Field

logger = logging.getLogger(__name__)

class MateConfig(BaseModel):
    """
    Pydantic model for a single Mate's configuration.
    Matches the structure of entries in mates.yml.
    """
    id: str = Field(..., description="Unique identifier for the Mate.")
    name: str = Field(..., description="Human-readable name of the Mate.")
    category: str = Field(..., description="Category the Mate belongs to (e.g., 'general_knowledge', 'coding_assistance').")
    description: str = Field(..., description="A brief description of the Mate's purpose or expertise.")
    default_system_prompt: str = Field(..., description="The default system prompt for this Mate.")
    assigned_apps: Optional[List[str]] = Field(None, description="List of app IDs this Mate can use by default. If None or empty, interpretation might vary (e.g., access to no specific apps or all globally available apps, depending on system design).")

class MatesYAML(BaseModel):
    """
    Pydantic model for the entire mates.yml file structure.
    """
    mates: List[MateConfig]

DEFAULT_MATES_FILE_PATH = "backend/apps/ai/mates.yml"

def load_mates_config(mates_file_path: str = DEFAULT_MATES_FILE_PATH) -> List[MateConfig]:
    """
    Loads Mate configurations from the specified YAML file.

    Args:
        mates_file_path: Path to the mates.yml file.

    Returns:
        A list of MateConfig objects, or an empty list if loading fails.
    """
    try:
        with open(mates_file_path, 'r', encoding='utf-8') as f:
            raw_mates_data = yaml.safe_load(f)
        
        if not raw_mates_data or "mates" not in raw_mates_data:
            logger.error(f"Mates configuration file '{mates_file_path}' is empty or does not contain a 'mates' key.")
            return []

        # Validate the structure using Pydantic
        validated_data = MatesYAML(**raw_mates_data)
        logger.info(f"Successfully loaded and validated {len(validated_data.mates)} mates from '{mates_file_path}'.")
        return validated_data.mates
    except FileNotFoundError:
        logger.error(f"Mates configuration file not found at '{mates_file_path}'.")
        return []
    except yaml.YAMLError as e:
        logger.error(f"Error parsing YAML from '{mates_file_path}': {e}")
        return []
    except ValidationError as e:
        logger.error(f"Validation error for mates configuration in '{mates_file_path}': {e}")
        return []
    except Exception as e:
        logger.error(f"An unexpected error occurred while loading mates from '{mates_file_path}': {e}", exc_info=True)
        return []

if __name__ == '__main__':
    # Example usage for testing
    logging.basicConfig(level=logging.INFO)
    # Create a dummy mates.yml for testing if it doesn't exist
    dummy_mates_content = """
mates:
  - id: "general_expert_v1"
    name: "General Expert"
    category: "general_knowledge"
    description: "A knowledgeable assistant for general queries."
    default_system_prompt: "You are a helpful AI assistant."
  - id: "code_helper_py_v1"
    name: "Python Code Helper"
    category: "coding_assistance"
    description: "Helps with Python programming questions and tasks."
    default_system_prompt: "You are an expert Python programmer. Provide clear and concise code examples."
"""
    dummy_path = "dummy_mates.yml"
    try:
        with open(dummy_path, 'w', encoding='utf-8') as f:
            f.write(dummy_mates_content)
        
        loaded_mates = load_mates_config(dummy_path)
        if loaded_mates:
            logger.info(f"Loaded {len(loaded_mates)} mates successfully for testing:")
            for mate in loaded_mates:
                logger.info(f"  Mate ID: {mate.id}, Name: {mate.name}, Category: {mate.category}")
        else:
            logger.error("Failed to load mates for testing.")
            
    except Exception as e:
        logger.error(f"Error in test script: {e}")
    finally:
        import os
        if os.path.exists(dummy_path):
            os.remove(dummy_path)