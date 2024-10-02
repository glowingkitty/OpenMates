import logging
from fastapi import WebSocket, WebSocketDisconnect
from typing import Literal
import assemblyai as aai
import os
import websockets
import json
import base64
import asyncio
import httpx  # New asynchronous HTTP client

logger = logging.getLogger(__name__)

logging.getLogger('websockets').setLevel(logging.WARNING)

async def call_custom_processing(
        websocket: WebSocket,
        team_slug: str
    ):
    await websocket.accept()
    logger.info("WebSocket connection accepted for transcription.")

    # Obtain the current running event loop
    loop = asyncio.get_running_loop()

    # Initialize AssemblyAI API key
    ASSEMBLYAI_API_KEY = os.getenv("ASSEMBLYAI_API_KEY")
    if not ASSEMBLYAI_API_KEY:
        logger.error("ASSEMBLYAI_API_KEY is not set.")
        raise Exception("ASSEMBLYAI_API_KEY not set in environment variables.")

    aai.settings.api_key = ASSEMBLYAI_API_KEY

    # Add system message to message history
    message_history = [{"role": "system", "content": "You are a helpful assistant. Keep your responses concise."}]
    current_task = None

    def on_open(session_opened: aai.RealtimeSessionOpened):
        logger.info(f"Transcription session opened: {session_opened.session_id}")

    def on_data(transcript: aai.RealtimePartialTranscript):
        nonlocal current_task
        if transcript.text:
            if isinstance(transcript, aai.RealtimeFinalTranscript):
                logger.info("User stopped talking.")
                logger.info(f"Full transcribed text: {transcript.text}")
                message_history.append({"role": "user", "content": transcript.text})
                if current_task:
                    current_task.cancel()
                # Schedule the async task using run_coroutine_threadsafe
                future = asyncio.run_coroutine_threadsafe(
                    send_to_gpt4o_mini(message_history),
                    loop
                )
                try:
                    # Optionally handle the result or exceptions
                    future.result()
                except Exception as e:
                    logger.error(f"Error scheduling send_to_gpt4o_mini: {e}")

    def on_error(error: aai.RealtimeError):
        logger.error(f"Transcription error: {error}")

    def on_close():
        logger.info("Transcription session closed.")

    transcriber = aai.RealtimeTranscriber(
        sample_rate=48000,
        on_data=on_data,  # Changed to synchronous
        on_error=on_error,
        on_open=on_open,
        on_close=on_close,
    )

    await asyncio.to_thread(transcriber.connect)

    async def send_to_gpt4o_mini(history):
        api_key = os.getenv('OPENAI_API_KEY')
        if not api_key:
            logger.error("OPENAI_API_KEY is not set.")
            raise Exception("OPENAI_API_KEY not set in environment variables.")

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": "gpt-4o-mini",
            "temperature": 0.5,
            "messages": history,
            "max_tokens": 1000,
            "stream": True
        }

        logger.debug(f"Sending payload to OpenAI: {payload}")
        logger.debug(f"With headers: {headers}")

        async with httpx.AsyncClient() as client:
            try:
                async with client.stream("POST", "https://api.openai.com/v1/chat/completions", headers=headers, json=payload) as response:
                    accumulated_text = ""
                    buffer = ""
                    async for chunk in response.aiter_text():
                        buffer += chunk.strip().replace("data: ", "")
                        while buffer:
                            try:
                                data, index = json.JSONDecoder().raw_decode(buffer)
                                buffer = buffer[index:].strip()  # Remove the processed part from the buffer
                                if 'choices' in data:
                                    choice = data['choices'][0]
                                    if 'delta' in choice:
                                        delta = choice['delta']
                                        if 'content' in delta:
                                            accumulated_text += delta['content']
                                            logger.debug(f"Accumulated text: {accumulated_text}")
                            except json.JSONDecodeError:
                                # Incomplete JSON, continue accumulating
                                break
            except asyncio.CancelledError:
                logger.info("Request to OpenAI was cancelled.")
            except Exception as e:
                logger.error(f"Error during OpenAI request: {e}")

    try:
        while True:
            data = await websocket.receive_bytes()
            # Cancel any ongoing request to OpenAI if the user starts talking again
            if current_task:
                current_task.cancel()
            # Send audio data to AssemblyAI for transcription
            await asyncio.to_thread(transcriber.stream, data)
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected.")
    except Exception as e:
        logger.error(f"WebSocket connection error: {e}")
    finally:
        # Correctly close the transcriber without awaiting
        await asyncio.to_thread(transcriber.close)
        # Removed the incorrect await transcriber.close()


async def call_chatgpt_processing(
        websocket: WebSocket,
        team_slug: str
    ):
    await websocket.accept()
    logger.info("WebSocket connection accepted for ChatGPT processing.")

    url = "wss://api.openai.com/v1/realtime?model=gpt-4o-realtime-preview-2024-10-01"
    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key:
        logger.error("OPENAI_API_KEY is not set.")
        raise Exception("OPENAI_API_KEY not set in environment variables.")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "OpenAI-Beta": "realtime=v1",
    }

    logger.debug(f"Connecting to {url} with headers: {headers}")

    try:
        async with websockets.connect(url, extra_headers=headers) as ws:
            logger.info("Connected to OpenAI Realtime API.")

            try:
                while True:
                    data = await websocket.receive_bytes()
                    # Encode audio data to base64
                    encoded_audio = base64.b64encode(data).decode('utf-8')
                    event = {
                        "type": "conversation.item.create",
                        "item": {
                            "type": "message",
                            "role": "user",
                            "content": [{
                                "type": "input_audio",
                                "audio": encoded_audio
                            }]
                        }
                    }
                    await ws.send(json.dumps(event))
                    response = await ws.recv()
                    logger.debug(f"Received response: {response}")
                    # Process the response as needed
            except WebSocketDisconnect:
                logger.info("WebSocket disconnected.")
            except Exception as e:
                logger.error(f"WebSocket connection error: {e}")
            finally:
                await ws.close()
    except websockets.exceptions.InvalidStatusCode as e:
        logger.error(f"WebSocket connection failed with status code: {e.status_code}")
        logger.error(f"Response headers: {e.headers}")


async def call_mate(
        websocket: WebSocket,
        team_slug: str,
        provider: Literal["chatgpt_advanced_voice_mode", "custom"] = "custom"
    ):
    if provider == "chatgpt_advanced_voice_mode":
        # TODO not working yet. Currently getting 403 error. Seems they are still working on scaling up access.
        await call_chatgpt_processing(websocket, team_slug)
    elif provider == "custom":
        await call_custom_processing(websocket, team_slug)
    else:
        raise ValueError(f"Invalid provider: {provider}")