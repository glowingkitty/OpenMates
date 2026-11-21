"""Screenshots/videos on ✅/❓ pushes and the proof check (scripts/push_proof.py, agent_question.py)."""
# contract-test-file: tooling

import argparse
import io
import json
import os
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import agent_question as aq  # noqa: E402
import discord_webhook  # noqa: E402
import push_proof  # noqa: E402

OWN_LINK = "https://nbg1.your-objectstorage.com/openmates-ai-test-user-videos/agent-pushes/x.webm?X-Amz-Signature=abc"


def no_model(*_):
    raise aq.discord_summary.ShortenFailed("test: no model")


@pytest.fixture
def root(tmp_path, monkeypatch):
    for key in aq.WEBHOOK_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("DISCORD_WEBHOOK_AGENT_QUESTIONS", "https://discord.example.org/api/webhooks/1/x")
    monkeypatch.delenv("CLAUDE_CHAT_TITLE", raising=False)
    monkeypatch.setattr(aq, "shorten_with_model", no_model)
    (tmp_path / ".claude").mkdir()
    return tmp_path


def sessions(root: Path, **by_key: tuple[str, list[str]]) -> None:
    (root / ".claude/sessions.json").write_text(json.dumps({"sessions": {
        key: {"agent_task_id": chat, "task": "Some work", "last_active": "2026", "modified_files": files}
        for key, (chat, files) in by_key.items()}}))


def ci_jobs(root: Path, *jobs: tuple[str, str, str]) -> None:
    path = root / push_proof.CI_QUEUE
    path.parent.mkdir(parents=True)
    with sqlite3.connect(path) as db:
        db.execute("create table jobs (id text, owner text, mode text, state text, specs text)")
        db.executemany("insert into jobs values (?, ?, ?, ?, '[]')",
                       [(str(i), owner, mode, state) for i, (owner, mode, state) in enumerate(jobs)])


def done(**overrides) -> argparse.Namespace:
    values = dict(command="done", summary="The settings panel slides in smoothly on dev.", paused_until=None,
                  task="", dry_run=False, force=True, attach=None, link=None, no_proof=None)
    values.update(overrides)
    return argparse.Namespace(**values)


def png(path: Path, size=(64, 48)) -> Path:
    from PIL import Image
    Image.new("RGB", size, (30, 120, 200)).save(path)
    return path


@pytest.mark.parametrize("path, visual", [
    ("frontend/packages/ui/src/components/Settings.svelte", True),
    ("frontend/packages/ui/src/styles/theme.css", True),
    ("apple/OpenMates/Sources/Features/Chat/Views/ChatView.swift", True),
    ("apple/OpenMates/Sources/Features/Chat/StartScreen.swift", True),
    ("apple/OpenMates/Assets.xcassets/AppIcon.appiconset/Contents.json", True),
    ("backend/core/api/templates/email/action-verification.mjml", True),
    ("backend/core/api/app/routes/settings.py", False),
    ("backend/core/api/Dockerfile.celery", False),
    ("apple/OpenMates/Sources/Core/SyncService.swift", False),
    ("apple/OpenMatesTests/ChatViewTests.swift", False),
    ("frontend/apps/web_app/tests/settings-overlay-motion.spec.ts", False),
    ("frontend/packages/ui/src/services/chatSyncService.ts", False),
    ("scripts/agent_question.py", False),
    ("docs/architecture/overview.md", False),
])
def test_ui_files_are_told_apart_from_backend_tooling_and_tests(path, visual):
    assert push_proof.is_ui_file(path) is visual


def test_research_backend_and_security_chats_need_no_proof(root):
    sessions(root, aa11=("chat-1", ["backend/core/api/Dockerfile.celery", "backend/core/docker-compose.yml"]))
    ci_jobs(root, ("aa11", "pytest", "success"), ("aa11", "rust-check", "failure"))
    assert push_proof.proof_reasons(root, "chat-1") == []
    assert push_proof.proof_reasons(root, "chat-without-session") == []
    assert push_proof.proof_reasons(root, "") == []


def test_ui_changes_and_finished_e2e_runs_need_proof(root):
    sessions(root, aa11=("chat-1", ["frontend/packages/ui/src/components/Settings.svelte"]),
             bb22=("chat-2", ["backend/x.py"]), cc33=("chat-3", []))
    ci_jobs(root, ("bb22", "e2e", "success"), ("cc33", "e2e", "running"), ("cc33", "component", "cancelled"))
    assert push_proof.proof_reasons(root, "chat-1") == ["changed UI files (Settings.svelte)"]
    assert push_proof.proof_reasons(root, "chat-2") == ["ran 1 end-to-end or visual CI job(s) (e2e)"]
    assert push_proof.proof_reasons(root, "chat-3") == []  # unfinished or cancelled runs have nothing yet


def test_push_wording_plays_no_part(root):
    sessions(root, aa11=("chat-1", ["backend/core/api/app/routes/settings.py"]))
    text = aq.send(done(summary="Security check of the UI login screen: not affected.", dry_run=True),
                   root, "chat-1", 1.0, post=lambda **_: pytest.fail("posted"))
    assert "No screenshot" not in text


@pytest.mark.parametrize("command", ["done", "ask"])
def test_visual_push_without_proof_is_refused_even_as_dry_run(root, command):
    sessions(root, aa11=("chat-1", ["frontend/packages/ui/src/components/Settings.svelte"]))
    extra = {"question": "Keep the darker backdrop?", "recommendation": "yes", "option": []} if command == "ask" else {}
    for dry in (True, False):
        with pytest.raises(aq.QuestionError, match="needs a screenshot or video.*--attach"):
            aq.send(done(command=command, dry_run=dry, **extra), root, "chat-1", 1.0,
                    post=lambda **_: pytest.fail("posted"), post_files=lambda **_: pytest.fail("posted"))


def test_no_proof_reason_is_sent_loudly(root):
    sessions(root, aa11=("chat-1", ["frontend/packages/ui/src/components/Settings.svelte"]))
    sent = []
    message = aq.send(done(no_proof="only a CSS comment changed"), root, "chat-1", 1.0,
                      post=lambda **kw: sent.append(kw) or {"message_id": "1"})
    assert message.splitlines()[1] == "⚠️ No screenshot or video: only a CSS comment changed"
    entry = json.loads((root / aq.PUSH_LOG).read_text().splitlines()[-1])
    assert entry["proof"] == {"no_proof": "only a CSS comment changed"}


def test_screenshot_and_video_go_out_as_discord_files_on_top_of_the_short_text(root, tmp_path):
    sessions(root, aa11=("chat-1", ["frontend/packages/ui/src/components/Settings.svelte"]))
    shot = png(tmp_path / "settings.png")
    video = tmp_path / "flow.webm"
    video.write_bytes(b"\x1aE\xdf\xa3" + b"0" * 2000)
    sent = []
    message = aq.send(done(attach=[str(shot), str(video)]), root, "chat-1", 1.0,
                      post=lambda **_: pytest.fail("text-only post"),
                      post_files=lambda **kw: sent.append(kw) or {"message_id": "1", "attachment_ids": ["a", "b"]})
    assert [name for name, _ in sent[0]["files"]] == ["settings.png", "flow.webm"]
    assert sent[0]["files"][0][1] == shot.read_bytes()
    assert sent[0]["payload"]["content"] == message and message.count("\n") == 0
    entry = json.loads((root / aq.PUSH_LOG).read_text().splitlines()[-1])
    assert entry["proof"] == {"files": ["settings.png", "flow.webm"], "links": []}


def test_large_screenshot_is_compressed_below_the_limit(tmp_path):
    from PIL import Image
    noisy = tmp_path / "big.png"
    Image.frombytes("RGB", (1800, 1400), os.urandom(1800 * 1400 * 3)).save(noisy)
    assert noisy.stat().st_size > push_proof.IMAGE_MAX_BYTES
    prepared = push_proof.prepare([str(noisy)], [], "chat-1", tmp_path, own_link=aq.own_storage_link,
                                  uploader=lambda *_: pytest.fail("uploaded"))
    (name, content), = prepared.files
    assert name == "big.jpg" and len(content) <= push_proof.IMAGE_MAX_BYTES
    assert Image.open(io.BytesIO(content)).format == "JPEG"


def test_video_over_the_limit_is_reencoded_or_linked_from_private_storage(root, tmp_path, monkeypatch):
    monkeypatch.setattr(push_proof, "MESSAGE_BYTES", 1000)
    video = tmp_path / "long.webm"
    video.write_bytes(b"0" * 5000)
    small = push_proof.prepare([str(video)], [], "chat-1", tmp_path, own_link=aq.own_storage_link,
                               uploader=lambda *_: pytest.fail("uploaded"),
                               video_compressor=lambda *_: b"1" * 900)
    assert small.files == [("long.mp4", b"1" * 900)] and not small.links
    uploads = []
    linked = push_proof.prepare([str(video)], [], "chat-1", tmp_path, own_link=aq.own_storage_link,
                                uploader=lambda path, chat: uploads.append((path, chat)) or OWN_LINK,
                                video_compressor=lambda *_: None)
    assert uploads == [(video, "chat-1")] and not linked.files
    assert linked.link_lines() == [f"long.webm: <{OWN_LINK}>"]


def test_link_lines_are_not_counted_against_the_text_limit(root, tmp_path, monkeypatch):
    monkeypatch.setattr(push_proof, "MESSAGE_BYTES", 10)
    sessions(root, aa11=("chat-1", ["frontend/packages/ui/src/components/Settings.svelte"]))
    video = tmp_path / "long.webm"
    video.write_bytes(b"0" * 500)
    monkeypatch.setattr(push_proof, "compress_video", lambda *_: None)
    sent = []
    message = aq.send(done(attach=[str(video)], link=[OWN_LINK]), root, "chat-1", 1.0,
                      post=lambda **kw: sent.append(kw) or {"message_id": "1"}, uploader=lambda *_: OWN_LINK)
    first, *links = message.splitlines()
    assert len(first) <= 140 and links == [f"Proof: <{OWN_LINK}>", f"long.webm: <{OWN_LINK}>"]


@pytest.mark.parametrize("name, error", [
    (".auth/state.png", "private paths"), (".env.local.png", "private paths"),
    ("ci-private/a.png", "private paths"), ("notes.txt", "only screenshots"), ("missing.png", "no such file"),
])
def test_private_missing_or_unsupported_attachments_are_refused(tmp_path, name, error):
    path = tmp_path / name
    if name != "missing.png":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")
    with pytest.raises(push_proof.ProofError, match=error):
        push_proof.check_path(str(path))


def test_only_links_to_our_private_storage_are_accepted(tmp_path):
    with pytest.raises(push_proof.ProofError, match="private proof storage"):
        push_proof.prepare([], ["https://example.org/video.mp4"], "chat-1", tmp_path, own_link=aq.own_storage_link)
    assert push_proof.prepare([], [OWN_LINK], "chat-1", tmp_path, own_link=aq.own_storage_link).links


class FakeResponse:
    def __init__(self, body: dict):
        self.body = json.dumps(body).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return self.body


def test_post_files_sends_one_multipart_message_and_confirms_every_attachment():
    seen = []

    def opener(request, timeout):
        seen.append(request)
        return FakeResponse({"id": "9", "attachments": [{"id": "1"}, {"id": "2"}]})

    result = discord_webhook.post_files(webhook_url="https://discord.example.org/api/webhooks/1/x",
                                        payload={"content": "hi"}, files=[("a.png", b"A"), ("b.webm", b"B")],
                                        opener=opener)
    assert result == {"message_id": "9", "attachment_ids": ["1", "2"]}
    body = seen[0].data
    assert b'name="files[0]"; filename="a.png"' in body and b'name="files[1]"; filename="b.webm"' in body
    assert seen[0].full_url.endswith("?wait=true")
    missing = discord_webhook.post_files(
        webhook_url="https://discord.example.org/api/webhooks/1/x", payload={"content": "hi"},
        files=[("a.png", b"A"), ("b.webm", b"B")],
        opener=lambda *_a, **_k: FakeResponse({"id": "9", "attachments": [{"id": "1"}]}))
    assert missing is None
