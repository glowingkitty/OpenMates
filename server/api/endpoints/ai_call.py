# backend/endpoints/ai_call.py

import os
import io
import base64
import asyncio
import logging
from typing import Dict
from PIL import Image
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Request, HTTPException
from fastapi.responses import JSONResponse, HTMLResponse
import assemblyai as aai
import openai
from elevenlabs import ElevenLabs, VoiceSettings

router = APIRouter()
logger = logging.getLogger(__name__)

# Initialize API Clients with environment variables
ASSEMBLYAI_API_KEY = os.getenv("ASSEMBLYAI_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")

if not all([ASSEMBLYAI_API_KEY, OPENAI_API_KEY, ELEVENLABS_API_KEY]):
    logger.error("One or more AI service API keys are missing.")
    raise Exception("AI service API keys are not set in environment variables.")

aai.settings.api_key = ASSEMBLYAI_API_KEY
openai.api_key = OPENAI_API_KEY
elevenlabs_client = ElevenLabs(api_key=ELEVENLABS_API_KEY)

# In-memory storage for calls
calls: Dict[str, Dict] = {}
calls_lock = asyncio.Lock()

class MockMicrophoneStream:
    def __init__(self, sample_rate):
        self.sample_rate = sample_rate

    async def __aenter__(self):
        logger.debug("Entering MockMicrophoneStream context")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        logger.debug("Exiting MockMicrophoneStream context")

    async def read(self, num_frames):
        logger.debug(f"Reading {num_frames} frames from MockMicrophoneStream")
        await asyncio.sleep(0.1)  # Simulate delay
        return b'\x00' * num_frames  # Return silence

@router.get("/mates/{matename}/call")
async def get_call_page(matename: str):
    """
    Serve the call.html page for the AI assistant call interface.
    """
    logger.debug(f"Serving call page for mate: {matename}")
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        html_path = os.path.join(base_dir.split('server')[0], 'server', 'frontend', 'static', 'call.html')
        file_path = os.path.abspath(html_path)
        logger.debug(f"Resolved file path: {file_path}")
        with open(file_path, "r") as f:
            html_content = f.read()
        return HTMLResponse(content=html_content, status_code=200)
    except Exception as e:
        logger.error(f"Error serving call page: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")

@router.post("/mates/{matename}/upload_image")
async def upload_image(matename: str, request: Request):
    """
    Receive an image from the frontend.
    """
    logger.debug(f"Uploading image for mate: {matename}")
    data = await request.json()
    image_data = data.get("image")
    if not image_data:
        logger.error("No image data provided.")
        raise HTTPException(status_code=400, detail="No image data provided.")

    async with calls_lock:
        if matename not in calls:
            calls[matename] = {"images": [], "audio_buffer": bytearray(), "websocket": None}
        # Decode base64 image
        try:
            header, encoded = image_data.split(',', 1)
            image = Image.open(io.BytesIO(base64.b64decode(encoded)))
            # Optionally, you can process or resize the image here
            calls[matename]["images"].append(image)
            logger.info(f"Received image for mate: {matename}")
        except Exception as e:
            logger.error(f"Error decoding image: {e}")
            raise HTTPException(status_code=400, detail="Invalid image data.")

    return {"status": "Image received"}

@router.websocket("/ws/mates/{matename}/audio")
async def websocket_audio_endpoint(websocket: WebSocket, matename: str):
    """
    Handle WebSocket connections for audio streaming.
    """
    await websocket.accept()
    logger.info(f"WebSocket connection established for mate: {matename}")
    async with calls_lock:
        if matename not in calls:
            calls[matename] = {"images": [], "audio_buffer": bytearray(), "websocket": websocket, "response_buffer": ""}
        else:
            calls[matename]["websocket"] = websocket

    try:
        while True:
            data = await websocket.receive_bytes()
            logger.debug(f"Received {len(data)} bytes of audio data")
            async with calls_lock:
                calls[matename]["audio_buffer"].extend(data)
            await transcribe_audio(matename)
    except WebSocketDisconnect:
        logger.info(f"WebSocket connection closed for mate: {matename}")
        async with calls_lock:
            if matename in calls:
                del calls[matename]

async def transcribe_audio(matename: str):
    """
    Transcribe audio using AssemblyAI.
    """
    logger.debug(f"Starting transcription for mate: {matename}")
    async with calls_lock:
        audio_buffer = calls[matename]["audio_buffer"]
        calls[matename]["audio_buffer"] = bytearray()

    if not audio_buffer:
        logger.debug("No audio data to transcribe.")
        return

    # Create a RealtimeTranscriber instance
    transcriber = aai.RealtimeTranscriber(
        sample_rate=16000,
        on_data=lambda transcript: asyncio.run(on_data(matename, transcript)),
        on_error=on_error,
        on_open=on_open,
        on_close=on_close,
    )

    # Connect the transcriber
    transcriber.connect()

    # Stream the audio buffer
    microphone_stream = aai.extras.MicrophoneStream(sample_rate=16000)
    transcriber.stream(microphone_stream)

    # Close the transcriber
    transcriber.close()

def on_open(session_opened: aai.RealtimeSessionOpened):
    logger.info(f"Session opened with ID: {session_opened.session_id}")

def on_error(error: aai.RealtimeError):
    logger.error(f"An error occurred: {error}")

def on_close():
    logger.info("Closing Session")

async def on_data(matename: str, transcript: aai.RealtimeTranscript):
    """
    Handle transcription data from AssemblyAI.
    """
    logger.debug(f"Received transcript data for mate: {matename}")
    if not transcript.text:
        return

    if isinstance(transcript, aai.RealtimeFinalTranscript):
        logger.debug(f"Final transcript for mate {matename}: {transcript.text}")
        await stream_ai_response(matename, transcript.text)
    else:
        logger.debug(f"Partial transcript for mate {matename}: {transcript.text}")

async def stream_ai_response(matename: str, transcription: str):
    """
    Stream AI response using OpenAI GPT-4 and ElevenLabs.
    """
    logger.debug(f"Streaming AI response for mate: {matename}")
    try:
        response = await openai.ChatCompletion.acreate(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are an AI assistant. Keep your answers concise."},
                {"role": "user", "content": transcription}
            ],
            temperature=0.7,
            max_tokens=2000,
            n=1,
            stop=None,
            stream=True
        )

        async with calls_lock:
            response_buffer = calls[matename]["response_buffer"]

        async for chunk in response:
            chunk_text = chunk.get('choices')[0].get('delta', {}).get('content', '')
            if chunk_text:
                logger.debug(f"AI response chunk for mate {matename}: {chunk_text}")
                response_buffer += chunk_text

                # Check if the buffer contains a complete sentence or significant chunk
                if '.' in response_buffer or len(response_buffer) > 100:
                    await send_text_to_voice(matename, response_buffer)
                    response_buffer = ""

        # Send any remaining text in the buffer
        if response_buffer:
            await send_text_to_voice(matename, response_buffer)

        async with calls_lock:
            calls[matename]["response_buffer"] = response_buffer

    except Exception as e:
        logger.error(f"OpenAI API error: {e}")

async def send_text_to_voice(matename: str, text: str):
    """
    Convert text to speech using ElevenLabs and send the voice data back to the client.
    """
    logger.debug(f"Converting text to voice for mate: {matename}")
    try:
        async with calls_lock:
            websocket = calls.get(matename, {}).get("websocket")

        if websocket and websocket.application_state == WebSocket.STATE_CONNECTED:
            async for chunk in elevenlabs_client.text_to_speech.convert_as_stream(
                voice_id="pMsXgVXv3BLzUgSXRplE",
                optimize_streaming_latency="0",
                output_format="mp3_22050_32",
                text=text,
                voice_settings=VoiceSettings(
                    stability=0.1,
                    similarity_boost=0.3,
                    style=0.2,
                ),
            ):
                logger.debug(f"Sending voice chunk to mate {matename}")
                await websocket.send_bytes(chunk)
    except Exception as e:
        logger.error(f"Error in text-to-voice conversion or sending voice response: {e}")