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
        logger.error(f"Base instructions file NOT FOUND at {BASE_INSTRUCTIONS_PATH}")
        # Log contents of AI_APP_DIR for diagnostics
        if os.path.exists(AI_APP_DIR):
            try:
                logger.info(f"Contents of AI_APP_DIR ({AI_APP_DIR}): {os.listdir(AI_APP_DIR)}")
            except Exception as e_list:
                logger.error(f"Could not list contents of AI_APP_DIR ({AI_APP_DIR}): {e_list}")
        else:
            logger.error(f"AI_APP_DIR ({AI_APP_DIR}) also does not exist.")
        return {}
    
    logger.info(f"Base instructions file FOUND at {BASE_INSTRUCTIONS_PATH}. Attempting to read...")
    try:
        with open(BASE_INSTRUCTIONS_PATH, 'r', encoding='utf-8') as f:
            instructions = yaml.safe_load(f)
        if not instructions: # This means the file was empty or contained only comments/invalid YAML for safe_load
            logger.error(f"File {BASE_INSTRUCTIONS_PATH} was loaded but is empty or malformed (YAML parsing resulted in None/empty).")
            return {}
        logger.info(f"Successfully loaded and parsed base instructions from {BASE_INSTRUCTIONS_PATH}")
        return instructions
    except FileNotFoundError: # This should ideally be caught by os.path.exists, but as a safeguard.
        logger.error(f"Safeguard: FileNotFoundError for {BASE_INSTRUCTIONS_PATH} despite os.path.exists initially being true. This is unexpected.")
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
