"""Loads the pictures of an images.modify request at full resolution.

The owner-bound loading (uploads, generated images, vector graphics and
embroidery results) is shared with videos.generate and lives in
``backend.shared.python_utils.owned_pictures``; this module keeps the names the
images.modify pipeline uses.
"""

from __future__ import annotations

from backend.shared.python_utils.owned_pictures import (
    EDITABLE_PIXEL_FORMATS,
    EMBROIDERY_PREVIEW_VARIANT,
    FRESH_UPLOAD_WINDOW_SECONDS,
    KIND_EMBROIDERY,
    KIND_PIXEL,
    KIND_SVG,
    LoadedPicture as LoadedInput,
    load_embroidery_index_record,
    load_owned_pictures as load_modify_inputs,
    request_internal,
    select_source,
)

__all__ = [
    "EDITABLE_PIXEL_FORMATS", "EMBROIDERY_PREVIEW_VARIANT", "FRESH_UPLOAD_WINDOW_SECONDS", "KIND_EMBROIDERY",
    "KIND_PIXEL", "KIND_SVG", "LoadedInput", "load_embroidery_index_record", "load_modify_inputs",
    "request_internal", "select_source",
]
