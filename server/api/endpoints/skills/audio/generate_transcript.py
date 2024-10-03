import logging
from server.api.models.skills.audio.skills_audio_generate_transcript import SkillsAudioGenerateTranscriptInput, SkillsAudioGenerateTranscriptOutput
from server.api.endpoints.skills.audio.providers.openai.generate_transcript import generate_transcript as generate_transcript_openai
from server.api.endpoints.skills.audio.providers.assemblyai.generate_transcript import generate_transcript as generate_transcript_assemblyai

# Configure logger
logger = logging.getLogger(__name__)


async def generate_transcript(
        input: SkillsAudioGenerateTranscriptInput
    ) -> SkillsAudioGenerateTranscriptOutput:
    """
    Generate a transcript based on the provided input.

    Args:
        input (SkillsAudioGenerateTranscriptInput): The input data containing audio and provider information.

    Returns:
        SkillsAudioGenerateTranscriptOutput: The output data containing the generated transcript.
    """
    logger.debug("Starting transcript generation process.")

    # Check which provider is specified in the input
    if input.provider.name == "openai":
        logger.debug("Provider 'openai' selected.")
        # Call the OpenAI transcript generation function
        return await generate_transcript_openai(input)
    elif input.provider.name == "assemblyai":
        logger.debug("Provider 'assemblyai' selected.")
        # Call the AssemblyAI transcript generation function
        return await generate_transcript_assemblyai(input)
    else:
        # Log and raise an error if the provider is invalid
        error_message = f"Invalid provider: {input.provider.name}"
        logger.error(error_message)
        raise ValueError(error_message)
