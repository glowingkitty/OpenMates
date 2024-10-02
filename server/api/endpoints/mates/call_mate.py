import logging
from fastapi import WebSocket, WebSocketDisconnect
from typing import Literal
import assemblyai as aai
import os
import websockets
import json
import base64

logger = logging.getLogger(__name__)

logging.getLogger('websockets').setLevel(logging.WARNING)

async def call_custom_processing(
        websocket: WebSocket,
        team_slug: str
    ):
    await websocket.accept()
    logger.info("WebSocket connection accepted for transcription.")

    # Initialize AssemblyAI API key
    ASSEMBLYAI_API_KEY = os.getenv("ASSEMBLYAI_API_KEY")
    if not ASSEMBLYAI_API_KEY:
        logger.error("ASSEMBLYAI_API_KEY is not set.")
        raise Exception("ASSEMBLYAI_API_KEY not set in environment variables.")

    aai.settings.api_key = ASSEMBLYAI_API_KEY

    def on_open(session_opened: aai.RealtimeSessionOpened):
        logger.info(f"Transcription session opened: {session_opened.session_id}")

    def on_data(transcript: aai.RealtimePartialTranscript):
        if transcript.text:
            if isinstance(transcript, aai.RealtimeFinalTranscript):
                logger.info("User stopped talking.")
                logger.info(f"Full transcribed text: {transcript.text}")

    def on_error(error: aai.RealtimeError):
        logger.error(f"Transcription error: {error}")

    def on_close():
        logger.info("Transcription session closed.")

    transcriber = aai.RealtimeTranscriber(
        sample_rate=48000,
        on_data=on_data,
        on_error=on_error,
        on_open=on_open,
        on_close=on_close,
    )

    transcriber.connect()

    try:
        while True:
            data = await websocket.receive_bytes()
            # Send audio data to AssemblyAI for transcription
            transcriber.stream(data)
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected.")
    except Exception as e:
        logger.error(f"WebSocket connection error: {e}")
    finally:
        transcriber.close()


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