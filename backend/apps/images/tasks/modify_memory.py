"""Keeps the editing program of an images.modify result for 24 hours (encrypted).

The chat stores the result client-encrypted only, so the program and the
references of the original inputs are kept server-readable for the processing
window: encrypted with the owner's Vault key in the cache, never shown as chat
content. When the result is passed to images.modify again within that time,
the author changes this program and it runs again on the original inputs, so
earlier steps are not applied twice and no quality is lost. After the window
the result is an ordinary input picture.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional, Sequence

PROGRAM_TTL_SECONDS = 86400
MAX_KEPT_PROGRAM_CHARS = 60_000


class KeptProgramError(RuntimeError):
    """A kept program exists but cannot be read back; the request fails instead of guessing."""


@dataclass(frozen=True)
class KeptProgram:
    """The program that produced a result and the original inputs it ran on, in order."""

    program: str
    input_embed_ids: tuple[str, ...]
    input_refs: tuple[str, ...]


def program_cache_key(embed_id: str) -> str:
    return f"images:modify_program:{embed_id}"


async def remember_program(
    task: Any, *, embed_id: str, program: str, input_embed_ids: Sequence[str], input_refs: Sequence[str],
    vault_key_id: str,
) -> None:
    """Encrypt the program and its input references with the owner's key and keep them 24 hours."""
    if len(program) > MAX_KEPT_PROGRAM_CHARS:
        raise KeptProgramError("The editing program is too large to keep")
    payload = json.dumps({"program": program, "input_embed_ids": list(input_embed_ids),
                          "input_refs": list(input_refs)})
    ciphertext, _ = await task._encryption_service.encrypt_with_user_key(payload, vault_key_id)
    if not ciphertext:
        raise KeptProgramError("The editing program could not be encrypted")
    client = await task._cache_service.client
    await client.set(program_cache_key(embed_id), ciphertext, ex=PROGRAM_TTL_SECONDS)


async def recall_program(task: Any, *, embed_id: str, vault_key_id: str) -> Optional[KeptProgram]:
    """Return the kept program of a result, or ``None`` when none is kept (any more)."""
    client = await task._cache_service.client
    ciphertext = await client.get(program_cache_key(embed_id))
    if not ciphertext:
        return None
    if isinstance(ciphertext, bytes):
        ciphertext = ciphertext.decode("utf-8")
    plaintext = await task._encryption_service.decrypt_with_user_key(ciphertext, vault_key_id)
    if not plaintext:
        raise KeptProgramError("The kept editing program could not be decrypted")
    try:
        data = json.loads(plaintext)
        program = data["program"]
        ids = tuple(str(value) for value in data["input_embed_ids"])
        refs = tuple(str(value) for value in data["input_refs"])
    except (ValueError, KeyError, TypeError) as exc:
        raise KeptProgramError("The kept editing program is unreadable") from exc
    if not isinstance(program, str) or not program or not ids or len(ids) != len(refs):
        raise KeptProgramError("The kept editing program is incomplete")
    return KeptProgram(program=program, input_embed_ids=ids, input_refs=refs)
