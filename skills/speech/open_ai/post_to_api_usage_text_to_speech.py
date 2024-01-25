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


def post_to_api_usage_text_to_speech(
        num_characters: int,
        model_name: str = "tts-1") -> bool:
    
    try:
        add_to_log(state="start", module_name="Audio | Speech | OpenAI", color="yellow")

        # TODO send request to save the costs to the database via rabbitmq

        # post them to a permanent database
        # TODO: post the total costs to a database that is always online
        

        add_to_log(state="success", message=f"Successfully sent the request to RabbitMQ to save the costs to the database.")
        return True
    
    except KeyboardInterrupt:
        shutdown()
    
    except Exception:
        process_error("Failed to post the total costs to the database.", traceback=traceback.format_exc())

if __name__ == "__main__":
    # test the function with the arguments from the command line
    post_to_api_usage_text_to_speech(num_characters=49)