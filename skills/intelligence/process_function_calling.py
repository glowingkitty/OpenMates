import sys
import os
import re
import json

# All the available tools
from skills.images.text_to_image.open_ai.start_generate_image import start_generate_image
from skills.reminder.set_reminder import set_reminder

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('API_OpenAI.*', '', full_current_path)
sys.path.append(main_directory)

from server import *


def process_function_calling(
        tool_calls,
        channel_id: str,
        sender_username: str,
        thread_id: str,
        bot_name: str
    ):
    try:
        add_to_log(state="start", module_name="LLMs", color="yellow")
        add_to_log("Processing function calls ...")

        for tool_call in tool_calls:
            add_to_log(f"Processing function call: {tool_call.function.name}")
            function_name = tool_call.function.name
            function_args = json.loads(tool_call.function.arguments)

            # call the function
            function_response = None
            if function_name == "start_generate_image":
                function_response = start_generate_image(
                    channel_id = channel_id,
                    target_user = sender_username,
                    thread_id = thread_id,
                    bot_name=bot_name,
                    prompt=function_args.get("prompt"),
                    image_shape=function_args.get("image_shape") or "square"
                )

            elif function_name == "set_reminder":
                function_response = set_reminder(
                    channel_id = channel_id,
                    target_user = sender_username,
                    thread_id = thread_id,
                    reminder_time = function_args.get("reminder_time")
                )
            
        return function_response
    
    except Exception:
        process_error("Failed to process function calls", traceback=traceback.format_exc())
        return None