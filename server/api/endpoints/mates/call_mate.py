import logging
from fastapi import WebSocket, WebSocketDisconnect
import assemblyai as aai
import os

logger = logging.getLogger(__name__)

# Initialize AssemblyAI API key
ASSEMBLYAI_API_KEY = os.getenv("ASSEMBLYAI_API_KEY")
if not ASSEMBLYAI_API_KEY:
    logger.error("ASSEMBLYAI_API_KEY is not set.")
    raise Exception("ASSEMBLYAI_API_KEY not set in environment variables.")

aai.settings.api_key = ASSEMBLYAI_API_KEY

def on_open(session_opened: aai.RealtimeSessionOpened):
    logger.info(f"Transcription session opened: {session_opened.session_id}")

def on_data(transcript: aai.RealtimeTranscript):
    if transcript.text:
        logger.debug(f"Transcribed text: {transcript.text}")

def on_error(error: aai.RealtimeError):
    logger.error(f"Transcription error: {error}")

def on_close():
    logger.info("Transcription session closed.")


async def call_mate(
        websocket: WebSocket,
        team_slug: str
    ):
    await websocket.accept()
    logger.info("WebSocket connection accepted for transcription.")

    transcriber = aai.RealtimeTranscriber(
        sample_rate=16000,
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