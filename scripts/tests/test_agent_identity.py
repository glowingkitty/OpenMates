"""Agent conversation identity resolution used by session and test tooling."""

from scripts.agent_identity import IDENTITY_ENV_VARS, agent_thread_id


def _clear(monkeypatch):
    for name in IDENTITY_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


# contract-test: tooling
def test_claude_session_id_is_preferred(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("CODEX_THREAD_ID", "legacy-thread")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "claude-conversation")
    assert agent_thread_id() == "claude-conversation"


# contract-test: tooling
def test_legacy_codex_identity_still_resolves(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("CODEX_SESSION_ID", "legacy-session")
    assert agent_thread_id() == "legacy-session"


# contract-test: tooling
def test_missing_or_blank_identity_returns_default(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "   ")
    assert agent_thread_id() == ""
    assert agent_thread_id("manual") == "manual"
