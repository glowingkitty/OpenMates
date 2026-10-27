"""Transient, bounded inline images for TypeSafe decision requests."""
from __future__ import annotations

import base64
import binascii
import io
from typing import Annotated, Any, Literal, Mapping

from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_ASSETS = 4
MAX_ASSET_BYTES = 1_048_576
MAX_TOTAL_ASSET_BYTES = 4_194_304
MAX_DECISION_BODY_BYTES = 6_291_456
MAX_ASSET_BASE64_CHARS = 4 * ((MAX_ASSET_BYTES + 2) // 3)
AssetReference = Annotated[str, Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")]


class DecisionImageAsset(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    type: Literal["image"]
    format: Literal["png", "jpg", "jpeg"]
    data_base64: str = Field(min_length=4, max_length=MAX_ASSET_BASE64_CHARS, repr=False)

    @model_validator(mode="after")
    def valid_image(self) -> DecisionImageAsset:
        try:
            decoded = base64.b64decode(self.data_base64, validate=True)
        except (ValueError, binascii.Error):
            raise ValueError("image requires canonical padded standard base64") from None
        if not decoded or len(decoded) > MAX_ASSET_BYTES:
            raise ValueError("image exceeds 1 MiB decoded bytes")
        if base64.b64encode(decoded).decode("ascii") != self.data_base64:
            raise ValueError("image requires canonical padded standard base64")
        try:
            with Image.open(io.BytesIO(decoded)) as image:
                expected = "PNG" if self.format == "png" else "JPEG"
                if image.format != expected:
                    raise ValueError("image format does not match PNG/JPEG content")
                if not all(280 <= side <= 1568 for side in image.size):
                    raise ValueError("image width and height must be 280..1568 pixels")
                if getattr(image, "is_animated", False) or getattr(image, "n_frames", 1) != 1:
                    raise ValueError("only still PNG/JPEG images are supported")
                image.verify()
            with Image.open(io.BytesIO(decoded)) as image:
                image.load()
        except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError):
            raise ValueError("image is not a complete decodable PNG/JPEG") from None
        return self


DecisionAssets = Annotated[dict[AssetReference, DecisionImageAsset], Field(max_length=MAX_ASSETS)]


def _string_values(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for child in value.values():
            yield from _string_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from _string_values(child)


def validate_asset_references(assets: Mapping[str, DecisionImageAsset], state: Any, questions: Any) -> None:
    """Object keys are text; only state/instruction/criterion values use assets."""
    values = tuple(_string_values({"state": state, "questions": [
        {key: value for key, value in question.items() if key in {"instructions", "criteria"}}
        for question in questions.values()
    ]}))
    for reference in assets:
        if not any(reference in value for value in values):
            raise ValueError("every image asset must be referenced in state, instructions, or criteria values")
