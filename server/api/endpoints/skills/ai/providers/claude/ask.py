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

from anthropic import Anthropic
from dotenv import load_dotenv
from server.api.models.skills.ai.skills_ai_ask import AiAskOutput, AiAskInput, ContentItem, ToolUse, Tool, AiAskOutputStream
from typing import Union, List, Dict, Any, Optional
from fastapi.responses import StreamingResponse
from anthropic.types import ContentBlock, TextBlock, ToolUseBlock
import json

def serialize_content_block(block: ContentBlock) -> Dict[str, Any]:
    result = {"type": block.type}
    if isinstance(block, TextBlock):
        result["text"] = block.text
    elif isinstance(block, ToolUseBlock):
        result["tool_use"] = {
            "id": block.id,
            "name": block.name,
            "input": block.input
        }
    return result

def chunk_text(text):
    lines = text.split('\n')
    chunks = []
    current_chunk = ""
    code_block = False
    paragraph_break = False

    for line in lines:
        # Check for code blocks
        if line.strip().startswith('```'):
            code_block = not code_block

        # Check for paragraph breaks
        if line.strip() == '':
            paragraph_break = True
        else:
            paragraph_break = False

        current_chunk += line + "\n"

        # Check for various separators
        is_separator = (
            re.match(r'^(#+\s|[A-Z][a-z]+(\s+[A-Z][a-z]+){0,2}:)', line.strip()) or  # Headlines
            re.match(r'^(-{3,}|\*{3,}|_{3,})$', line.strip()) or  # Horizontal rules
            re.match(r'^>.*$', line.strip()) or  # Block quotes
            re.match(r'^\|.*\|$', line.strip()) or  # Tables
            re.match(r'^(===+|#{3,})$', line.strip()) or  # Section breaks
            re.match(r'^\s*[\d*-]\s', line) or  # List items
            re.match(r'^[A-Za-z-]+:\s', line)  # Key-value pairs
        )

        # If it's a separator and we have a substantial chunk, start a new chunk
        if (is_separator or paragraph_break) and len(current_chunk.strip()) > 50 and not code_block:
            chunks.append(current_chunk)
            current_chunk = ""

    if current_chunk:
        chunks.append(current_chunk)

    return chunks

async def ask(
        token: str,
        system: str = "You are a helpful assistant. Keep your answers concise.",
        message: str = None,
        message_history: List[Dict[str, Any]] = None,
        provider: dict = {"name":"claude", "model":"claude-3.5-sonnet"},
        temperature: float = 0.5,
        stream: bool = False,
        cache: bool = False,
        max_tokens: int = 1000,
        stop_sequence: str = None,
        tools: List[Tool] = None
    ) -> Union[AiAskOutput, StreamingResponse]:
    """
    Ask a question to Claude
    """

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

    # TODO check for user api key or billing / enough credits

    add_to_log("Asking Claude ...", module_name="OpenMates | Skills | Claude | Ask", color="yellow")

    # Select a more specific model
    if input.provider.model == "claude-3.5-sonnet":
        ai_model = "claude-3-5-sonnet-20240620"
    elif input.provider.model == "claude-3-haiku":
        ai_model = "claude-3-haiku-20240307"

    # Define common configuration
    message_config = {
        "model": ai_model,
        "max_tokens": input.max_tokens,
        "system": input.system,
        "messages": [message.to_dict() for message in input.message_history] if input.message_history else [
            {
                "role": "user",
                "content": [{"type": "text", "text": input.message}]
            }
        ],
        "temperature": input.temperature
    }

    if input.tools:
        message_config["tools"] = input.tools
        message_config["tool_choice"] = {"type": "auto"}

    # Send request to Claude to get a response
    load_dotenv()
    client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    if input.stream:
        async def event_stream():
            with client.messages.stream(**message_config) as stream:
                accumulated_text = ""
                accumulated_json = ""
                for event in stream:
                    if event.type == "content_block_delta":
                        if event.delta.type == "text_delta":
                            accumulated_text += event.delta.text
                            chunks = chunk_text(accumulated_text)
                            if len(chunks) > 1:
                                for complete_chunk in chunks[:-1]:
                                    yield AiAskOutputStream(
                                        content=ContentItem(type="text", text=complete_chunk)
                                    ).model_dump_json(exclude_none=True) + "\n\n"
                                accumulated_text = chunks[-1]
                        elif event.delta.type == "input_json_delta":
                            accumulated_json += event.delta.partial_json
                            try:
                                parsed_json = json.loads(accumulated_json)
                                tool_name = determine_tool_name(parsed_json, input.tools)
                                if tool_name:
                                    yield AiAskOutputStream(
                                        content=ContentItem(
                                            type="tool_use",
                                            tool_use=ToolUse(
                                                id=str(uuid.uuid4()),
                                                name=tool_name,
                                                input=parsed_json
                                            )
                                        )
                                    ).model_dump_json(exclude_none=True) + "\n\n"
                                    accumulated_json = ""
                            except json.JSONDecodeError:
                                pass  # Continue accumulating JSON
                    elif event.type == "message_stop":
                        if accumulated_text:
                            yield AiAskOutputStream(content=ContentItem(type="text", text=accumulated_text)).model_dump_json(exclude_none=True) + "\n\n"
                        yield AiAskOutputStream(stream_end=True).model_dump_json(exclude_none=True) + "\n\n"

        return StreamingResponse(event_stream(), media_type="text/event-stream")
    else:
        response = client.messages.create(**message_config)

        # TODO calculate cost, based on token usage
        cost_credits = None
        content = []
        for block in response.content:
            if isinstance(block, TextBlock):
                content.append(ContentItem(type="text", text=block.text))
            elif isinstance(block, ToolUseBlock):
                content.append(ContentItem(
                    type="tool_use",
                    tool_use=ToolUse(
                        id=block.id,
                        name=block.name,
                        input=block.input
                    )
                ))
            # Add handling for tool results if applicable
            # This might depend on how Claude returns tool results
        return AiAskOutput(
            content=content,
            cost_credits=cost_credits
        ).model_dump(exclude_none=True)

def determine_tool_name(parsed_json: Dict[str, Any], tools: List[Tool]) -> Optional[str]:
    for tool in tools:
        if all(prop in parsed_json for prop in tool.input_schema.properties.keys()):
            return tool.name
    return None