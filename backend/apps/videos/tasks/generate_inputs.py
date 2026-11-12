"""The pictures of one videos.generate request, read server-side (assertion videos-generate.inputs).

Each picture is an exact embed id the skill resolved from the conversation. It
is one of:

- a search result (image, web, news or video search): readable only through
  its Vault-encrypted cache copy; its public picture address is fetched once in
  full size through the SSRF-safe public image reader (20 MB, longest side at
  most 2560 px) and its title is kept;
- an owned picture (upload in its window, generated image, vector graphic,
  embroidery preview): read like images.modify reads its inputs.

Anything else fails the request explicitly (``VideoInputUnavailable``); there is
no substitute picture.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass
from io import BytesIO
from typing import Any, Mapping, Optional, Sequence

import httpx

from backend.apps.videos.composed.models import ComposedInput
from backend.shared.python_utils.owned_pictures import KIND_SVG, ReferenceImageUnavailable, load_owned_pictures
from backend.shared.python_utils.public_images import (
    MAX_FULL_SIDE,
    FullPublicImage,
    download_public_image_full,
    prepare_full_image,
)
from backend.shared.python_utils.result_pictures import (
    ContentReader,
    ResultPictureUnavailable,
    picture_url,
    read_result_picture,
    vault_content_reader,
)

logger = logging.getLogger(__name__)

KIND_RESULT = "search_result"
KIND_IMAGE = "image"
KIND_VECTOR = "vector_graphic"
_SVG_MIN_SIDE = 1920


class VideoInputUnavailable(RuntimeError):
    """A picture of the request could not be read or used; nothing is made or charged."""


@dataclass(frozen=True)
class PictureRef:
    """One requested picture: its embed id, its ref in the chat and, once read, what kind it is."""

    embed_id: str
    ref: str
    kind: str  # search_result | image (an owned picture, kind known after loading)


def _is_result_content(content: Mapping[str, Any]) -> bool:
    """A search-result card: a picture address and no stored file of its own."""
    return picture_url(content) is not None and not content.get("files") and not content.get("s3_base_url")


def task_reader(task: Any, vault_key_id: str) -> ContentReader:
    return vault_content_reader(cache_service=task._cache_service, encryption_service=task._encryption_service,
                                user_vault_key_id=vault_key_id)


async def classify_pictures(embed_ids: Sequence[str], refs: Sequence[str], *, read_content: ContentReader
                            ) -> list[PictureRef]:
    """Tell search results from owned pictures (a result is read from its server-readable cache copy)."""
    if len(embed_ids) != len(refs):
        raise ValueError("every picture needs its reference")
    pictures: list[PictureRef] = []
    for embed_id, ref in zip(embed_ids, refs):
        loaded = await read_content(embed_id)
        is_result = loaded is not None and _is_result_content(loaded[1])
        pictures.append(PictureRef(embed_id=embed_id, ref=ref, kind=KIND_RESULT if is_result else KIND_IMAGE))
    return pictures


def _rasterize_svg(svg: bytes) -> FullPublicImage:
    import cairosvg
    from PIL import Image

    png = cairosvg.svg2png(bytestring=svg, unsafe=False)
    with Image.open(BytesIO(png)) as image:
        width, height = image.size
    longest = max(width, height, 1)
    if longest < _SVG_MIN_SIDE or longest > MAX_FULL_SIDE:
        scale = min(MAX_FULL_SIDE, max(_SVG_MIN_SIDE, min(longest, MAX_FULL_SIDE))) / longest
        png = cairosvg.svg2png(bytestring=svg, output_width=max(1, round(width * scale)),
                               output_height=max(1, round(height * scale)), unsafe=False)
    return prepare_full_image(png)


def _extension(mime_type: str) -> str:
    return "png" if mime_type == "image/png" else "jpg"


async def load_composed_inputs(
    task: Any, *, pictures: Sequence[PictureRef], user_id: str, vault_key_id: str, s3_service: Any, bucket: str,
    log_prefix: str, read_content: Optional[ContentReader] = None,
) -> tuple[list[ComposedInput], list[str]]:
    """Every picture in request order at full size, named for the sandbox; plus the pictures' kinds."""
    reader = read_content or task_reader(task, vault_key_id)
    owner_hash = hashlib.sha256(user_id.encode("utf-8")).hexdigest()
    inputs: list[ComposedInput] = []
    kinds: list[str] = []
    for index, picture in enumerate(pictures, start=1):
        title = ""
        try:
            if picture.kind == KIND_RESULT:
                result = await read_result_picture(picture.embed_id, read_content=reader, owner_hash=owner_hash)
                try:
                    full = await download_public_image_full(result.url)
                except (httpx.HTTPError, OSError, TimeoutError) as exc:
                    raise ResultPictureUnavailable(
                        f"The picture of search result {picture.ref!r} could not be downloaded from its site."
                    ) from exc
                title, kind, input_kind = result.title, KIND_RESULT, "search_result"
            else:
                [owned] = await load_owned_pictures(
                    task, embed_ids=[picture.embed_id], refs=[picture.ref], user_id=user_id,
                    user_vault_key_id=vault_key_id, s3_service=s3_service, bucket=bucket, log_prefix=log_prefix,
                )
                if owned.kind == KIND_SVG:
                    full = await asyncio.to_thread(_rasterize_svg, owned.data)
                    kind = KIND_VECTOR
                else:
                    full = await asyncio.to_thread(prepare_full_image, owned.data)
                    kind = KIND_IMAGE
                title, input_kind = owned.name, "image"
        except (ResultPictureUnavailable, ReferenceImageUnavailable) as exc:
            logger.info("%s Picture %s unavailable: %s", log_prefix, picture.embed_id[:8], exc)
            raise VideoInputUnavailable(str(exc)) from exc
        except ValueError as exc:
            # Fetch refused (not public HTTPS, redirect, too large) or not a usable still picture.
            logger.info("%s Picture %s not usable: %s", log_prefix, picture.embed_id[:8], exc)
            raise VideoInputUnavailable(f"The picture {picture.ref!r} could not be used: {exc}") from exc
        inputs.append(ComposedInput(
            name=f"input-{index}.{_extension(full.mime_type)}", content=full.content, mime_type=full.mime_type,
            width=full.width, height=full.height, title=title, kind=input_kind,
        ))
        kinds.append(kind)
        logger.info("%s [input:%s] %s picture %dx%d, %d bytes", log_prefix, picture.embed_id[:8], kind,
                    full.width, full.height, len(full.content))
    return inputs, kinds
