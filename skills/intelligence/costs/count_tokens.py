################
# Default Imports
################
import sys
import os
import re

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('skills.intelligence.*', '', full_current_path)
sys.path.append(main_directory)

from server import *
################

import tiktoken


def count_tokens(
        message: str = None,
        message_history: list = None,
        model_name: str = "gpt-3.5-turbo") -> int:
    try:
        add_to_log(state="start", module_name="LLMs", color="yellow")
        add_to_log(f"Counting the tokens ...")

        if message_history and not message:
            message = ""
            for message_item in message_history:
                if message_item.get("message"):
                    message += message_item["message"]
                elif message_item.get("content"):
                    if type(message_item["content"]) == list:
                        for content_item in message_item["content"]:
                            if content_item.get("text"):
                                message += content_item["text"]
                    else:
                        message += message_item["content"]
        
        message = str(message)
        if model_name == "gpt-3.5":
            model_name = "gpt-3.5-turbo"
        encoding = tiktoken.encoding_for_model(model_name)
        tokens = len(encoding.encode(message))

        add_to_log(state="success", message=f"Successfully counted the tokens: {tokens}")

        return tokens
    
    except KeyboardInterrupt:
        shutdown()
    
    except Exception:
        process_error("Failed to count the tokens", traceback=traceback.format_exc())
        return None
    

if __name__ == "__main__":
    count_tokens(message="Hello World")