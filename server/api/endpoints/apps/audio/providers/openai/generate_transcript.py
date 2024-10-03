import logging
from openai.resources.audio.transcriptions import AsyncTranscriptions, Transcription
from server.api.models.apps.audio.skills_audio_generate_transcript import AudioGenerateTranscriptInput, AudioGenerateTranscriptOutput
logger = logging.getLogger(__name__)

async def generate_transcript(
        input: AudioGenerateTranscriptInput
    ) -> AudioGenerateTranscriptOutput:
    """
    Asynchronously generates a transcript for the given audio bytes.

    Args:
        input (AudioGenerateTranscriptInput): Input data for transcript generation.

    Returns:
        AudioGenerateTranscriptOutput: Output data for transcript generation.
    """
    logger.debug("Starting OpenAI transcript generation for audio data")

    # Create an instance of AsyncTranscriptions
    async_transcriptions = AsyncTranscriptions()

    try:
        if input.stream:
            logger.debug("Processing streamed response...")
            # Use the with_streaming_response property to get a streamed response
            streamed_response = await async_transcriptions.with_streaming_response.create(
                file=input.audio_data,
                model=input.provider.model,
                response_format="text"
            )

            async def stream_generator():
                async for chunk in streamed_response.aiter_content():
                    yield chunk

            return AudioGenerateTranscriptOutput(stream=stream_generator())
        else:
            logger.debug("Processing full response...")
            # Use the create method to get the full response
            full_response: Transcription = await async_transcriptions.create(
                file=input.audio_data,
                model=input.provider.model,
                response_format="text"
            )

            return AudioGenerateTranscriptOutput(text=full_response.text)

    except Exception:
        logger.exception("An error occurred during transcript generation")

    logger.debug("Transcript generation completed for audio data")
