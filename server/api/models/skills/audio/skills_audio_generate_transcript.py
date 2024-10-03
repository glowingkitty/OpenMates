from pydantic import BaseModel, Field, model_validator
from typing import Literal, Optional, AsyncGenerator


# POST /skill/audio/generate_transcript (generate transcript from audio file)

class AudioTranscriptAiProvider(BaseModel):
    name: Literal["openai","assemblyai"] = Field(..., title="Provider Name", description="Name of the AI provider")
    model: Literal["whisper-1","whisper-large-v3-turbo", "assemblyai"] = Field(..., title="Model", description="Specific model of the AI provider")

    @model_validator(mode='after')
    def validate_model(self):
        valid_models = {
            "openai": ["whisper-1","whisper-large-v3-turbo"],
            "assemblyai": ["assemblyai"]
        }
        if self.name not in valid_models:
            raise ValueError(f"Invalid provider: {self.name}")
        if self.model not in valid_models[self.name]:
            raise ValueError(f"Invalid model '{self.model}' for provider '{self.name}'. Valid models are: {', '.join(valid_models[self.name])}")
        return self


class AudioGenerateTranscriptInput(BaseModel):
    audio_data: bytes = Field(..., description="The audio data to generate a transcript for")
    provider: AudioTranscriptAiProvider = Field(..., description="The provider to use for generating the transcript")
    stream: bool = Field(False, description="Whether to stream the transcript")


class AudioGenerateTranscriptOutput(BaseModel):
    text: Optional[str] = Field(None, description="The transcript of the audio data")