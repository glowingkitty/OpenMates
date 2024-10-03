import os
import json
import uuid
import time
import asyncio
import logging
from datetime import datetime
from typing import Literal, Union, List, Dict, Any
from fastapi.responses import StreamingResponse
from dotenv import load_dotenv
import httpx  # New asynchronous HTTP client
from server.api.models.apps.ai.skills_ai_ask import (
    AiAskOutput,
    ContentItem,
    AiAskInput,
    Tool,
    ToolUse,
    AiAskOutputStream
)
from server.api.endpoints.apps.ai.providers.claude.ask import chunk_text

logger = logging.getLogger(__name__)

class SimpleRateLimiter:
    def __init__(self, max_calls, period):
        self.max_calls = max_calls
        self.period = period
        self.calls = asyncio.Queue()

    async def acquire(self):
        now = time.time()

        while not self.calls.empty():
            if now - self.calls._queue[0] > self.period:
                await self.calls.get()
            else:
                break

        if self.calls.qsize() >= self.max_calls:
            sleep_time = self.period - (now - self.calls._queue[0])
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)

        await self.calls.put(now)

# Initialize the rate limiter (adjust values as needed)
rate_limiter = SimpleRateLimiter(max_calls=5000, period=60)  # 5000 calls per minute

async def ask(
        input: AiAskInput,
        api_token: str = os.getenv("OPENAI_API_KEY"),
        retries: int = 3  # Add a retries parameter with a default value
    ) -> Union[AiAskOutput, StreamingResponse]:
    """
    Ask a question to ChatGPT asynchronously using httpx.
    """

    # Wait for rate limit to allow the call
    await rate_limiter.acquire()

    logger.info("Asking ChatGPT ...")

    load_dotenv()

    # Prepare messages for the chat
    messages = [{"role": "system", "content": input.system}]
    tool_use_map = {}

    if input.message_history:
        for msg in input.message_history:
            if isinstance(msg.content, list):
                # Handle complex message input_content (text, images, tool uses, tool results)
                input_content = []
                for item in msg.content:
                    if item.type == 'text':
                        # Add text content
                        input_content.append({"type": "text", "text": item.text})
                    elif item.type == 'image':
                        # Add image content
                        input_content.append({
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{item.source.media_type};base64,{item.source.data}"
                            }
                        })
                    elif item.type == 'tool_use':
                        # Handle tool use
                        tool_call = {
                            "role": "assistant",
                            "content": None,
                            "function_call": {
                                "name": item.name,
                                "arguments": json.dumps(item.input)
                            }
                        }
                        messages.append(tool_call)
                        tool_use_map[item.id] = item.name
                    elif item.type == 'tool_result':
                        # Handle tool result
                        if item.tool_use_id in tool_use_map:
                            messages.append({
                                "role": "function",
                                "name": tool_use_map[item.tool_use_id],
                                "content": item.content
                            })
                        else:
                            logger.warning(f"Warning: tool_result without corresponding tool_use (ID: {item.tool_use_id})")
                if input_content:
                    messages.append({"role": msg.role, "content": input_content})
            else:
                # Add simple message content
                messages.append(msg.model_dump())
    elif input.message:
        # Add single message if no history is provided
        messages.append({"role": "user", "content": input.message})

    # Prepare chat configuration
    chat_config = {
        "model": input.provider.model,
        "messages": messages,
        "temperature": input.temperature,
        "max_tokens": input.max_tokens,
        "stop": input.stop_sequence,
        "stream": input.stream
    }

    # Add tools configuration if provided
    if input.tools:
        chat_config["functions"] = [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.input_schema.model_dump()
            }
            for tool in input.tools
        ]
        chat_config["function_call"] = "auto"  # Use function_call instead of tool_choice

    async with httpx.AsyncClient() as client:
        headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json"
        }

        if input.stream:
            # Handle streaming response
            async def event_stream():
                async with client.stream("POST", "https://api.openai.com/v1/chat/completions", headers=headers, json=chat_config) as response:
                    accumulated_text = ""
                    accumulated_tool_call = {}
                    async for chunk in response.aiter_text():
                        data = json.loads(chunk)
                        if 'choices' in data:
                            choice = data['choices'][0]
                            if 'delta' in choice:
                                delta = choice['delta']
                                if 'content' in delta:
                                    accumulated_text += delta['content']
                                    chunks = chunk_text(accumulated_text)
                                    if len(chunks) > 1:
                                        for complete_chunk in chunks[:-1]:
                                            yield AiAskOutputStream(content=ContentItem(type="text", text=complete_chunk)).model_dump_json(exclude_none=True) + "\n\n"
                                        accumulated_text = chunks[-1]
                                if 'function_call' in delta:
                                    tool_call = delta['function_call']
                                    if tool_call.get('name'):
                                        accumulated_tool_call["name"] = tool_call['name']
                                    if tool_call.get('arguments'):
                                        accumulated_tool_call["arguments"] = accumulated_tool_call.get("arguments", "") + tool_call['arguments']

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
            for attempt in range(retries):
                try:
                    response = await client.post("https://api.openai.com/v1/chat/completions", headers=headers, json=chat_config, timeout=300.0)
                    response.raise_for_status()
                    data = response.json()
                    break
                except httpx.TimeoutException as e:
                    logger.error(f"HTTP Timeout Error: {e}")
                    if attempt < retries - 1:
                        logger.warning(f"Retrying... ({attempt + 1}/{retries})")
                        await asyncio.sleep(2 ** attempt)  # Exponential backoff
                    else:
                        logger.error("Max retries reached. Request failed.")
                        raise
                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 429:
                        error_details = e.response.json()
                        logger.error(f"HTTP 429 Too Many Requests Error: {error_details}")
                        if attempt < retries - 1:
                            retry_after = int(e.response.headers.get("Retry-After", 2 ** attempt))
                            logger.warning(f"Retrying after {retry_after} seconds... ({attempt + 1}/{retries})")
                            await asyncio.sleep(retry_after)
                        else:
                            logger.error("Max retries reached. Request failed.")
                            raise
                    else:
                        error_details = e.response.json()
                        logger.error(f"HTTP Error: {error_details}")
                        raise

            # Process the response content
            content = []
            if data['choices'][0]['message'].get('content'):
                content.append(ContentItem(type="text", text=data['choices'][0]['message']['content']))

            # Handle tool calls
            if data['choices'][0]['message'].get('function_call'):
                tool_call = data['choices'][0]['message']['function_call']
                content.append(ContentItem(
                    type="tool_use",
                    tool_use=ToolUse(
                        id=str(uuid.uuid4()),
                        name=tool_call['name'],
                        input=json.loads(tool_call['arguments'])
                    )
                ))

            return AiAskOutput(
                content=content,
                cost_credits=None
            )
        # .model_dump(exclude_none=True)