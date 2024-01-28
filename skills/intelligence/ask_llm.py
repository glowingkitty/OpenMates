from openai import AsyncOpenAI, RateLimitError, APITimeoutError, InternalServerError, Stream
import time
import sys
import os
import re
import random
import asyncio
from typing import Union
import json
import aiohttp

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('skills.intelligence.*', '', full_current_path)
sys.path.append(main_directory)

from server import *

from server.message.get_location_time_date import get_location_time_date
from chat.mattermost.functions.channel.get_channel_name import get_channel_name
from skills.intelligence.process_function_calling import process_function_calling
from skills.intelligence.post_to_api_usage_chat import post_to_api_usage_chat
from skills.intelligence.prepare_message_history_for_llm import prepare_message_history_for_llm
from skills.intelligence.count_tokens import count_tokens
from skills.intelligence.get_costs_chat import get_costs_chat
from skills.images.text_to_image.open_ai.start_generate_image import tool__start_generate_image
from skills.reminder.set_reminder import tool__set_reminder
import httpx
import httpcore

async def ask_llm(
        new_message: str = "Hey, how are you doing?",
        bot: dict = None,
        thread_id: str = None,
        channel_id: str = None,
        sender_username: str = None,
        message_history: list = None,
        stream: bool = False,
        response_format: str = "text",
        save_request_to_json: bool = False,
        ) -> Union[str, Stream]:
    
    try:
        add_to_log(state="start", module_name="LLMs", color="yellow")

        
        if not new_message and not message_history:
            raise Exception("new_message or message_history need to be defined")
        
        if not bot:
            raise Exception("bot needs to be defined")
        
        secrets = load_secrets()
        config = load_config()

        if channel_id:
            channel_name = get_channel_name(channel_id=channel_id)
        else:
            channel_name = None

        # Load API key from environment variables
        if bot["model"].startswith("mistral-"):
            client = aiohttp.ClientSession(headers={
                "Authorization": f"Bearer {secrets['MISTRAL_AI_API_KEY']}",
                "Content-Type": "application/json",
                "Accept": "application/json"
            })
        elif bot["model"].startswith("gpt-"):
            client = AsyncOpenAI(
                api_key=secrets["OPENAI_API_KEY"]
                )
        else:
            client = AsyncOpenAI(
                base_url = "https://api.endpoints.anyscale.com/v1",
                api_key = secrets["ANYSCALE_API_KEY"]
            )

        # Load the tools for the specific bot
        tools = [globals()[f"tool__{tool}"] for tool in bot["tools"]] if "tools" in bot and bot["tools"] else None

        # Prepare message history for chatbot, allow vision
        conversion_result = prepare_message_history_for_llm(
            message_history=message_history,
            bot=bot,
            channel_name=channel_name
        )
        # TODO if the execution of a direct command was triggered, directly start that command instead
        # if conversion_result.get('start_skill'):
        #     skill_response = await get_skill_response(conversion_result['start_skill'])
        #     return skill_response

        model = conversion_result["model"]
        new_message_history = conversion_result["message_history"]
        includes_images = conversion_result["includes_images"]
        
        # Add location, date, and time to system prompt
        location_time_date = get_location_time_date()
        system_prompt = location_time_date + "\n" + bot["system_prompt"]
        
        if not new_message_history and new_message:
            new_message_history = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": new_message}
            ]
        elif message_history:
            # check if the system prompt is already in the message history
            if message_history[0]["role"] == "system":
                new_message_history = message_history
            else:
                # else, create a new message history with the system prompt first, then the message history
                new_message_history = [
                    {"role": "system", "content": system_prompt},
                    *message_history
                ]
        

        # Create a params dictionary to hold the common parameters
        params = {
            "model": model,
            "messages": new_message_history,
            "temperature": bot["creativity"],
            "max_tokens": 4096,
            "stream": stream,
            "timeout": 60
        }

        # remove all fields which are not role or content
        filtered_message_history = [{'role': message['role'], 'content': message['content']} for message in params["messages"]]
        params["messages"] = filtered_message_history

        if not includes_images and response_format=="json":
            params["response_format"] = {"type": "json_object"}

        # if the request should be saved to json, do so
        if save_request_to_json:
            # make sure the folder exists
            os.makedirs("logs/requests", exist_ok=True)
            with open(f"logs/requests/{time.time()}.json", "w") as f:
                json.dump(params, f, indent=4)

        # Get the predicted costs of the image generation
        tokens = count_tokens(message_history=new_message_history)
        costs = get_costs_chat(
            num_input_tokens=tokens,
            model_name = model,
        )
        if not costs:
            add_to_log("Failed to get the costs for the message.", state="error")
            return None
        
        # Warn about the costs in log
        add_to_log(f"You are about to spend at least {round(costs['total_costs_min'], 4)} {costs['currency']} for sending a message to {model}.")

        if config["environment"] == "development":
            add_to_log("Press CTRL+C to cancel or wait 5 seconds to auto continue ...")
            time.sleep(5)

        # try multiple times to send the message to OpenAI
        for _ in range(10):
            try:

                # if the message contains images AND the bot can use tools: send first to vision model
                if includes_images and tools:
                    add_to_log("Message contains images and bot can use tools.")
                    add_to_log(f"Sending message history to vision model '{model}'...")
                    params["stream"] = False
                    vision_response = await client.chat.completions.create(**params)

                    # if the message contains images AND the bot can use tools: recaluclate the message history without the images
                    conversion_result = prepare_message_history_for_llm(
                        message_history=message_history,
                        bot=bot,
                        channel_name=channel_name,
                        allow_image_processing=False
                        )
                    params["model"] = conversion_result["model"]
                    params["messages"] = conversion_result["message_history"]

                    # if the message contains images AND the bot can use tools: attach the response from vision model to message history
                    vision_response_message = vision_response.choices[0].message.content
                    params["messages"].append({"role": "assistant", "content":vision_response_message})

                # if the bot can use tools: send the new message history to the gpt-4 preview model with tools
                if tools:
                    add_to_log(f"Sending message history to '{model}' with tools...")
                    params["stream"] = False
                    params["tools"] = tools
                    params["tool_choice"] = "auto"
                    if model.startswith("mistral-"):
                        response = await client.post(
                            "https://api.mistral.ai/v1/chat/completions",
                            json=params
                        )
                        response = await response.json()
                    else:
                        response = await client.chat.completions.create(**params)

                # if the bot can NOT use tools: send to regular gpt-4 turbo or 3.5-turbo model
                else:
                    add_to_log(f"Sending message history to '{model}' (without tools)...")
                    if model.startswith("mistral-"):
                        # remove json_object response format if it is set
                        if "response_format" in params:
                            del params["response_format"]
                        if 'timeout' in params:
                            del params['timeout']
                        response = await client.post(
                            "https://api.mistral.ai/v1/chat/completions",
                            json=params
                        )
                        response = await response.json()
                        # check the response status code
                    else:
                        response = await client.chat.completions.create(**params)

                # if tools are used, process the response accordingly
                if tools:
                    if response.choices[0].message.tool_calls:
                        if not thread_id:
                            raise Exception("thread_id needs to be defined if tools are used")
                        if not channel_id:
                            raise Exception("channel_id needs to be defined if tools are used")
                        if not sender_username:
                            raise Exception("sender_username needs to be defined if tools are used")
                        
                        response = process_function_calling(
                            tool_calls = response.choices[0].message.tool_calls,
                            channel_id=channel_id,
                            sender_username=sender_username,
                            thread_id=thread_id,
                            bot_name = bot["user_name"]
                            )

                if type(response) == str:
                    add_to_log(f"Successfully received message from '{model}'.", state="success")
                    return response
                elif stream:
                    add_to_log("Successfully received stream from OpenAI.", state="success")
                    return response
                else:
                    if isinstance(response, dict):
                        num_input_tokens = response.get('usage', {}).get('prompt_tokens', None)
                        output_tokens = response.get('usage', {}).get('completion_tokens', None)
                        choices_content = response.get('choices', [{}])[0].get('message', {}).get('content', None)
                    else:
                        num_input_tokens = getattr(response.usage, 'prompt_tokens', None)
                        output_tokens = getattr(response.usage, 'completion_tokens', None)
                        choices_content = getattr(getattr(response.choices[0], 'message', {}), 'content', None)

                    post_to_api_usage_chat(
                        num_input_tokens=num_input_tokens,
                        num_output_tokens=output_tokens,
                        model=model
                    )

                    add_to_log(f"Successfully received message from '{model}'.", state="success")

                    # load the json from the response
                    if response_format=="json":
                        try:
                            # check if the output is a string with ```json in it
                            # if so, extract the json between the ```json and ```
                            if "```json" in choices_content:
                                output = json.loads(choices_content.split("```json")[1].split("```")[0])
                            # if not, just load the json
                            else:
                                output = json.loads(choices_content)

                        except Exception:
                            process_error(f"Failed to parse json response", traceback=traceback.format_exc())
                            output = {"output":choices_content}

                    elif response_format=="text":
                        output = choices_content

                    return output
                
            except KeyboardInterrupt:
                shutdown()

            except (APITimeoutError, RateLimitError, InternalServerError, httpx.ReadTimeout, httpx.HTTPError, httpcore.ReadTimeout) as e:
                add_to_log(f"OpenAI {e.__class__.__name__}. Trying again...", state="error")
                time.sleep(5 if isinstance(e, RateLimitError) else 1)

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
                    
                    response = [
                        {
                            "choices": [
                                {
                                    "delta": {
                                        "content": random.choice(error_messages)
                                    }
                                }
                            ]
                        }
                    ]
                    return response

                else:
                    process_error("Failed sending a message to the chatbot", traceback=traceback.format_exc())
                    return None
                

    except KeyboardInterrupt:
        shutdown()

    except Exception as e:
        process_error("Failed preparing to send a message to the chatbot", traceback=traceback.format_exc())
        return None
    
    finally:
        if client:
            if isinstance(client, aiohttp.ClientSession):
                await client.close()
    

if __name__ == "__main__":
    # # Example call to the function with dummy data
    # response = asyncio.run(ask_llm(
    #     thread_id="123",
    #     channel_id="channel",
    #     sender_username="user",
    #     bot={
    #         "user_name": "remi", 
    #         "system_prompt": "You are a helpful assistant. Answer in the same language as the question.", 
    #         "creativity": 0, 
    #         # "model": "gpt-4",
    #         "model": "gpt-3.5",
    #         # "model": "mistral-medium",
    #         # "model": "mistralai/Mixtral-8x7B-Instruct-v0.1",
    #         # "tools": ["set_reminder"]
    #         },
    #     new_message="Ich will anfangen Bambums mit Leinöl Firnis zu streichen. Was gibt es dabei zu beachten? Sicherheitshinweise? Hitze?",
    #     message_history=[],
    #     # response_format="json",
    #     stream=False
    # ))
    # print(response)
    # print(type(response))

    # TODO add keywords to transaction based on LLM response
    from skills.intelligence.load_systemprompt import load_systemprompt

    systemprompt_extract_invoice_number = load_systemprompt(special_usecase="bank_transactions_processing/extract_keywords_to_find_matching_voucher_from_transaction_purpose")
    message_history = [
                {"role": "system", "content":systemprompt_extract_invoice_number},
                {"role": "user", "content":"Payment from Part Gmbh Fuer Digitales Handeln - RNr. 475D6855-0003 RDat. 21.11.2023"}
                ]

    invoice_numbers_list = asyncio.run(ask_llm(
        bot={
            "user_name": "finn", 
            "system_prompt": systemprompt_extract_invoice_number, 
            "creativity": 0, 
            "model": "gpt-4"
        },
        message_history=message_history,
        response_format="json"
    )
    )
    print(invoice_numbers_list)