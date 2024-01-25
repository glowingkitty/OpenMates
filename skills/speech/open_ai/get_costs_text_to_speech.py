################
# Default Imports
################
import sys
import os
import re

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('skills.*', '', full_current_path)
sys.path.append(main_directory)

from server import *
################


def get_costs_text_to_speech(
        num_characters: str,
        model_name: str = "tts-1",
        currency: str = "USD") -> dict:
    try:
        add_to_log(state="start", module_name="Audio | Speech | OpenAI", color="yellow")
        
        # calculate the costs
        prices_per_character = {
            "tts-1-hd": 0.030/1000,
            "tts-1": 0.015/1000
        }

        total_costs = num_characters * prices_per_character[model_name]

        add_to_log(state="success", message=f"Successfully calculated the costs for {num_characters} characters of text using the {model_name} model")
        add_to_log(state="success", message=f"Total costs: {round(total_costs,4)} {currency}")

        return {
            "total_costs": total_costs,
            "currency": currency
            }
    
    except KeyboardInterrupt:
        shutdown()
    
    except Exception:
        process_error(f"Failed getting the costs for {num_characters} characters of text using the {model_name} model", traceback=traceback.format_exc())
        return None
    

if __name__ == "__main__":
    get_costs_text_to_speech(num_characters=1000)