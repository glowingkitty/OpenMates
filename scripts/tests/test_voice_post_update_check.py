# contract-test-file: tooling
"""Light tests for scripts/voice_post_update_check.py (no browser, no network)."""
from __future__ import annotations

import json
import sys
import wave
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import voice_post_update_check as check  # noqa: E402
import ai_test_users_accounts as accounts  # noqa: E402
import post_update_test_account as account  # noqa: E402


def leg_dir(tmp_path: Path, receipt: dict | None, video: bool = True) -> Path:
    if receipt is not None:
        (tmp_path / "receipt.json").write_text(json.dumps(receipt))
    if video:
        (tmp_path / "results").mkdir()
        (tmp_path / "results" / "video-with-audio.webm").write_bytes(b"x")
    return tmp_path


def loud(_video):
    return -20.0


def test_capital_question_uses_a_local_microphone_fixture(tmp_path, monkeypatch):
    import voice_call_web_real_test as voice

    def reject_provider(*_args):
        pytest.fail("the recurring voice check must use its recorded microphone question")

    monkeypatch.setattr(voice, "speak", reject_provider)
    assert voice.generate_speech(tmp_path, "capital")["capital"] > 1
    with wave.open(str(tmp_path / "capital.wav"), "rb") as audio:
        assert (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) == (1, 2, 16000)
        assert audio.getnframes() > 90 * audio.getframerate()
        assert any(audio.readframes(5 * audio.getframerate()))


def test_passes_with_reply_and_audible_video(tmp_path):
    out = leg_dir(tmp_path, {"status": "passed", "played_audio": ["1 clip"]})
    assert check.evaluate_leg(out, loud)["status"] == "passed"


@pytest.mark.parametrize("receipt,video,loudness,fragment", [
    (None, True, loud, "no receipt"),
    ({"status": "failed", "error_code": "boom"}, True, loud, "boom"),
    ({"status": "passed", "played_audio": []}, True, loud, "no spoken reply"),
    ({"status": "passed", "played_audio": ["a"]}, False, loud, "no with-audio video"),
    ({"status": "passed", "played_audio": ["a"]}, True, lambda v: -80.0, "silent"),
])
def test_failures(tmp_path, receipt, video, loudness, fragment):
    result = check.evaluate_leg(leg_dir(tmp_path, receipt, video), loudness)
    assert result["status"] == "failed" and fragment in result["error"]


def test_guest_receipt_with_speech_status(tmp_path):
    out = leg_dir(tmp_path, {"status": "passed", "speech_status": 200})
    assert check.evaluate_leg(out, loud)["status"] == "passed"


def fake_summary(passed: bool) -> dict:
    status = "passed" if passed else "failed"
    return {"passed": passed, "legs": {"guest": {"status": status, "video": None, "error": None}}}


def test_push_only_on_failure(tmp_path):
    pushed = []
    for status in ("passed", "failed"):
        check.run_check("dev", "https://x", "abc", tmp_path / status, ["guest"],
                        leg_runner=lambda *a, s=status: {"status": s, "video": None, "error": "no reply"},
                        pusher=lambda t, s: pushed.append(s))
    assert len(pushed) == 1 and pushed[0]["passed"] is False
    assert json.loads((tmp_path / "passed" / "summary.json").read_text())["passed"] is True


def test_no_push_flag(tmp_path):
    pushed = []
    check.run_check("dev", "https://x", "abc", tmp_path, ["guest"], push=False,
                    leg_runner=lambda *a: {"status": "failed", "video": None, "error": "e"},
                    pusher=lambda t, s: pushed.append(s))
    assert not pushed


def test_dev_watch_checks_new_revisions_without_debounce(tmp_path):
    state = tmp_path / "s" / "state.json"
    calls = []

    def checker(*args):
        calls.append(args[2])
        return fake_summary(True)

    clock = [10_000.0]

    def run(rev):
        return check.dev_watch(state, lambda: clock[0], lambda _u: rev, checker, runtime_ready=lambda _rev: True)

    assert run("r1") == 0 and calls == ["r1"]
    assert run("r1") == 0 and calls == ["r1"]          # same revision: quiet
    clock[0] += 60
    assert run("r2") == 0 and calls == ["r1", "r2"]
    assert run("r2") == 0 and calls == ["r1", "r2"]
    assert run("r1") == 0 and calls == ["r1", "r2"]  # rollback
    assert json.loads(state.read_text())["last_revision"] == "r2"


def test_dev_watch_never_repeats_an_interrupted_call(tmp_path):
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"last_revision": "older"}))
    calls = []

    def interrupted(*args):
        calls.append(args[2])
        raise KeyboardInterrupt

    def run(revision):
        return check.dev_watch(state, lambda: 10, lambda _url: revision, interrupted, runtime_ready=lambda _rev: True)

    with pytest.raises(KeyboardInterrupt):
        run("current")
    assert run("current") == 0
    assert run("older") == 0
    assert calls == ["current"]
    assert json.loads(state.read_text())["last_result"] == {"status": "started"}


def test_dev_watch_defers_when_backend_is_behind(tmp_path):
    state = tmp_path / "state.json"
    calls = []

    def checker(*args):
        calls.append(args[2])
        return fake_summary(True)

    assert check.dev_watch(state, lambda: 10, lambda _url: "r", checker, runtime_ready=lambda _rev: False) == 0
    assert calls == []
    assert not state.exists()
    assert check.dev_watch(state, lambda: 11, lambda _url: "r", checker, runtime_ready=lambda _rev: True) == 0
    assert calls == ["r"]


def test_dev_watch_records_failure(tmp_path):
    state = tmp_path / "state.json"
    code = check.dev_watch(state, lambda: 1e6, lambda _u: "r1", lambda *a: fake_summary(False),
                           runtime_ready=lambda _rev: True)
    assert code == 1 and json.loads(state.read_text())["last_result"]["passed"] is False


def test_prod_leg_always_deletes_account(tmp_path, monkeypatch):
    deleted = []
    monkeypatch.setitem(sys.modules, "voice_call_web_real_test",
                        type("M", (), {"generate_speech": staticmethod(lambda *a: {})}))

    def create(target, path):
        path.write_text(json.dumps({"email": "a@example.org", "password": "p"}))
        return {"email": "a@example.org"}

    def boom(*a, **k):
        raise RuntimeError("playwright crashed")

    monkeypatch.setattr(check, "create_account", create)
    monkeypatch.setattr(check, "delete_account", lambda t, e: deleted.append((t, e)))
    monkeypatch.setattr(check, "run_playwright", boom)
    with pytest.raises(RuntimeError):
        check.run_signed_in_prod(check.BASE_URLS["prod"], tmp_path)
    assert deleted == [("prod", "a@example.org")]


@pytest.mark.parametrize("signup_succeeds", [True, False])
def test_production_uses_one_test_gift_card_and_cleans_up(tmp_path, monkeypatch, signup_succeeds):
    monkeypatch.setattr(accounts, "HOME", tmp_path)
    codes = tmp_path / accounts.PROD_CODES_FILE
    codes.write_text("test-card-one\ntest-card-two\n")
    calls = []

    def browser_job(signup, mode):
        calls.append((mode, signup.get("gift_card_code")))
        if mode == "signup_only":
            status = "signup_only_done" if signup_succeeds else "harness_error"
            return {"status": status}
        return {"deletion": {"status": "deleted"}}

    monkeypatch.setattr(account, "_production_browser_job", browser_job)
    credentials = tmp_path / "credentials.json"
    if signup_succeeds:
        created = account.create("prod", credentials)
        assert credentials.stat().st_mode & 0o777 == 0o600
        assert "gift_card_code" not in json.loads(credentials.read_text())
        assert account.delete("prod", created["email"]) == {"deleted": True}
    else:
        with pytest.raises(account.AccountError, match="redemption failed"):
            account.create("prod", credentials)
        assert not credentials.exists()

    assert calls == [("signup_only", "test-card-one"), ("delete_only", None)]
    assert codes.read_text() == "test-card-two\n"
    registry = accounts.latest_by_email()
    assert len(registry) == 1
    email, entry = next(iter(registry.items()))
    assert entry["status"] == "deleted"
    assert accounts.load_secret(email) is None


def test_run_leg_turns_launch_failure_into_failed_result(tmp_path, monkeypatch):
    def no_slot(*a):
        raise check.CheckError("no slot")

    monkeypatch.setattr(check, "run_guest", no_slot)
    result = check.run_leg("guest", "dev", "https://x", "abc", tmp_path)
    assert result["status"] == "failed" and "no slot" in result["error"]
