"""Editing programs and author input for the images-modify skill.

The author model of ``images.modify`` writes one Python module with
``edit(inputs)`` that computes the result from the original pictures in the
image-edit sandbox (``backend/shared/providers/e2b_image_edit.py`` documents the
exact runtime contract). This module holds everything around that program that
runs in the worker: the dedicated system prompt, extraction and a cheap static
check of the authored code, preparation of the input pictures (exact oriented
sizes, reduced viewing copies) and the messages sent to the author.

The static check is not a security boundary - the sandbox without internet is.
It rejects obviously unusable or escaping code early so the failure feeds a
correction round instead of a sandbox run.
"""

from __future__ import annotations

import ast
import base64
import os
import re
from dataclasses import dataclass
from io import BytesIO
from typing import Any, Optional, Sequence

from backend.shared.providers.e2b_image_edit import (
    MAX_INPUT_BYTES,
    MAX_OUTPUT_SIDE,
    ImageEditInput,
)

MAX_IMAGES = 6
MAX_INSTRUCTION_CHARS = 2000
MAX_SOURCE_PROGRAM_CHARS = 40_000
AUTHOR_PREVIEW_SIDE = 1024
DRAFT_SIDE = 512
DRAFT_MAX_BYTES = 60_000
MAX_SVG_INPUT_SIDE = 4096

ALLOWED_MODULES = frozenset({
    "PIL", "numpy", "cv2", "cairosvg",
    "math", "cmath", "random", "itertools", "functools", "colorsys", "statistics", "io", "re", "json",
    "dataclasses", "typing", "collections", "fractions", "decimal", "operator", "string", "copy", "enum",
    "bisect", "heapq", "textwrap", "unicodedata", "struct", "array", "__future__",
})
_FORBIDDEN_CALLS = frozenset({
    "eval", "exec", "compile", "__import__", "breakpoint", "input", "exit", "quit", "globals", "locals",
    "vars", "setattr", "delattr",
})
_FORBIDDEN_ATTRIBUTES = frozenset({
    "system", "popen", "spawn", "fork", "execv", "execve", "remove", "unlink", "rmtree", "imwrite",
    "show", "urlopen", "__subclasses__", "__globals__", "__builtins__", "__code__", "__bases__", "__mro__",
    "__getattribute__", "__dict__",
})
_CODE_FENCE = re.compile(r"```(?:python|py)?[ \t]*\n([\s\S]*?)```", re.IGNORECASE)
_EDIT_DEF = re.compile(r"^def edit\s*\(", re.MULTILINE)

SYSTEM_PROMPT = f"""You are an expert image-processing programmer. You write one small deterministic Python 3 module that edits pictures exactly as asked.
Return exactly one Python module and nothing else: no prose, no Markdown fence.

Module contract:
- Define `def edit(inputs: list[dict]) -> PIL.Image.Image`. It is called once and returns the one finished picture.
- `inputs` is in the order of the request. Each item: index (1-based), name, kind ("pixel" or "svg"), width and height (exact pixels), image (pixel: a full-resolution PIL image in RGB or RGBA, EXIF orientation already applied; svg: None), svg (svg: the SVG source text; pixel: None).
- Allowed imports: PIL, numpy, cv2, cairosvg and these standard modules: math, random, itertools, functools, colorsys, statistics, io, re, json, collections, dataclasses, typing. Nothing else: no os, sys, pathlib, subprocess, socket, network, threads, sleep, eval/exec, no file writes, no .save() to a path, no cv2.imwrite.
- Deterministic: randomness only through random.Random(<fixed seed>) or numpy.random.default_rng(<fixed seed>).
- Must finish in well under 60 seconds: vectorised numpy/cv2 operations, never Python loops over pixels.

How to edit well:
- The attached pictures are reduced viewing copies; your code works on the full-resolution `image`. Derive every position and size from width/height (fractions of the picture) or from measurements your code makes on the full image, never from pixel coordinates read off the reduced copies.
- Keep everything the request does not ask to change pixel-identical: start from `base = inputs[i]["image"].copy()`, composite onto it, and keep its size unless asked. Never re-encode, blur, resize or recolour the base by accident, and never remove, cover up or paint over existing content of the base (prints, logos, people, text) unless the request asks for it; a new element may overlap what is already there.
- To locate something in a photo (a dark panel, a subject, a horizon, a face area) measure it in code - thresholds, masks, connected components, contours, row and column profiles with numpy/cv2 - restricted to the region where the request says it is, then clamp results to the picture.
- Overlays: scale with Image.LANCZOS, rotate RGBA with expand=True and resample=Image.BICUBIC, and composite with Image.alpha_composite or paste(..., mask=alpha). Convert the base to RGBA only for compositing.
- A picture placed onto another keeps its own background and is placed whole, unless the request asks to remove the background, cut the subject out or place only the motif. A logo or motif meant to sit directly on a surface (a print on a shirt, a sticker on a product) counts as such a request.
- Removing a plain background from a motif: first crop away borders and bars that are not part of the motif (for example uniform dark or light strips of a screenshot), then build an alpha mask from the colour distance to the background colour sampled at the crop's edges, with a soft ramp instead of a hard cut. Then remove the fringe: un-mix the background colour from semi-transparent pixels (colour = (pixel - background * (1 - alpha)) / alpha) and, after scaling to the final size, shrink the alpha by about 1 px; a thin light outline around the motif on a dark base is a visible defect. Keep the motif's parts (also inner holes become transparent) and crop to its bounding box.
- Embroidery stitch previews are RGBA with a transparent background already: use their alpha as is.
- SVG input: rasterise directly at the final pixel size with cairosvg.svg2png(bytestring=svg.encode("utf-8"), output_width=<px>) and open it with Image.open(io.BytesIO(png)).convert("RGBA"); never upscale a small rendering.
- Collages and layouts: never stretch. Pictures with different aspect ratios cannot all fill equal cells: either crop each to fill its cell (only when cropping is acceptable) or, when every picture must stay whole, derive the cell sizes from the pictures' aspect ratios (justified rows or columns, then a canvas size that follows from them) so the stated gaps stay exactly equal and no uneven empty space is left.
- Colour and tone changes: apply them with numpy or PIL.ImageEnhance on the whole picture or a mask, clip to 0-255 and keep uint8.
- Text: ImageFont.truetype with "DejaVuSans.ttf", "DejaVuSans-Bold.ttf", "LiberationSans-Regular.ttf" or "NotoSans-Regular.ttf", sized from the picture.
- Output: return RGB for a jpg result and RGB or RGBA for a png result; the longest side at most {MAX_OUTPUT_SIDE} px.
- Put the tunable values (positions as fractions, sizes, colours, strengths) as named constants at the top so the edit is easy to change later.
- When given an existing program to change: keep everything that was not asked to change and return the full updated module; it runs again on the original inputs."""


class ModifyInputError(ValueError):
    """The request's pictures or instructions are outside the limits; nothing is run or charged."""


class InvalidProgramError(ValueError):
    """The authored text is not a usable editing program for the sandbox."""


@dataclass(frozen=True)
class PreparedInput:
    """One input picture: the sandbox upload plus the reduced copy the author and reviewer see."""

    upload: ImageEditInput
    preview: bytes
    preview_mime: str
    has_alpha: bool


def extract_program(text: str) -> Optional[str]:
    """Return the Python module in model output, if it defines ``edit``."""
    fenced = _CODE_FENCE.search(text)
    code = (fenced.group(1) if fenced else text).strip()
    return code if _EDIT_DEF.search(code) else None


def _is_write_mode(node: ast.Call) -> bool:
    mode: Any = None
    if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
        mode = node.args[1].value
    for keyword in node.keywords:
        if keyword.arg == "mode":
            mode = keyword.value.value if isinstance(keyword.value, ast.Constant) else "?"
    if len(node.args) >= 2 and not isinstance(node.args[1], ast.Constant):
        mode = "?"
    return isinstance(mode, str) and any(flag in mode for flag in "wax+?")


def validate_program(code: str) -> str:
    """Parse the program and reject imports outside the allow-list and obvious escapes."""
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        raise InvalidProgramError(f"the program is not valid Python (line {exc.lineno}: {exc.msg})") from exc
    if not any(isinstance(node, ast.FunctionDef) and node.name == "edit" for node in tree.body):
        raise InvalidProgramError("the program must define a top-level function edit(inputs)")
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                raise InvalidProgramError("relative imports are not allowed")
            names = [node.module or ""]
        else:
            names = []
        for name in names:
            if name.split(".", 1)[0] not in ALLOWED_MODULES:
                raise InvalidProgramError(f"import of {name!r} is not allowed; use only PIL, numpy, cv2, cairosvg "
                                          "and the listed standard modules")
        if isinstance(node, ast.Name) and node.id in _FORBIDDEN_CALLS:
            raise InvalidProgramError(f"{node.id} is not allowed")
        if isinstance(node, ast.Attribute) and node.attr in _FORBIDDEN_ATTRIBUTES:
            raise InvalidProgramError(f".{node.attr} is not allowed")
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == "open" and _is_write_mode(node):
                raise InvalidProgramError("writing files is not allowed; return the picture from edit()")
            if (isinstance(func, ast.Attribute) and func.attr == "save" and node.args
                    and isinstance(node.args[0], (ast.Constant, ast.JoinedStr))):
                raise InvalidProgramError("saving to a file path is not allowed; return the picture from edit()")
    return code


def _oriented(image: Any) -> Any:
    from PIL import ImageOps

    return ImageOps.exif_transpose(image)


def _encode_preview(image: Any, side: int, *, alpha: bool) -> tuple[bytes, str]:
    from PIL import Image

    copy = image.convert("RGBA" if alpha else "RGB")
    copy.thumbnail((side, side), Image.LANCZOS)
    output = BytesIO()
    if alpha:
        copy.save(output, format="PNG", optimize=True)
        return output.getvalue(), "image/png"
    copy.save(output, format="JPEG", quality=85)
    return output.getvalue(), "image/jpeg"


def _svg_size(svg: bytes) -> tuple[int, int, bytes]:
    import cairosvg
    from PIL import Image

    try:
        png = cairosvg.svg2png(bytestring=svg, unsafe=False)
        with Image.open(BytesIO(png)) as natural:
            width, height = natural.size
        scale = AUTHOR_PREVIEW_SIDE / max(width, height)
        png = cairosvg.svg2png(bytestring=svg, output_width=max(1, round(width * scale)),
                               output_height=max(1, round(height * scale)), unsafe=False)
    except (ValueError, OSError, SyntaxError) as exc:
        raise ModifyInputError(f"the vector graphic could not be read ({exc})") from exc
    return width, height, png


def prepare_input(name: str, data: bytes, kind: str) -> PreparedInput:
    """Measure one picture (oriented pixel size) and make its reduced viewing copy."""
    if not data:
        raise ModifyInputError(f"the picture {name!r} is empty")
    if len(data) > MAX_INPUT_BYTES:
        raise ModifyInputError(f"the picture {name!r} is larger than {MAX_INPUT_BYTES // 1048576} MB")
    if kind == "svg":
        width, height, preview = _svg_size(data)
        if max(width, height) > MAX_SVG_INPUT_SIDE:
            width, height = (round(width * MAX_SVG_INPUT_SIDE / max(width, height)),
                             round(height * MAX_SVG_INPUT_SIDE / max(width, height)))
        upload = ImageEditInput(name=name, data=data, kind="svg", width=width, height=height, extension="svg")
        return PreparedInput(upload=upload, preview=preview, preview_mime="image/png", has_alpha=True)
    if kind != "pixel":
        raise ModifyInputError(f"unknown picture kind {kind!r}")
    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(BytesIO(data)) as source:
            source.load()
            image_format = (source.format or "").lower()
            oriented = _oriented(source)
            alpha = oriented.mode in ("RGBA", "LA", "PA") or "transparency" in oriented.info
            width, height = oriented.size
            preview, mime = _encode_preview(oriented, AUTHOR_PREVIEW_SIDE, alpha=alpha)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ModifyInputError(f"the picture {name!r} could not be read") from exc
    extension = {"jpeg": "jpg", "mpo": "jpg"}.get(image_format, image_format)
    if extension not in {"png", "jpg", "webp", "gif", "bmp", "tiff"}:
        raise ModifyInputError(f"the picture {name!r} has an unsupported format {image_format or 'unknown'}")
    upload = ImageEditInput(name=name, data=data, kind="pixel", width=width, height=height, extension=extension)
    return PreparedInput(upload=upload, preview=preview, preview_mime=mime, has_alpha=alpha)


def prepare_inputs(pictures: Sequence[tuple[str, bytes, str]]) -> list[PreparedInput]:
    """Validate the request's pictures ``(name, bytes, kind)`` and prepare them in order."""
    if not pictures:
        raise ModifyInputError("at least one picture is needed")
    if len(pictures) > MAX_IMAGES:
        raise ModifyInputError(f"at most {MAX_IMAGES} pictures can be combined")
    return [prepare_input(name, data, kind) for name, data, kind in pictures]


def reduced_jpeg(image_bytes: bytes, side: int = DRAFT_SIDE, max_bytes: int = DRAFT_MAX_BYTES) -> bytes:
    """Return a small JPEG copy of a computed picture (transparency shown on light grey)."""
    from PIL import Image

    with Image.open(BytesIO(image_bytes)) as source:
        rgba = source.convert("RGBA")
    rgba.thumbnail((side, side), Image.LANCZOS)
    flat = Image.new("RGB", rgba.size, (225, 225, 225))
    flat.paste(rgba, mask=rgba.getchannel("A"))
    for quality in (82, 70, 58, 46, 34):
        output = BytesIO()
        flat.save(output, format="JPEG", quality=quality)
        if output.tell() <= max_bytes:
            break
    return output.getvalue()


def _image_block(content: bytes, mime_type: str) -> dict[str, Any]:
    encoded = base64.b64encode(content).decode("ascii")
    return {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{encoded}"}}


def describe_inputs(inputs: Sequence[PreparedInput]) -> str:
    """One line per input with its order, kind, exact size and transparency."""
    lines = []
    for index, item in enumerate(inputs, start=1):
        upload = item.upload
        stem = os.path.splitext(upload.name)[0][:60]
        kind = "vector graphic (SVG source in `svg`)" if upload.kind == "svg" else (
            "picture with transparency (RGBA)" if item.has_alpha else "picture (RGB)")
        lines.append(f"- inputs[{index - 1}] (index {index}, {stem!r}): {kind}, {upload.width} x {upload.height} px; "
                     f"attached copy {index} is reduced to fit {AUTHOR_PREVIEW_SIDE} px")
    return "\n".join(lines)


def build_author_message(
    *, instructions: str, requirements: Sequence[str], inputs: Sequence[PreparedInput], output_type: str,
    source_program: Optional[str] = None,
) -> dict[str, Any]:
    """Build the single user message that carries the whole editing request."""
    parts = [f"Request: {instructions.strip()}", "Input pictures, in order:\n" + describe_inputs(inputs),
             f"Result file type: {output_type}."]
    if requirements:
        parts.append("Requirements (each one must hold in the result):\n"
                     + "\n".join(f"- {item}" for item in requirements))
    if source_program:
        parts.append("Existing program to change (it produced the previous result from these same original "
                     f"inputs; change only what the request asks):\n{source_program[:MAX_SOURCE_PROGRAM_CHARS]}")
    blocks: list[dict[str, Any]] = [{"type": "text", "text": "\n\n".join(parts)}]
    for item in inputs:
        blocks.append(_image_block(item.preview, item.preview_mime))
    return {"role": "user", "content": blocks}


def build_correction_message(*, feedback: str, computed_preview: Optional[bytes]) -> dict[str, Any]:
    """Build the user message of a correction round: the reason and, if any, the computed picture."""
    if computed_preview:
        text = (f"The computed result (attached, reduced) has a problem: {feedback}. Look at it, find the cause in "
                "your program and fix only that; keep everything else in the program as it is. Do not edit more of "
                "the base picture than the request asks in order to satisfy a check. Return the complete corrected "
                "Python module only.")
        return {"role": "user", "content": [{"type": "text", "text": text},
                                            _image_block(computed_preview, "image/jpeg")]}
    return {"role": "user", "content": f"Running the program failed: {feedback}. Return the complete corrected "
                                       "Python module only."}
