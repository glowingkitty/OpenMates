"""Account Import V1 OpenMates archive parser contract tests.

Synthetic Export V1 archives verify the importer only restores chats plus
referenced embeds/uploads and rejects incompatible archive layouts before scan.
"""

from __future__ import annotations

import zipfile
from io import BytesIO

import pytest
import yaml

from backend.core.api.app.services.account_import_service import ImportParseError, parse_openmates_export_bytes


def _openmates_zip(*, manifest_version: str = "1", include_unsupported_domains: bool = True) -> bytes:
    manifest = {
        "format": "openmates-account-export",
        "version": manifest_version,
        "domains": {
            "chats": {"count": 1},
            "embeds": {"count": 1},
            "referenced_uploads": {"count": 1},
        },
    }
    if include_unsupported_domains:
        manifest["domains"].update({"projects": {"count": 1}, "tasks": {"count": 1}, "memories": {"count": 1}})
    chat = {
        "id": "openmates-chat-1",
        "title": "Synthetic exported chat",
        "created_at": "2026-07-17T11:00:00Z",
        "updated_at": "2026-07-17T11:10:00Z",
        "messages": [
            {
                "id": "openmates-message-1",
                "role": "user",
                "content": "Synthetic OpenMates export message.",
                "created_at": "2026-07-17T11:00:00Z",
                "embed_refs": ["embed-1"],
            }
        ],
        "embed_refs": ["embed-1"],
        "upload_refs": ["upload-1"],
    }
    embed = {"id": "embed-1", "type": "code", "content": {"language": "text"}, "referenced_upload_ids": ["upload-1"]}
    upload = {"id": "upload-1", "file_name": "synthetic.txt", "mime_type": "text/plain", "bytes": 42, "path": "uploads/upload-1.txt"}
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("README.md", "Synthetic OpenMates Export V1 fixture")
        archive.writestr("manifest.yml", yaml.safe_dump(manifest))
        archive.writestr("export-report.yml", yaml.safe_dump({"status": "complete"}))
        archive.writestr("chats/openmates-chat-1.yml", yaml.safe_dump(chat))
        archive.writestr("chats/openmates-chat-1.md", "# Synthetic exported chat\n")
        archive.writestr("embeds/embed-1.yml", yaml.safe_dump(embed))
        archive.writestr("uploads/upload-1.yml", yaml.safe_dump(upload))
        archive.writestr("projects/project-1.yml", yaml.safe_dump({"id": "project-1"}))
    return buffer.getvalue()


def test_openmates_export_v1_parses_chats_embeds_and_referenced_uploads_only() -> None:
    result = parse_openmates_export_bytes(_openmates_zip(), source_name="openmates-export.zip")

    assert result["source"] == "openmates"
    assert result["skipped_domains"] == ["memories", "projects", "tasks"]
    assert len(result["chats"]) == 1
    chat = result["chats"][0]
    assert chat["provider"] == "openmates"
    assert chat["source_chat_id"] == "openmates-chat-1"
    assert chat["messages"][0]["role"] == "user"
    assert chat["embeds"][0]["source_embed_id"] == "embed-1"
    assert chat["uploads"][0]["source_upload_id"] == "upload-1"


def test_openmates_export_incompatible_version_fails_before_scan_or_billing() -> None:
    with pytest.raises(ImportParseError, match="OpenMates Export V1"):
        parse_openmates_export_bytes(_openmates_zip(manifest_version="2"), source_name="future-export.zip")


def test_openmates_export_requires_manifest_and_chat_yaml() -> None:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("README.md", "missing manifest")

    with pytest.raises(ImportParseError, match="manifest.yml"):
        parse_openmates_export_bytes(buffer.getvalue(), source_name="missing-manifest.zip")
