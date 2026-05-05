"""
Embed Diff Service — applies unified diffs to embed content, manages version history.

Handles:
- Parsing unified diff format from LLM output
- 3-tier patch application (exact → fuzzy → visual fallback)
- Version tracking in embed_diffs collection
- Snapshot storage for v1 (original) and latest in encrypted_content

Architecture: docs/architecture/messaging/embed-diff-editing.md
"""

import hashlib
import logging
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ─── Data classes ────────────────────────────────────────────────────

@dataclass
class DiffHunk:
    """A single @@ hunk from a unified diff."""
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: List[str]  # Each line prefixed with ' ', '+', or '-'


@dataclass
class ParsedDiff:
    """A parsed unified diff targeting a specific embed."""
    embed_ref: str
    hunks: List[DiffHunk]
    raw_diff: str


@dataclass
class PatchResult:
    """Result of attempting to apply a patch."""
    success: bool
    new_content: Optional[str]  # The patched content (None if failed)
    tier: int  # 1=exact, 2=fuzzy, 3=fallback (visual only)
    error: Optional[str]  # Error message if failed


# ─── Diff Parsing ────────────────────────────────────────────────────

HUNK_HEADER_PATTERN = re.compile(
    r'^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@'
)


def parse_unified_diff(diff_text: str, embed_ref: str) -> ParsedDiff:
    """
    Parse a unified diff string into structured hunks.

    Args:
        diff_text: The raw diff content (lines starting with ' ', '+', '-', '@@')
        embed_ref: The embed reference this diff targets

    Returns:
        ParsedDiff with parsed hunks
    """
    hunks: List[DiffHunk] = []
    current_hunk: Optional[DiffHunk] = None
    lines = diff_text.split('\n')

    for line in lines:
        header_match = HUNK_HEADER_PATTERN.match(line)
        if header_match:
            if current_hunk is not None:
                hunks.append(current_hunk)
            current_hunk = DiffHunk(
                old_start=int(header_match.group(1)),
                old_count=int(header_match.group(2) or '1'),
                new_start=int(header_match.group(3)),
                new_count=int(header_match.group(4) or '1'),
                lines=[]
            )
        elif current_hunk is not None:
            # Only include actual diff lines (context, add, remove)
            if line.startswith((' ', '+', '-')):
                current_hunk.lines.append(line)
            elif line == '':
                # Empty line in diff = context line with space prefix stripped
                current_hunk.lines.append(' ')
            # Skip lines that don't match diff format (e.g., "\ No newline at end of file")

    if current_hunk is not None:
        hunks.append(current_hunk)

    return ParsedDiff(embed_ref=embed_ref, hunks=hunks, raw_diff=diff_text)


# ─── Patch Application ───────────────────────────────────────────────

def apply_patch_exact(content: str, diff: ParsedDiff) -> PatchResult:
    """
    Tier 1: Apply patch with exact context line matching.
    All context and removal lines must match the original content exactly.
    """
    content_lines = content.split('\n')
    # Work through hunks in reverse order so line numbers stay valid
    sorted_hunks = sorted(diff.hunks, key=lambda h: h.old_start, reverse=True)

    for hunk in sorted_hunks:
        # Convert to 0-indexed
        start_idx = hunk.old_start - 1

        # Extract expected old lines from hunk
        old_lines = []
        new_lines = []
        for line in hunk.lines:
            if line.startswith(' '):
                old_lines.append(line[1:])
                new_lines.append(line[1:])
            elif line.startswith('-'):
                old_lines.append(line[1:])
            elif line.startswith('+'):
                new_lines.append(line[1:])

        # Verify context matches exactly
        end_idx = start_idx + len(old_lines)
        if end_idx > len(content_lines):
            return PatchResult(
                success=False, new_content=None, tier=1,
                error=f"Hunk @@ -{hunk.old_start},{hunk.old_count} extends past end of file "
                      f"(file has {len(content_lines)} lines, hunk needs up to line {end_idx})"
            )

        actual_old = content_lines[start_idx:end_idx]
        if actual_old != old_lines:
            # Find first mismatch for error reporting
            for i, (actual, expected) in enumerate(zip(actual_old, old_lines)):
                if actual != expected:
                    return PatchResult(
                        success=False, new_content=None, tier=1,
                        error=f"Context mismatch at line {start_idx + i + 1}: "
                              f"expected {expected!r}, got {actual!r}"
                    )
            return PatchResult(
                success=False, new_content=None, tier=1,
                error=f"Line count mismatch: expected {len(old_lines)} lines, "
                      f"got {len(actual_old)} lines at position {start_idx + 1}"
            )

        # Apply the replacement
        content_lines[start_idx:end_idx] = new_lines

    return PatchResult(
        success=True,
        new_content='\n'.join(content_lines),
        tier=1,
        error=None
    )


def apply_patch_fuzzy(content: str, diff: ParsedDiff, max_offset: int = 3) -> PatchResult:
    """
    Tier 2: Apply patch with fuzzy context matching.
    Allows context lines to be offset by up to max_offset lines from expected position.
    """
    content_lines = content.split('\n')
    sorted_hunks = sorted(diff.hunks, key=lambda h: h.old_start, reverse=True)

    for hunk in sorted_hunks:
        start_idx = hunk.old_start - 1

        old_lines = []
        new_lines = []
        for line in hunk.lines:
            if line.startswith(' '):
                old_lines.append(line[1:])
                new_lines.append(line[1:])
            elif line.startswith('-'):
                old_lines.append(line[1:])
            elif line.startswith('+'):
                new_lines.append(line[1:])

        # Try exact position first, then search ±max_offset
        found_at = None
        for offset in range(0, max_offset + 1):
            for direction in ([0] if offset == 0 else [offset, -offset]):
                try_idx = start_idx + direction
                if try_idx < 0 or try_idx + len(old_lines) > len(content_lines):
                    continue
                if content_lines[try_idx:try_idx + len(old_lines)] == old_lines:
                    found_at = try_idx
                    break
            if found_at is not None:
                break

        if found_at is None:
            return PatchResult(
                success=False, new_content=None, tier=2,
                error=f"Fuzzy match failed for hunk @@ -{hunk.old_start},{hunk.old_count}: "
                      f"could not find matching context within ±{max_offset} lines"
            )

        # Apply the replacement at found position
        content_lines[found_at:found_at + len(old_lines)] = new_lines

    return PatchResult(
        success=True,
        new_content='\n'.join(content_lines),
        tier=2,
        error=None
    )


def apply_patch(content: str, diff: ParsedDiff) -> PatchResult:
    """
    Apply a parsed diff to content using 3-tier fallback strategy.

    Returns PatchResult with:
    - tier=1/2 + success=True: patch applied, new_content has result
    - tier=3 + success=False: patch failed, raw_diff should be shown as visual card
    """
    if not diff.hunks:
        return PatchResult(
            success=False, new_content=None, tier=3,
            error="No hunks found in diff"
        )

    # Tier 1: Exact match
    result = apply_patch_exact(content, diff)
    if result.success:
        logger.debug(f"Patch applied successfully (tier 1, exact) for {diff.embed_ref}")
        return result

    tier1_error = result.error
    logger.debug(f"Tier 1 (exact) failed for {diff.embed_ref}: {tier1_error}. Trying fuzzy...")

    # Tier 2: Fuzzy match (±3 lines)
    result = apply_patch_fuzzy(content, diff, max_offset=3)
    if result.success:
        logger.info(f"Patch applied successfully (tier 2, fuzzy) for {diff.embed_ref}")
        return result

    tier2_error = result.error
    logger.warning(
        f"Patch application failed for {diff.embed_ref}. "
        f"Tier 1: {tier1_error}. Tier 2: {tier2_error}. "
        f"Falling back to visual diff card (tier 3)."
    )

    # Tier 3: Visual fallback — return failure so caller renders diff as card
    return PatchResult(
        success=False, new_content=None, tier=3,
        error=f"Exact: {tier1_error}. Fuzzy: {tier2_error}"
    )


# ─── Diff Detection in Stream ────────────────────────────────────────

DIFF_FENCE_PATTERN = re.compile(r'^```diff:(.+)$')


def is_diff_fence_open(line: str) -> Optional[str]:
    """
    Check if a line opens a diff fence. Returns embed_ref if yes, None otherwise.

    Example: ```diff:process_data.py-k8D → returns "process_data.py-k8D"
    """
    match = DIFF_FENCE_PATTERN.match(line.strip())
    return match.group(1) if match else None


# ─── Version Management ──────────────────────────────────────────────

class EmbedDiffService:
    """
    Manages embed version history — stores snapshots and diffs,
    reconstructs historical versions on demand.
    """

    def __init__(self, cache_service, directus_service, encryption_service):
        self.cache_service = cache_service
        self.directus_service = directus_service
        self.encryption_service = encryption_service

    async def store_initial_snapshot(
        self,
        embed_id: str,
        content: str,
        user_vault_key_id: str,
        hashed_user_id: str,
        log_prefix: str = ""
    ) -> bool:
        """
        Store the original content as v1 snapshot in embed_diffs.
        Called the first time a diff is applied to an embed.

        Returns True if stored successfully.
        """
        try:
            encrypted_snapshot, _ = await self.encryption_service.encrypt_with_user_key(
                content, user_vault_key_id
            )

            await self.directus_service.create_item("embed_diffs", {
                "embed_id": embed_id,
                "version_number": 1,
                "encrypted_snapshot": encrypted_snapshot,
                "encrypted_patch": None,
                "hashed_user_id": hashed_user_id,
                "created_at": int(time.time())
            })

            logger.info(f"{log_prefix} Stored v1 snapshot for embed {embed_id} ({len(content)} chars)")
            return True

        except Exception as e:
            logger.error(f"{log_prefix} Failed to store v1 snapshot for embed {embed_id}: {e}")
            return False

    async def store_diff_version(
        self,
        embed_id: str,
        version_number: int,
        patch_text: str,
        user_vault_key_id: str,
        hashed_user_id: str,
        log_prefix: str = ""
    ) -> bool:
        """
        Store a diff as a new version in embed_diffs.
        Called after successfully applying a patch.
        """
        try:
            encrypted_patch, _ = await self.encryption_service.encrypt_with_user_key(
                patch_text, user_vault_key_id
            )

            await self.directus_service.create_item("embed_diffs", {
                "embed_id": embed_id,
                "version_number": version_number,
                "encrypted_snapshot": None,
                "encrypted_patch": encrypted_patch,
                "hashed_user_id": hashed_user_id,
                "created_at": int(time.time())
            })

            logger.info(
                f"{log_prefix} Stored diff v{version_number} for embed {embed_id} "
                f"({len(patch_text)} chars)"
            )
            return True

        except Exception as e:
            logger.error(
                f"{log_prefix} Failed to store diff v{version_number} for embed {embed_id}: {e}"
            )
            return False

    async def get_version_history(
        self,
        embed_id: str,
        hashed_user_id: str,
        user_vault_key_id: str,
        log_prefix: str = ""
    ) -> List[Dict[str, Any]]:
        """
        Fetch all versions for an embed (for timeline display).
        Returns list of {version_number, created_at, has_snapshot, patch_preview}.
        Does NOT decrypt full content — just metadata for timeline rendering.
        """
        try:
            items = await self.directus_service.read_items(
                "embed_diffs",
                params={
                    "filter": {
                        "embed_id": {"_eq": embed_id},
                        "hashed_user_id": {"_eq": hashed_user_id},
                    },
                    "sort": ["version_number"],
                    "fields": ["version_number", "created_at", "encrypted_snapshot", "encrypted_patch"],
                }
            )

            versions = []
            for item in (items or []):
                versions.append({
                    "version_number": item["version_number"],
                    "created_at": item["created_at"],
                    "has_snapshot": item.get("encrypted_snapshot") is not None,
                    "has_patch": item.get("encrypted_patch") is not None,
                })

            return versions

        except Exception as e:
            logger.error(f"{log_prefix} Failed to fetch version history for embed {embed_id}: {e}")
            return []

    async def reconstruct_version(
        self,
        embed_id: str,
        target_version: int,
        hashed_user_id: str,
        user_vault_key_id: str,
        log_prefix: str = ""
    ) -> Optional[str]:
        """
        Reconstruct content at a specific version by applying patches forward from v1.

        Returns the content string at the target version, or None on failure.
        """
        try:
            items = await self.directus_service.read_items(
                "embed_diffs",
                params={
                    "filter": {
                        "embed_id": {"_eq": embed_id},
                        "hashed_user_id": {"_eq": hashed_user_id},
                        "version_number": {"_lte": target_version},
                    },
                    "sort": ["version_number"],
                    "fields": ["version_number", "encrypted_snapshot", "encrypted_patch"],
                }
            )

            if not items:
                logger.warning(f"{log_prefix} No versions found for embed {embed_id}")
                return None

            # First item should be v1 with snapshot
            v1_item = items[0]
            if not v1_item.get("encrypted_snapshot"):
                logger.error(f"{log_prefix} v1 snapshot missing for embed {embed_id}")
                return None

            # Decrypt v1 snapshot
            content = await self.encryption_service.decrypt_with_user_key(
                v1_item["encrypted_snapshot"], user_vault_key_id
            )

            # Apply patches forward
            for item in items[1:]:
                if not item.get("encrypted_patch"):
                    continue
                patch_text = await self.encryption_service.decrypt_with_user_key(
                    item["encrypted_patch"], user_vault_key_id
                )
                parsed = parse_unified_diff(patch_text, embed_id)
                result = apply_patch(content, parsed)
                if result.success:
                    content = result.new_content
                else:
                    logger.warning(
                        f"{log_prefix} Failed to apply patch v{item['version_number']} "
                        f"for embed {embed_id}: {result.error}. Stopping at v{item['version_number'] - 1}."
                    )
                    break

            return content

        except Exception as e:
            logger.error(f"{log_prefix} Failed to reconstruct v{target_version} for embed {embed_id}: {e}")
            return None
