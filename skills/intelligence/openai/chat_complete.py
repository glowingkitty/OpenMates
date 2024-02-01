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
from skills.intelligence.openai.load_available_skill_tool_parameters import load_available_skill_tool_parameters
from skills.intelligence.openai.process_llm_response import process_llm_response

async def chat_complete(
        client: AsyncOpenAI,
        messages: list,
        model: str = "gpt-4-turbo-preview", # or 'gpt-4-turbo-preview'
        temperature: float = 0,
        return_full_response: bool = False,
        timeout: int = 60,
        use_function_calling: bool = True,
        response_format: str = None, # can be set to 'json' for json response
        ):
    try:
        add_to_log(state="start", module_name="Skills | Intelligence | OpenAI | Chat complete", color="yellow")

        #TODO always return full response, regardless if stream or not? (together with token count, and costs, after calculating them and sending them to database)

        llm_params = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "stream": not return_full_response,
            "timeout": timeout
        }

        # if json response is requested, add the parameter
        if response_format == "json":
            llm_params["response_format"] = { "type": "json_object" }

        if use_function_calling:
            # Load the skill tools
            llm_params["tools"] = load_available_skill_tool_parameters()
            llm_params["tool_choice"] = "auto"

            
        # TODO what about vision? vision model doesn't support function calling. maybe manually adding the functions that can be called to the systemprompt?


        for _ in range(10):
            try:
                response = await client.chat.completions.create(**llm_params)
                add_to_log(f"Received response from OpenAI.", state="success")

                # process response
                response = await process_llm_response(response, llm_params=llm_params)
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
        # model="gpt-4-turbo-preview",
        # return_full_response=True,
        messages=[
            {"role": "system", "content":"You are a helpful assistant. Answer the questions and full the requested tasks. Keep your answers concise and to the point."},
            {"role": "user", "content":"What is interesting about Tokyo and Paris? Also, what is the weather in Tokyo and Paris now?"}
        ]
    ))
    if response:
        print(response)