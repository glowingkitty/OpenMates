import sys
import os
import re

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('skills.*', '', full_current_path)
sys.path.append(main_directory)

from server import *

import json
from skills.intelligence.openai.load_available_skill_functions import load_available_skill_functions
from skills.intelligence.openai.load_client import load_client


async def process_llm_response(response, llm_params: dict):
    try:
        add_to_log(state="start", module_name="Skills | Intelligence | OpenAI | Process LLM response", color="yellow")

        available_functions = load_available_skill_functions()

        tool_calls = []

        # if the response is not a stream, check the full response for function calls and process everything accordingly
        # TODO

        # if the response is a stream, check every message part for a function call or a text part and process it accordingly
        if llm_params["stream"]==True:
            function_name = None
            function_arguments = None
            # check if a function call is present in the response
            async for message in response:

                # if the message is text, forward it to the client via rabbitmq
                if message.choices[0].delta.content and len(message.choices[0].delta.content)>0:
                    # add_to_log(f"Response is a text response: {message.choices[0].delta.content}")
                    # return response
                    print(message.choices[0].delta.content)

                    # TODO if a message part is returned, send that to rabbitmq, which will then collect the parts, build message paragraphs, and send them as a response to the client


                # if the message is a function call, collect the function name, arguments and then execute the function
                elif message.choices[0].delta.tool_calls != None:
                    # the response is a function call

                    # get the function name
                    if message.choices[0].delta.tool_calls[0].function.name != None:
                        # add the previous function call
                        if function_name and function_arguments:
                            tool_calls.append({
                                "id":tool_call_id,
                                "type":"function",
                                "function":{
                                    "name":function_name,
                                    "arguments":json.dumps(json.loads(function_arguments))
                                }
                            })
                        
                        # start collecting the data for that function call
                        tool_call_id = message.choices[0].delta.tool_calls[0].id
                        function_name = message.choices[0].delta.tool_calls[0].function.name
                        add_to_log(f"Function call detected: {function_name} (id: {tool_call_id})")
                        function_arguments = ""

                    elif message.choices[0].delta.tool_calls[0].function.arguments != "":
                        function_arguments_part = message.choices[0].delta.tool_calls[0].function.arguments
                        function_arguments+=function_arguments_part

                elif (message.choices[0].finish_reason != None and message.choices[0].finish_reason == "tool_calls"):
                    # add the function to tool_calls
                    tool_calls.append({
                        "id":tool_call_id,
                        "type":"function",
                        "function":{
                            "name":function_name,
                            "arguments":json.dumps(json.loads(function_arguments))
                        }
                    })

            # Add the tool calls to the message history
            llm_params["messages"].append({
                "role":"assistant",
                "tool_calls":tool_calls
            })

            # After all function calls are received, process them and add output to message history
            for tool_call in tool_calls:
                tool_call_id = tool_call["id"]
                function_name = tool_call["function"]["name"]
                function_arguments = tool_call["function"]["arguments"]

                # execute the function
                function_arguments = json.loads(function_arguments)
                add_to_log(f"Executing function '{function_name}' with arguments '{function_arguments}'")

                # NOTE: this function is not called async, which might cause performance issues. Need to test and see if action needs to be taken.
                function_response = available_functions[function_name](**function_arguments)

                llm_params["messages"].append(
                    {
                        "tool_call_id": tool_call_id,
                        "role": "tool",
                        "name": function_name,
                        "content": function_response,
                    }
                )
        
            # Then send the message history including the function response to the OpenAI API
            client = await load_client()

            llm_params.pop("tools")
            llm_params.pop("tool_choice")
            second_response = await client.chat.completions.create(**llm_params)
            async for message in second_response:
                print(message.choices[0].delta.content)
                # TODO if a message part is returned, send that to rabbitmq, which will then collect the parts, build message paragraphs, and send them as a response to the client

        add_to_log(f"Processed response from OpenAI.", state="success")

    except KeyboardInterrupt:
        shutdown()

    except Exception:
        process_error("Failed to process function calls.", traceback=traceback.format_exc())