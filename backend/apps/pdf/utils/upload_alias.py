"""Resolve a plain PDF file name to the user's own upload, for pdf.search and pdf.read.

CLI uploads are referenced in the file index by a slug (a 40-character prefix of the file name
plus a 6-character digest), while the assistant usually passes the file name it sees in the
document block. A file name is therefore only accepted as an alias when exactly one candidate
slug in the caller's own index decrypts to a PDF whose metadata repeats that file name and slug.
Anything missing, unreadable, malformed or ambiguous is refused; an alias never selects another
PDF by guess and never reaches an upload outside the caller's index.

Spec: pdf-processing.surface.semantic-parity
"""

from __future__ import annotations

import logging
import re
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

CLI_PDF_REF = re.compile(r"^[a-z0-9-]{1,40}-[a-f0-9]{6}$")
ALIAS_ERROR = "PDF filename is missing or ambiguous; use its exact embed_ref."

EmbedLookup = Callable[[str, str], Awaitable[Dict[str, Any]]]


def candidate_pdf_upload_refs(file_path: str, file_path_index: Dict[str, str]) -> List[Tuple[str, str]]:
    """Narrow a file name to trusted CLI upload refs, never to storage IDs.

    The client embed ID inside the slug differs from the server upload ID, so the ref cannot be
    regenerated here. Decrypted PDF metadata is checked before any candidate is accepted.
    """
    if (
        not isinstance(file_path, str)
        or len(file_path) > 512
        or not file_path.lower().endswith(".pdf")
        or "/" in file_path
        or "\\" in file_path
        or any(ord(char) < 32 for char in file_path)
    ):
        return []
    filename_slug = re.sub(r"[^a-z0-9]+", "-", file_path.lower()).strip("-")
    if not filename_slug:
        return []
    prefix = filename_slug[:40]
    matches: List[Tuple[str, str]] = []
    for ref, embed_id in file_path_index.items():
        if not isinstance(ref, str) or not isinstance(embed_id, str) or not CLI_PDF_REF.fullmatch(ref):
            continue
        ref_prefix = ref.rsplit("-", 1)[0]
        same_filename_prefix = (
            ref_prefix == prefix
            if len(filename_slug) >= 40
            else ref_prefix.startswith(f"{prefix}-")
        )
        if same_filename_prefix:
            matches.append((ref, embed_id))
    return matches


async def resolve_pdf_alias(
    file_path: str,
    file_path_index: Dict[str, str],
    vault_key_id: str,
    lookup: EmbedLookup,
    log_prefix: str,
) -> Optional[Tuple[str, Dict[str, Any]]]:
    """Return (embed_id, decrypted embed content) for the one verified upload, else None.

    ``lookup(embed_id, vault_key_id)`` decrypts an embed; it raises RuntimeError or ValueError when
    the embed is unavailable or belongs to another owner.
    """
    verified: List[Tuple[str, Dict[str, Any]]] = []
    unverified_candidate = False
    for candidate_ref, candidate_id in candidate_pdf_upload_refs(file_path, file_path_index):
        try:
            content = await lookup(candidate_id, vault_key_id)
        except (RuntimeError, ValueError):
            # A competing entry that cannot be checked makes the alias ambiguous. It must not
            # silently select another PDF.
            unverified_candidate = True
            continue
        if not isinstance(content, dict) or any(
            not isinstance(content.get(field), str) or not content[field]
            for field in ("type", "filename", "embed_ref")
        ):
            unverified_candidate = True
            continue
        if (
            content.get("type") == "pdf"
            and content.get("filename") == file_path
            and content.get("embed_ref") == candidate_ref
        ):
            verified.append((candidate_id, content))
    if len(verified) != 1 or unverified_candidate:
        logger.warning("%s PDF filename alias has %d verified matches", log_prefix, len(verified))
        return None
    return verified[0]
