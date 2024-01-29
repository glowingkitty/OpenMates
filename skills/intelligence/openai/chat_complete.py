import sys
import os
import re

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('skills.*', '', full_current_path)
sys.path.append(main_directory)

from server import *

import random
from openai import AsyncOpenAI, RateLimitError, APITimeoutError, InternalServerError, BadRequestError


async def chat_complete(
        client: AsyncOpenAI,
        messages: list,
        model: str = "gpt-3.5-turbo", # or 'gpt-4-turbo-preview'
        temperature: float = 0,
        max_output_tokens: int = 4096,
        stream: bool = False,
        timeout: int = 60,
        use_function_calling: bool = True,
        response_format: str = None, # can be set to 'json' for json response
        ):
    try:
        add_to_log(state="start", module_name="Skills | Intelligence | OpenAI | Chat complete", color="yellow")

        # if the model is gpt-3.5-turbo, adapt the output max_output_tokens, by subtracting the length of the messages
        if model.startswith("gpt-3.5-turbo"):
            for message in messages:
                max_output_tokens = max_output_tokens - len(message["content"])

        params = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_output_tokens,
            "stream": stream,
            "timeout": timeout
        }

        # if json response is requested, add the parameter
        if response_format == "json":
            params["response_format"] = { "type": "json_object" }

        # TODO add function calling and check if stream needs to be turned off for that

        for _ in range(10):
            try:
                response = await client.chat.completions.create(**params)

                add_to_log(f"Received response from OpenAI.", state="success")
                return response
            
            # if the OpenAI API returns an error, try again
            except (APITimeoutError, RateLimitError, InternalServerError) as e:
                add_to_log(f"OpenAI {e.__class__.__name__}. Trying again...", state="error")
                await asyncio.sleep(5 if isinstance(e, RateLimitError) else 1)
                continue

            except BadRequestError as e:
                add_to_log(f"OpenAI {e.__class__.__name__}: {e}", state="error")
                break

            except Exception:
                error_log = traceback.format_exc()
                if "This model's maximum context length is" in error_log:
                    add_to_log("Message too long.", state="error")
                    error_messages = [
                        "Seriously? That's way too much text for me to handle.",
                        "You've got to be kidding! I can't read all this.",
                        "This is just too much! I don't want to read all this.",
                        "Oh come on, this is way too lengthy for me to read.",
                        "Ehh no thanks, that's too much text for me to read.",
                        "Sorry but I don't want to read all this. It's too much."
                    ]

                    return [{"choices": [{"delta": {"content": random.choice(error_messages)}}]}]

                else:
                    process_error("Failed sending a message to the chatbot", traceback=traceback.format_exc())
                    return None
    
    except KeyboardInterrupt:
        shutdown()

    except Exception:
        process_error("Failed to receive response from OpenAI.", traceback=traceback.format_exc())



if __name__ == "__main__":
    import asyncio
    from skills.intelligence.openai.load_client import load_client

    client = asyncio.run(load_client())

    ## Simple test
    # response = asyncio.run(chat_complete(
    #     client=client,
    #     messages=[
    #         {"role": "system", "content":"You are a helpful assistant."},
    #         {"role": "user", "content":"Write Python code that print's \"Hello World!\""}
    #     ]
    # ))
    # if response:
    #     print(response.choices[0].message.content)

    ## Function calling test
    response = asyncio.run(chat_complete(
        client=client,
        messages=[
            {"role": "system", "content":"You are a helpful assistant."},
            {"role": "user", "content":"Write Python code that print's \"Hello World!\""}
        ]
    ))
    if response:
        print(response.choices[0].message.content)