import json
from pathlib import Path
import urllib.parse

from scripts.opencode_permission_watcher import approve_pending_patterns


def test_approve_pending_patterns_remembers_valid_ids(monkeypatch, tmp_path: Path) -> None:
    requests = []

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def capture(request, timeout):
        requests.append((request, timeout))
        return Response()

    monkeypatch.setattr("urllib.request.urlopen", capture)
    approved = approve_pending_patterns(
        server_url="http://127.0.0.1:4096",
        project_root=tmp_path,
        session_id="ses_example",
        state={"pending_permission_ids": ["per_valid123", "invalid"]},
    )

    assert approved == ["per_valid123"]
    request, timeout = requests[0]
    assert request.method == "POST"
    assert json.loads(request.data) == {"response": "always"}
    assert urllib.parse.parse_qs(urllib.parse.urlparse(request.full_url).query) == {
        "directory": [str(tmp_path)],
    }
    assert timeout == 10
