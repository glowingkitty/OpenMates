import sys
import os
import re

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('skills.*', '', full_current_path)
sys.path.append(main_directory)

from server import *

from skills.intelligence.openai.test import get_current_weather

def load_available_skill_functions(asked_mate_username: str) -> list:
    try:
        add_to_log(state="start", module_name="Skills | Intelligence | OpenAI | Load skill functions", color="yellow")

        # Load the skill functions
        # TODO load all functions for all skills into memory, for every bot, when the server boots.
        available_functions = {
            "get_current_weather": get_current_weather,
        }

        add_to_log(f"Loaded {len(available_functions)} skill functions.", state="success")

        return available_functions

    
    except KeyboardInterrupt:
        shutdown()

    except Exception:
        process_error("Failed to load skill functions.", traceback=traceback.format_exc())



if __name__ == "__main__":
    functions = load_available_skill_functions()
    print(functions)