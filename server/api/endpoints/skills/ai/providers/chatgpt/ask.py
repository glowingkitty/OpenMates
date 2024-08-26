################
# Default Imports
################
import sys
import os
import re
import uuid

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('skills.*', '', full_current_path)
sys.path.append(main_directory)

from server import *
################

from openai import OpenAI
from dotenv import load_dotenv
from server.api.models.skills.ai.skills_ai_ask import AiAskOutput, ContentItem, AiAskInput, ToolUse, AiAskOutputStream
from typing import Literal, Union, List, Dict, Any
from fastapi.responses import StreamingResponse
import json
from server.api.endpoints.skills.ai.providers.claude.ask import chunk_text

def serialize_content_block(block: Dict[str, Any]) -> Dict[str, Any]:
    # Helper function to serialize content blocks
    return {
        "type": block["type"],
        "text": block.get("text", ""),
        "tool_calls": block.get("tool_calls", [])
    }

async def ask(
        api_token: str = os.getenv("OPENAI_API_KEY"),
        system: str = "You are a helpful assistant. Keep your answers concise.",
        message: str = None,
        message_history: List[Dict[str, Any]] = None,
        provider: dict = {"name":"chatgpt", "model":"gpt-4o"},
        temperature: float = 0.5,
        stream: bool = False,
        cache: bool = False,
        max_tokens: int = 1000,
        stop_sequence: str = None,
        tools: List[dict] = None
    ) -> Union[AiAskOutput, StreamingResponse]:
    """
    Ask a question to ChatGPT
    """

    # Create an AiAskInput object with the provided parameters
    input = AiAskInput(
        system=system,
        message=message,
        message_history=message_history,
        provider=provider,
        temperature=temperature,
        stream=stream,
        cache=cache,
        max_tokens=max_tokens,
        stop_sequence=stop_sequence,
        tools=tools
    )

    add_to_log("Asking ChatGPT ...", module_name="OpenMates | Skills | ChatGPT | Ask", color="yellow")

    # Initialize OpenAI client
    load_dotenv()
    client = OpenAI(api_key=api_token)

    # Prepare messages for the chat
    messages = [{"role": "system", "content": input.system}]
    tool_use_map = {}

    if input.message_history:
        for msg in input.message_history:
            msg_dict = msg.to_dict()
            if isinstance(msg_dict['content'], list):
                # Handle complex message content (text, images, tool uses, tool results)
                content = []
                for item in msg_dict['content']:
                    if item['type'] == 'text':
                        # Add text content
                        content.append({"type": "text", "text": item['text']})
                    elif item['type'] == 'image':
                        # Add image content
                        content.append({
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{item['source']['media_type']};base64,{item['source']['data']}"
                            }
                        })
                    elif item['type'] == 'tool_use':
                        # Handle tool use
                        tool_call = {
                            "role": "assistant",
                            "content": None,
                            "function_call": {
                                "name": item['name'],
                                "arguments": json.dumps(item['input'])
                            }
                        }
                        messages.append(tool_call)
                        tool_use_map[item['id']] = item['name']
                    elif item['type'] == 'tool_result':
                        # Handle tool result
                        if item['tool_use_id'] in tool_use_map:
                            messages.append({
                                "role": "function",
                                "name": tool_use_map[item['tool_use_id']],
                                "content": item['content']
                            })
                        else:
                            add_to_log(f"Warning: tool_result without corresponding tool_use (ID: {item['tool_use_id']})", color="yellow")
                if content:
                    messages.append({"role": msg_dict['role'], "content": content})
            else:
                # Add simple message content
                messages.append(msg_dict)
    elif input.message:
        # Add single message if no history is provided
        messages.append({"role": "user", "content": input.message})

    # Prepare chat configuration
    chat_config = {
        "model": input.provider.model,
        "messages": messages,
        "temperature": input.temperature,
        "max_tokens": input.max_tokens,
        "stream": input.stream
    }

    # Add tools configuration if provided
    if input.tools:
        chat_config["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.input_schema.model_dump()
                }
            }
            for tool in input.tools
        ]
        chat_config["tool_choice"] = "auto"  # Use tool_choice instead of function_call

    if input.stream:
        # Handle streaming response
        async def event_stream():
            stream = client.chat.completions.create(**chat_config)
            accumulated_text = ""
            accumulated_tool_call = {}
            for chunk in stream:
                if chunk.choices[0].delta.content is not None:
                    accumulated_text += chunk.choices[0].delta.content
                    chunks = chunk_text(accumulated_text)
                    if len(chunks) > 1:
                        for complete_chunk in chunks[:-1]:
                            yield AiAskOutputStream(content=ContentItem(type="text", text=complete_chunk)).model_dump_json(exclude_none=True) + "\n\n"
                        accumulated_text = chunks[-1]
                elif chunk.choices[0].delta.tool_calls:
                    tool_call = chunk.choices[0].delta.tool_calls[0]
                    if tool_call.function.name:
                        accumulated_tool_call["name"] = tool_call.function.name
                    if tool_call.function.arguments:
                        accumulated_tool_call["arguments"] = accumulated_tool_call.get("arguments", "") + tool_call.function.arguments

                    if "name" in accumulated_tool_call and "arguments" in accumulated_tool_call:
                        try:
                            parsed_arguments = json.loads(accumulated_tool_call["arguments"])
                            yield AiAskOutputStream(
                                content=ContentItem(
                                    type="tool_use",
                                    tool_use=ToolUse(
                                        id=str(uuid.uuid4()),
                                        name=accumulated_tool_call["name"],
                                        input=parsed_arguments
                                    )
                                )
                            ).model_dump_json(exclude_none=True) + "\n\n"
                            accumulated_tool_call = {}
                        except json.JSONDecodeError:
                            pass
            if accumulated_text:
                yield AiAskOutputStream(content=ContentItem(type="text", text=accumulated_text)).model_dump_json(exclude_none=True) + "\n\n"
            yield AiAskOutputStream(stream_end=True).model_dump_json(exclude_none=True) + "\n\n"

        return StreamingResponse(event_stream(), media_type="text/event-stream")
    else:
        # Handle non-streaming response
        response = client.chat.completions.create(**chat_config)

        # TODO: Calculate cost based on token usage
        cost_credits = None

        # Process the response content
        content = []
        if response.choices[0].message.content:
            content.append(ContentItem(type="text", text=response.choices[0].message.content))

        # Handle tool calls (previously function_call)
        if response.choices[0].message.tool_calls:
            for tool_call in response.choices[0].message.tool_calls:
                content.append(ContentItem(
                    type="tool_use",
                    tool_use=ToolUse(
                        name=tool_call.function.name,
                        input=json.loads(tool_call.function.arguments)
                    )
                ))

        # Add handling for tool results if applicable
        # This might depend on how ChatGPT returns tool results

        add_to_log(content)

        # Return the final output
        return AiAskOutput(
            content=content,
            cost_credits=cost_credits
        ).model_dump(exclude_none=True)