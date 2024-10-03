import logging
import assemblyai as aai
import asyncio
from server.api.models.skills.audio.skills_audio_generate_transcript import SkillsAudioGenerateTranscriptInput, SkillsAudioGenerateTranscriptOutput

logger = logging.getLogger(__name__)

async def generate_transcript(
        input: SkillsAudioGenerateTranscriptInput
    ) -> SkillsAudioGenerateTranscriptOutput:
    """
    Asynchronously generates a transcript for the given audio bytes using AssemblyAI.

    Args:
        input (SkillsAudioGenerateTranscriptInput): Input data for transcript generation.

    Returns:
        SkillsAudioGenerateTranscriptOutput: Output data for transcript generation.
    """
    logger.debug("Starting AssemblyAI transcript generation for audio data")

    # Initialize AssemblyAI API key
    ASSEMBLYAI_API_KEY = input.provider.api_key
    if not ASSEMBLYAI_API_KEY:
        logger.error("ASSEMBLYAI_API_KEY is not set.")
        raise Exception("ASSEMBLYAI_API_KEY not set in input provider.")

    aai.settings.api_key = ASSEMBLYAI_API_KEY

    try:
        if input.stream:
            logger.debug("Processing streamed response...")
            # Initialize the RealtimeTranscriber
            transcriber = aai.RealtimeTranscriber(
                sample_rate=16000,
                on_data=lambda transcript: logger.debug(f"Received transcript chunk: {transcript.text}"),
                on_error=lambda error: logger.error(f"Transcription error: {error}"),
                on_open=lambda session: logger.info(f"Transcription session opened: {session.session_id}"),
                on_close=lambda: logger.info("Transcription session closed.")
            )

            # Connect to the real-time service
            await asyncio.to_thread(transcriber.connect)

            # Use a queue to collect transcript chunks
            transcript_queue = asyncio.Queue()

            def on_data(transcript):
                # Put the transcript text into the queue
                asyncio.run_coroutine_threadsafe(transcript_queue.put(transcript.text), asyncio.get_event_loop())

            # Update the transcriber with the on_data callback
            transcriber._impl._on_data = on_data

            async def stream_generator():
                try:
                    # Stream audio data
                    transcriber.stream(input.audio_data)
                    # Yield chunks as they are received
                    while True:
                        chunk = await transcript_queue.get()
                        yield chunk
                finally:
                    # Ensure the connection is closed
                    transcriber.close()

            return SkillsAudioGenerateTranscriptOutput(stream=stream_generator())
        else:
            logger.debug("Processing full response...")

            # Initialize the Transcriber with the API key
            transcriber = aai.Transcriber(client=aai._client.Client(api_key=ASSEMBLYAI_API_KEY))

            # Use the transcribe method to get the full response
            response = transcriber.transcribe(data=input.audio_data)

            return SkillsAudioGenerateTranscriptOutput(text=response.text)

    except Exception:
        logger.exception("An error occurred during transcript generation")

    logger.debug("Transcript generation completed for audio data")
