"""Provider-neutral caption data returned by the media.ccc.de wrapper."""

from pydantic import BaseModel, Field


class Caption(BaseModel):
    start: float = Field(ge=0)
    duration: float = Field(gt=0)
    text: str


class MediaCCCTranscript(BaseModel):
    title: str
    language: str
    captions: list[Caption]
