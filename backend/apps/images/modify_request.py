"""Request contract of the images.modify skill (Specification feature.app-skill.images-modify).

``parse_modify_request`` is the single validation of a call. The skill runs it
before anything is queued and the task runs it again on the queued arguments,
so a call outside the limits fails explicitly before any model, sandbox or
charge is involved.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from backend.apps.images.modify_program import MAX_IMAGES, MAX_INSTRUCTION_CHARS

MAX_REQUIREMENTS = 8
MAX_REQUIREMENT_CHARS = 300
OUTPUT_FILETYPES = ("png", "jpg")
DEFAULT_OUTPUT_FILETYPE = "png"


class ModifyRequestError(ValueError):
    """The call is outside the request contract; nothing is queued, run or charged."""


@dataclass(frozen=True)
class ModifyRequest:
    """A validated call: instructions, the picture references in order, requirements and file type."""

    instructions: str
    images: tuple[str, ...]
    requirements: tuple[str, ...]
    output_filetype: str


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise ModifyRequestError(f"{field} must be text")
    return " ".join(value.split())


def parse_modify_request(
    *, instructions: Any, images: Any, requirements: Any = None, output_filetype: Any = None,
) -> ModifyRequest:
    """Validate one images.modify call; raise ``ModifyRequestError`` with a plain reason."""
    text = _text(instructions, "instructions") if instructions is not None else ""
    if not text:
        raise ModifyRequestError("instructions are required: say exactly what should be done with the pictures")
    if len(text) > MAX_INSTRUCTION_CHARS:
        raise ModifyRequestError(f"instructions are longer than {MAX_INSTRUCTION_CHARS} characters")

    if not isinstance(images, (list, tuple)) or not images:
        raise ModifyRequestError("images is required: pass the embed_ref of at least one picture from this chat")
    if len(images) > MAX_IMAGES:
        raise ModifyRequestError(f"at most {MAX_IMAGES} pictures can be combined in one images.modify call")
    refs: list[str] = []
    for value in images:
        if not isinstance(value, str) or not value.strip():
            raise ModifyRequestError("every entry of images must be the embed_ref of a picture from this chat")
        refs.append(value.strip())

    wanted: list[str] = []
    if requirements is not None:
        if not isinstance(requirements, (list, tuple)):
            raise ModifyRequestError("requirements must be a list of short sentences")
        for value in requirements:
            item = _text(value, "every requirement")
            if not item:
                continue
            if len(item) > MAX_REQUIREMENT_CHARS:
                raise ModifyRequestError(f"a requirement is longer than {MAX_REQUIREMENT_CHARS} characters")
            wanted.append(item)
        if len(wanted) > MAX_REQUIREMENTS:
            raise ModifyRequestError(f"at most {MAX_REQUIREMENTS} requirements can be checked")

    filetype: Optional[str] = DEFAULT_OUTPUT_FILETYPE if output_filetype in (None, "") else output_filetype
    filetype = str(filetype).strip().lower()
    if filetype == "jpeg":
        filetype = "jpg"
    if filetype not in OUTPUT_FILETYPES:
        raise ModifyRequestError("output_filetype must be png or jpg")
    return ModifyRequest(instructions=text, images=tuple(refs), requirements=tuple(wanted), output_filetype=filetype)
