# backend/apps/ai/utils/instruction_loader.py
# Utilities for loading instruction files for the AI App.

import logging
import yaml
import os

logger = logging.getLogger(__name__)

# Determine the AI app's directory to locate base_instructions.yml
# __file__ in this context is backend/apps/ai/utils/instruction_loader.py
# So, os.path.dirname(__file__) is backend/apps/ai/utils
# And os.path.dirname(os.path.dirname(__file__)) is backend/apps/ai
AI_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE_INSTRUCTIONS_PATH = os.path.join(AI_APP_DIR, "base_instructions.yml")

def load_base_instructions() -> dict:
    """
    Loads the base_instructions.yml file from the AI app's directory.

    Returns:
        dict: The parsed content of base_instructions.yml, or an empty dict if loading fails.
    """
    if not os.path.exists(BASE_INSTRUCTIONS_PATH):
        logger.error(f"Base instructions file not found at {BASE_INSTRUCTIONS_PATH}")
        return {}
    try:
        with open(BASE_INSTRUCTIONS_PATH, 'r', encoding='utf-8') as f:
            instructions = yaml.safe_load(f)
        if not instructions:
            logger.error(f"Failed to load or parse {BASE_INSTRUCTIONS_PATH}. File might be empty or malformed.")
            return {}
        logger.info(f"Successfully loaded base instructions from {BASE_INSTRUCTIONS_PATH}")
        return instructions
    except FileNotFoundError: # Should be caught by os.path.exists, but as a safeguard
        logger.error(f"{BASE_INSTRUCTIONS_PATH} not found (safeguard).")
        return {}
    except yaml.YAMLError as e:
        logger.error(f"Error parsing YAML from {BASE_INSTRUCTIONS_PATH}: {e}")
        return {}
    except Exception as e:
        logger.error(f"An unexpected error occurred while loading {BASE_INSTRUCTIONS_PATH}: {e}", exc_info=True)
        return {}

if __name__ == '__main__':
    # Example of how to use the loader
    logging.basicConfig(level=logging.INFO)
    loaded_instructions = load_base_instructions()
    if loaded_instructions:
        logger.info("Instructions loaded successfully.")
        preprocess_tool = loaded_instructions.get("preprocess_request_tool")
        if preprocess_tool:
            logger.info(f"Preprocess tool name: {preprocess_tool.get('function', {}).get('name')}")
        else:
            logger.warning("Preprocess_request_tool not found in loaded instructions.")
    else:
        logger.error("Failed to load instructions.")