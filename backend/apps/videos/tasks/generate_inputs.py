"""The inputs of one videos.generate request, read server-side (assertion videos-generate.inputs).

Each reference is an exact embed id the skill resolved from the conversation. It
is one of:

- a search result (image, web, news or video search): readable only through
  its Vault-encrypted cache copy. Its title and bounded text (source, date,
  URL, description) always reach the author; its public picture address, when
  it has one, is fetched once in full size through the SSRF-safe public image
  reader (20 MB, longest side at most 2560 px). A result without a picture is
  a text-only source;
- a whole search (the skill-use parent of a search): it expands to its owned
  results in their order, at most ``MAX_REFERENCED_RESULTS`` results in total;
  their pictures fill what is left of the ``MAX_IMAGES`` picture budget, the
  rest are text-only sources;
- an owned picture (upload in its window, generated image, vector graphic,
  embroidery preview): read like images.modify reads its inputs.

A reference that cannot be read fails the request explicitly
(``VideoInputUnavailable``); there is no substitute picture. The picture of a
result named by its own ref that cannot be fetched fails the request too. Only
a result that came from expanding a whole search degrades to its text when its
picture cannot be fetched (logged), so one dead thumbnail does not fail a
recap of the whole search.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass, field, replace
from io import BytesIO
from typing import Any, Mapping, Optional, Sequence

import httpx

from backend.apps.videos.composed.models import MAX_SOURCES, ComposedInput, ComposedSource
from backend.apps.videos.generate_request import MAX_IMAGES
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
    is_search_result,
    owns,
    picture_url,
    read_result_reference,
    search_parent_children,
    vault_content_reader,
)

logger = logging.getLogger(__name__)

KIND_RESULT = "search_result"
KIND_RESULT_TEXT = "search_result_text"  # routing kind of a result used without a picture
KIND_IMAGE = "image"
KIND_VECTOR = "vector_graphic"
MAX_REFERENCED_RESULTS = MAX_SOURCES  # search results of one request after expanding whole searches
_SVG_MIN_SIDE = 1920


class VideoInputUnavailable(RuntimeError):
    """A reference of the request could not be read or used; nothing is made or charged."""


@dataclass(frozen=True)
class PictureRef:
    """One requested input: its embed id, its ref in the chat and what kind it is.

    ``use_picture`` is False for a search result that is used through its text
    only (it has no picture, or a whole search's picture budget is used up).
    ``explicit`` is False for a result that came from expanding a whole search.
    """

    embed_id: str
    ref: str
    kind: str  # search_result | image (an owned picture, kind known after loading)
    use_picture: bool = True
    explicit: bool = True

    @property
    def routing_kind(self) -> str:
        return KIND_RESULT_TEXT if self.kind == KIND_RESULT and not self.use_picture else self.kind


@dataclass(frozen=True)
class LoadedInputs:
    """Picture files for the sandbox (with the reference of each), and the text-only search results."""

    inputs: list[ComposedInput] = field(default_factory=list)
    pictures: list[PictureRef] = field(default_factory=list)  # aligned with ``inputs``
    sources: list[ComposedSource] = field(default_factory=list)
    source_titles: list[str] = field(default_factory=list)  # every search result title, in request order


def task_reader(task: Any, vault_key_id: str) -> ContentReader:
    return vault_content_reader(cache_service=task._cache_service, encryption_service=task._encryption_service,
                                user_vault_key_id=vault_key_id)


async def _expand_search(parent_id: str, ref: str, record: Mapping[str, Any], children: Sequence[str], *,
                         read_content: ContentReader, owner_hash: str) -> list[PictureRef]:
    if not owns(record, owner_hash):
        raise VideoInputUnavailable(f"The search {ref!r} is not available to this caller.")
    expanded: list[PictureRef] = []
    unreadable = 0
    for number, child_id in enumerate(children, start=1):
        loaded = await read_content(child_id)
        if loaded is None or not owns(loaded[0], owner_hash) or not is_search_result(loaded[1]):
            unreadable += 1
            continue
        child_ref = loaded[1].get("embed_ref")
        expanded.append(PictureRef(
            embed_id=child_id, ref=child_ref if isinstance(child_ref, str) and child_ref else f"{ref}#{number}",
            kind=KIND_RESULT, use_picture=picture_url(loaded[1]) is not None, explicit=False,
        ))
    if not expanded:
        raise VideoInputUnavailable(
            f"The results of the search {ref!r} are no longer readable by the server; search again to use them.")
    if unreadable:
        logger.info("[videos.generate] Search %s: %d of %d results not readable, used the rest", parent_id[:8],
                    unreadable, len(children))
    return expanded


def _apply_caps(pictures: list[PictureRef]) -> list[PictureRef]:
    """At most ``MAX_REFERENCED_RESULTS`` results; expanded results get pictures only while the budget lasts."""
    explicit_results = sum(1 for picture in pictures if picture.kind == KIND_RESULT and picture.explicit)
    result_room = max(0, MAX_REFERENCED_RESULTS - explicit_results)
    picture_room = MAX_IMAGES - sum(1 for picture in pictures if picture.explicit and picture.use_picture)
    capped: list[PictureRef] = []
    dropped = 0
    for picture in pictures:
        if not picture.explicit:
            if result_room <= 0:
                dropped += 1
                continue
            result_room -= 1
            if picture.use_picture:
                if picture_room > 0:
                    picture_room -= 1
                else:
                    picture = replace(picture, use_picture=False)
        capped.append(picture)
    if dropped:
        logger.info("[videos.generate] %d search results left out (at most %d results per video)", dropped,
                    MAX_REFERENCED_RESULTS)
    return capped


async def classify_pictures(embed_ids: Sequence[str], refs: Sequence[str], *, read_content: ContentReader,
                            owner_hash: str) -> list[PictureRef]:
    """Tell search results from owned pictures and expand whole searches into their results.

    A result is read from its server-readable cache copy; an unreadable id is
    left to the owned-picture reader, which fails it explicitly.
    """
    if len(embed_ids) != len(refs):
        raise ValueError("every picture needs its reference")
    pictures: list[PictureRef] = []
    for embed_id, ref in zip(embed_ids, refs):
        loaded = await read_content(embed_id)
        children = search_parent_children(loaded[1]) if loaded is not None else []
        if loaded is not None and children:
            pictures.extend(await _expand_search(embed_id, ref, loaded[0], children, read_content=read_content,
                                                 owner_hash=owner_hash))
        elif loaded is not None and is_search_result(loaded[1]):
            pictures.append(PictureRef(embed_id=embed_id, ref=ref, kind=KIND_RESULT,
                                       use_picture=picture_url(loaded[1]) is not None))
        else:
            pictures.append(PictureRef(embed_id=embed_id, ref=ref, kind=KIND_IMAGE))
    return _apply_caps(pictures)


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


async def _result_picture(picture: PictureRef, url: Optional[str], log_prefix: str) -> Optional[FullPublicImage]:
    """The full-size picture of a result; ``None`` when it is used through its text only."""
    if not picture.use_picture or url is None:
        return None
    try:
        return await download_public_image_full(url)
    except (httpx.HTTPError, OSError, TimeoutError, ValueError) as exc:
        # ValueError: fetch refused (not public HTTPS, redirect, too large) or not a usable still picture.
        if picture.explicit:
            message = (f"The picture of search result {picture.ref!r} could not be downloaded from its site."
                       if not isinstance(exc, ValueError) else f"The picture {picture.ref!r} could not be used: {exc}")
            raise VideoInputUnavailable(message) from exc
        logger.info("%s Result %s of a whole search: picture not usable (%s), its text is used", log_prefix,
                    picture.embed_id[:8], type(exc).__name__)
        return None


async def load_composed_inputs(
    task: Any, *, pictures: Sequence[PictureRef], user_id: str, vault_key_id: str, s3_service: Any, bucket: str,
    log_prefix: str, read_content: Optional[ContentReader] = None,
) -> LoadedInputs:
    """Every picture in request order at full size, named for the sandbox; text-only results as sources."""
    reader = read_content or task_reader(task, vault_key_id)
    owner_hash = hashlib.sha256(user_id.encode("utf-8")).hexdigest()
    loaded = LoadedInputs()
    for picture in pictures:
        title, text = "", ""
        try:
            if picture.kind == KIND_RESULT:
                result = await read_result_reference(picture.embed_id, read_content=reader, owner_hash=owner_hash)
                full = await _result_picture(picture, result.url, log_prefix)
                title, text, kind, input_kind = result.title, result.text, KIND_RESULT, "search_result"
                if title:
                    loaded.source_titles.append(title)
                if full is None:
                    if not (title or text):
                        raise VideoInputUnavailable(f"The search result {picture.ref!r} has no picture and no text.")
                    loaded.sources.append(ComposedSource(title=title, text=text))
                    logger.info("%s [input:%s] search result used as text (%d chars)", log_prefix,
                                picture.embed_id[:8], len(title) + len(text))
                    continue
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
            # Not a usable still picture (owned picture that cannot be decoded or prepared).
            logger.info("%s Picture %s not usable: %s", log_prefix, picture.embed_id[:8], exc)
            raise VideoInputUnavailable(f"The picture {picture.ref!r} could not be used: {exc}") from exc
        loaded.inputs.append(ComposedInput(
            name=f"input-{len(loaded.inputs) + 1}.{_extension(full.mime_type)}", content=full.content,
            mime_type=full.mime_type, width=full.width, height=full.height, title=title, kind=input_kind, text=text,
        ))
        loaded.pictures.append(picture)
        logger.info("%s [input:%s] %s picture %dx%d, %d bytes", log_prefix, picture.embed_id[:8], kind,
                    full.width, full.height, len(full.content))
    return loaded
