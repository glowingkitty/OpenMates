# contract-test-file: infrastructure
"""Public docs API resolves the project docs/ tree (repo checkout and /app image)."""

from pathlib import Path

import pytest
from fastapi import HTTPException

from backend.core.api.app.routes import docs_routes

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_docs_root_is_project_docs_directory():
    assert docs_routes._DOCS_ROOT == REPO_ROOT / "docs"
    assert docs_routes._DOCS_ROOT.is_dir()


@pytest.mark.asyncio
async def test_docs_tree_lists_public_docs_and_honors_docsignore():
    tree = await docs_routes.list_docs.__wrapped__(None)
    folder_paths = {folder["path"] for folder in tree["folders"]}
    assert "user-guide" in folder_paths
    assert "contributing" not in folder_paths

    content = await docs_routes.get_doc.__wrapped__(None, "user-guide")
    assert content.body
    with pytest.raises(HTTPException) as exc:
        await docs_routes.get_doc.__wrapped__(None, "contributing/guides/testing")
    assert exc.value.status_code == 404
