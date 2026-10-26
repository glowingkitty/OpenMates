"""Browse accepts assistant dispatch context without weakening its public contract."""

import pytest
from pydantic import ValidationError

from backend.apps.ai.processing.skill_executor import get_skill_timeout


# contract-test: supporting surface=cli assertions=web-browse.dispatch-and-routing
@pytest.mark.parametrize("timeout_seconds", [10, 180, 600])
# contract-test: supporting surface=cli assertions=web-browse.dispatch-and-routing
def test_browse_timeout_accepts_real_assistant_dispatch_context(timeout_seconds):
    arguments = {
        "task": "Read the public example page",
        "start_url": "https://example.com/",
        "timeout_seconds": timeout_seconds,
        "_same_turn_batch_id": "batch",
        "_placeholder_embed_ids": ["embed"],
        "_user_vault_key_id": "private-vault-reference",
        "_file_path_index": {},
    }
    assert get_skill_timeout("web", "browse", arguments) == timeout_seconds + 120


# contract-test: supporting surface=cli assertions=web-browse.dispatch-and-routing
def test_browse_timeout_keeps_public_validation():
    for invalid in ({"timeout_seconds": 601}, {"arbitrary_browser_code": "forbidden"}):
        with pytest.raises(ValidationError):
            get_skill_timeout("web", "browse", {"task": "Read example", **invalid})
