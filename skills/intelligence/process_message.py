import uuid
import traceback
import sys
import os
import re
from openai.resources.chat.completions import ChatCompletion

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('API_OpenAI.*', '', full_current_path)
sys.path.append(main_directory)

from server import *

from skills.intelligence.ask_llm import ask_llm
from server.queue.write_message_to_outgoing_messages import write_message_to_outgoing_messages
from chat.mattermost.functions.message.send_typing_indicator import send_typing_indicator



def code_block_started_or_ended(text: str) -> bool:
    if text.startswith('``') or text.endswith('``'):
        return True
    return False


def is_new_paragraph(text: str, inside_code_block: bool) -> bool:
    if not inside_code_block and text.endswith('\n\n'):
        return True
    if inside_code_block and text.endswith('``'):
        return True
    return False


async def process_message(
        sender_username: str,
        bot: dict,
        new_message: str = "Hey, how are you doing?",
        message_history: list = None,
        stream: bool = True,
        channel_name: str = None,
        channel_id: str = None,
        thread_id: str = None) -> bool:
    try:
        add_to_log(state="start", module_name="OpenAI", color="yellow")

        # handle reminder bot
        if bot["user_name"] == "remi":
            message_history = None # bot doesn't need message history, except for last message
            stream = False


        # process message with LLM
        response = await ask_llm(
            thread_id=thread_id,
            channel_id=channel_id,
            sender_username=sender_username,
            bot=bot,
            new_message=new_message,
            message_history=message_history,
            stream=stream)

        # process stream response
        full_message = ""
        inside_code_block = False
        code_block_just_started = False

        if stream and type(response) != str and type(response) != ChatCompletion:
            add_to_log("Processing stream response...")
            # generate stream_id based on UUID, to be able to update messages on mattermost
            stream_id = str(uuid.uuid4())
            async for message in response:
                new_message_part = message.choices[0].delta.content or None
                if new_message_part:
                    send_typing_indicator(
                        bot_name=bot["user_name"], 
                        channel_id=channel_id, 
                        thread_id=thread_id
                        )

                    # if new messsage part is a new line, also print it as escape character
                    full_message += new_message_part

                    # check if a new code block has started
                    code_block_status_changed = code_block_started_or_ended(new_message_part)

                    if code_block_status_changed:
                        inside_code_block = not inside_code_block

                        if inside_code_block:
                            code_block_just_started = True
                    
                    # check if new paragraph has started
                    if not code_block_just_started and is_new_paragraph(full_message,inside_code_block):
                        # send paragraph
                        write_message_to_outgoing_messages(
                            full_message=full_message,
                            stream_id=stream_id,
                            channel_name=channel_name,
                            channel_id=channel_id,
                            thread_id=thread_id,
                            bot_name=bot["user_name"]
                            )
                    
                    code_block_just_started = False
                                
            # send finale paragraph
            write_message_to_outgoing_messages(
                full_message=full_message + "\n@"+sender_username if ("@"+sender_username not in full_message) else full_message,
                stream_id=stream_id,
                channel_name=channel_name,
                channel_id=channel_id,
                thread_id=thread_id,
                bot_name=bot["user_name"]
                )

            
        else:
            # send response in full
            if type(response) == str:
                full_message = response
            elif type(response) == ChatCompletion:
                full_message = response.choices[0].message.content
            else:
                full_message = response[0]
                
            write_message_to_outgoing_messages(
                full_message = full_message + "\n@"+sender_username, 
                channel_name = channel_name,
                channel_id = channel_id,
                thread_id = thread_id,
                bot_name = bot["user_name"]
                )

        add_to_log(state="success", message=f"Successfully processed message from '{sender_username}'")
        return True
    
    except KeyboardInterrupt:
        shutdown()
    
    except Exception:
        process_error(f"Failed to process message from '{sender_username}'", traceback=traceback.format_exc())
        return False