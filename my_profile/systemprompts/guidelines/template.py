################
# Default Imports
################
import sys
import os
import re

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('API_OpenAI.*', '', full_current_path)
sys.path.append(main_directory)

from server import *
################

import tiktoken


def count_tokens(
        message: str, 
        model_name: str = "gpt-3.5-turbo") -> int:
    try:
        add_to_log(module_name="OpenAI", color="yellow", state="start")
        add_to_log("Counting the tokens ...")
        
        message = str(message)
        if model_name == "gpt-3.5":
            model_name = "gpt-3.5-turbo"
        encoding = tiktoken.encoding_for_model(model_name)
        tokens = len(encoding.encode(message))

        add_to_log(f"Successfully counted the tokens: {tokens}",state="success")

        return tokens
    
    except KeyboardInterrupt:
        shutdown()
    
    except Exception:
        process_error("Failed to count the tokens via model '{model_name}'",traceback=traceback.format_exc())
        return None
    

if __name__ == "__main__":
    count_tokens(message="Hello World")