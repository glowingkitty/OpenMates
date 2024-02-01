import sys
import os
import re

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('skills.*', '', full_current_path)
sys.path.append(main_directory)

from server import *


def load_available_skill_tool_parameters() -> list:
    try:
        add_to_log(state="start", module_name="Skills | Intelligence | OpenAI | Load skill tools", color="yellow")

        # Load the skill tools
        # TODO load all tools for all skills into memory, for every bot, when the server boots
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "get_current_weather",
                    "description": "Get the current weather in a given location",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "location": {
                                "type": "string",
                                "description": "The city and state, e.g. San Francisco, CA",
                            },
                            "unit": {"type": "string", "enum": ["celsius", "fahrenheit"]},
                        },
                        "required": ["location"],
                    },
                },
            },
        ]

        add_to_log(f"Loaded {len(tools)} skill tools.", state="success")

        return tools

    
    except KeyboardInterrupt:
        shutdown()

    except Exception:
        process_error("Failed to load skill tools.", traceback=traceback.format_exc())



if __name__ == "__main__":
    tools = load_available_skill_tool_parameters()
    print(tools)