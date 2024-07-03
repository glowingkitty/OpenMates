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
from skills.intelligence.costs.count_tokens import count_tokens
from skills.intelligence.costs.get_costs_chat import get_costs_chat

async def process_llm_response(response, asked_mate_username: str, llm_params: dict):
    try:
        add_to_log(state="start", module_name="Skills | Intelligence | OpenAI | Process LLM response", color="yellow")

        available_functions = load_available_skill_functions(asked_mate_username)
        

        # calulate the input token count
        input_token_count = 0
        for message in llm_params["messages"]:
            input_token_count+=count_tokens(message=message["content"])

        tool_calls = []
        llm_response_message = ""

        # if the response is a stream, check every message part for a function call or a text part and process it accordingly
        if llm_params["stream"]==True:

            function_name = None
            function_arguments = None

            # check if a function call is present in the response
            async for message in response:

                #####################################
                ##### Send message part to user #####
                #####################################
                if message.choices[0].delta.content and len(message.choices[0].delta.content)>0:
                    print(message.choices[0].delta.content)
                    llm_response_message+=message.choices[0].delta.content
                    # TODO if a message part is returned, send that to rabbitmq, which will then collect the parts, build message paragraphs, and send them as a response to the client


                #####################################
                ###### Process function call ########
                #####################################
                elif message.choices[0].delta.tool_calls != None:

                    # Start collecting the next function call
                    if message.choices[0].delta.tool_calls[0].function.name != None:
                        # But before processing the next function, make sure the current function is added to tool_calls
                        if function_name and function_arguments:
                            tool_calls.append({
                                "id":tool_call_id,
                                "type":"function",
                                "function":{
                                    "name":function_name,
                                    "arguments":json.dumps(json.loads(function_arguments))
                                }
                            })
                        
                        # Then collect the data for that function call
                        tool_call_id = message.choices[0].delta.tool_calls[0].id
                        function_name = message.choices[0].delta.tool_calls[0].function.name
                        add_to_log(f"Function call detected: {function_name} (id: {tool_call_id})")
                        function_arguments = ""

                    # Collect the function arguments
                    elif message.choices[0].delta.tool_calls[0].function.arguments != "":
                        function_arguments_part = message.choices[0].delta.tool_calls[0].function.arguments
                        function_arguments+=function_arguments_part

                # If all function calls are received, add the last function to tool_calls
                elif (message.choices[0].finish_reason != None and message.choices[0].finish_reason == "tool_calls"):
                    tool_calls.append({
                        "id":tool_call_id,
                        "type":"function",
                        "function":{
                            "name":function_name,
                            "arguments":json.dumps(json.loads(function_arguments))
                        }
                    })

            # if any tool_calls are present, process them
            if len(tool_calls)>0:

                #####################################
                ##### Add tool calls to history #####
                #####################################
                llm_params["messages"].append({
                    "role":"assistant",
                    "tool_calls":tool_calls
                })

                #####################################
                ####### Execute all functions #######
                #####################################
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

                # But first remove the tools, since we only want to interpret the tool response, not trigger another function call
                llm_params.pop("tools")
                llm_params.pop("tool_choice")
                second_response = await client.chat.completions.create(**llm_params)

                
                #####################################
                ##### Send message part to user #####
                #####################################
                async for message in second_response:
                    if message.choices[0].delta.content and len(message.choices[0].delta.content)>0:
                        print(message.choices[0].delta.content)
                        llm_response_message+=message.choices[0].delta.content
                        # TODO if a message part is returned, send that to rabbitmq, which will then collect the parts, build message paragraphs, and send them as a response to the client

        # calculate the output token count
        output_function_calling_token_count=count_tokens(message=str(tool_calls)) if tool_calls else 0 # NOTE OpenAI does not show the token count for the function calls, so this is a workaround for an estimation, using the tiktoken library from OpenAI
        output_response_token_count=count_tokens(message=llm_response_message) # NOTE OpenAI does not show the full token count for the response, so this is a workaround for an estimation, using the tiktoken library from OpenAI
        output_total_token_count = output_function_calling_token_count+output_response_token_count

        # calculate the costs
        total_costs = get_costs_chat(
            num_input_tokens=input_token_count,
            num_output_tokens=output_total_token_count,
            model_name=llm_params["model"]
        )

        add_to_log(f"Processed response from OpenAI.", state="success")
        return {
            "total_costs":total_costs,
            "total_token_count": input_token_count+output_total_token_count,
            "total_output_token_count": output_total_token_count,
            "total_input_token_count": input_token_count,
            "output_message_token_count": output_response_token_count,
            "output_function_calling_token_count": output_function_calling_token_count,
            "output_message": llm_response_message,
            "output_function_calls": tool_calls,
        }

    except KeyboardInterrupt:
        shutdown()

    except Exception:
        process_error("Failed to process function calls.", traceback=traceback.format_exc())