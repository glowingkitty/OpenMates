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


@pytest.mark.parametrize("receipt,video,loudness,status,fragment", [
    (None, True, loud, "blocked", "no receipt"),
    ({"status": "failed", "error_code": "boom"}, True, loud, "failed", "boom"),
    ({"status": "passed", "played_audio": []}, True, loud, "failed", "no spoken reply"),
    ({"status": "passed", "played_audio": ["a"]}, False, loud, "blocked", "no with-audio video"),
    ({"status": "passed", "played_audio": ["a"]}, True, lambda v: -80.0, "blocked", "silent"),
])
def test_failures(tmp_path, receipt, video, loudness, status, fragment):
    result = check.evaluate_leg(leg_dir(tmp_path, receipt, video), loudness)
    assert result["status"] == status and fragment in result["error"]


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


def test_dev_watch_records_failure_after_retry_and_sends_once(tmp_path):
    state = tmp_path / "state.json"
    clock = [10_000]
    calls, pushes = [], []

    def checker(target, base, revision, out, legs, push):
        assert not push
        calls.append(legs)
        return fake_summary(False)

    def run():
        return check.dev_watch(state, lambda: clock[0], lambda _u: "r1", checker,
                               runtime_ready=lambda _rev: True, pusher=lambda t, s: pushes.append(s))

    assert run() == 0 and not pushes
    clock[0] += check.RETRY_DELAY - 1
    assert run() == 0 and not pushes
    clock[0] += 1
    assert run() == 1 and len(pushes) == 1
    assert run() == 0 and len(pushes) == 1
    assert calls == [list(check.LEGS), ["guest"]]
    assert pushes[0]["retried"] and not json.loads(state.read_text())["last_result"]["passed"]


def test_incident_combines_blocked_sign_in_and_guest_timeout_after_retry(tmp_path):
    signed_dir = tmp_path / "signed"
    guest_dir = tmp_path / "guest"
    signed_dir.mkdir()
    guest_dir.mkdir()
    signed_in = check.evaluate_leg(leg_dir(signed_dir, {
        "status": "failed", "error_code": "lease_unavailable",
        "error_detail": "docker exec api failed: container 123456789abcdef is not running",
    }, video=False))
    guest = check.evaluate_leg(leg_dir(guest_dir, {
        "status": "failed", "error": "expect toBeVisible timed out for getByTestId('message-user')",
    }, video=False))
    assert (signed_in["status"], guest["status"]) == ("blocked", "failed")
    state = tmp_path / "state.json"
    clock = [10_000]
    calls, pushes = [], []

    def checker(*args):
        calls.append(args[4])
        return {"passed": False, "legs": {"signed_in": signed_in, "guest": guest}}

    def run(ready):
        return check.dev_watch(state, lambda: clock[0], lambda _u: "r1", checker,
                               runtime_ready=lambda _rev: ready,
                               pusher=lambda target, summary: pushes.append(check.failure_message(target, summary)))

    assert run(True) == 0 and not pushes
    clock[0] += check.RETRY_DELAY
    assert run(False) == 0 and len(calls) == 1 and not pushes
    assert run(True) == 1 and len(calls) == 2 and len(pushes) == 1
    preview, detail = pushes[0].splitlines()
    assert preview == "The dev voice check is incomplete after the update."
    assert "The signed-in call check could not start while the dev API was unavailable." in detail
    assert "The guest call check timed out waiting for the user's message." in detail
    assert "The checker retried the unresolved checks." in detail
    assert "A voice outage is unconfirmed." in detail
    assert "Hold the next production rollout" in detail
    assert "lease_unavailable" not in pushes[0] and "123456789abcdef" not in pushes[0]
    assert run(True) == 0 and len(pushes) == 1


def test_retry_success_sends_nothing_and_keeps_first_passing_leg(tmp_path):
    state = tmp_path / "state.json"
    clock = [10_000]
    found = []

    def checker(*args):
        found.append(args[4])
        if len(found) == 1:
            return {"passed": False, "legs": {"signed_in": {"status": "passed"},
                                             "guest": {"status": "blocked"}}}
        return fake_summary(True)

    def run():
        return check.dev_watch(state, lambda: clock[0], lambda _u: "r1", checker,
                               runtime_ready=lambda _rev: True, pusher=lambda *_: pytest.fail("unexpected alert"))

    assert run() == 0
    clock[0] += check.RETRY_DELAY
    assert run() == 0
    assert found == [list(check.LEGS), ["guest"]]
    assert json.loads(state.read_text())["last_result"] == {
        "passed": True, "legs": {"signed_in": "passed", "guest": "passed"},
    }


def test_retry_expires_while_prerequisite_is_still_unavailable(tmp_path):
    state = tmp_path / "state.json"
    clock = [10_000]
    calls, pushes = [], []

    def checker(*args):
        calls.append(args[4])
        return {"passed": False, "legs": {"guest": {"status": "blocked"}}}

    def run(ready):
        return check.dev_watch(state, lambda: clock[0], lambda _u: "r1", checker,
                               runtime_ready=lambda _rev: ready,
                               pusher=lambda target, summary: pushes.append(check.failure_message(target, summary)))

    assert run(True) == 0
    clock[0] += check.RETRY_WINDOW - 1
    assert run(False) == 0 and not pushes
    clock[0] += 1
    assert run(False) == 1 and len(calls) == 1
    assert "the retry window ended" in pushes[0] and "Nothing needed from you" in pushes[0]
    assert run(False) == 0 and len(pushes) == 1


def test_new_revision_supersedes_waiting_retry_even_if_not_yet_ready(tmp_path):
    state = tmp_path / "state.json"
    calls = []

    def checker(*args):
        calls.append(args[2])
        return fake_summary(False)

    def run(revision, ready):
        return check.dev_watch(state, lambda: 10, lambda _u: revision, checker,
                               runtime_ready=lambda _rev: ready, pusher=lambda *_: pytest.fail("unexpected alert"))

    assert run("r1", True) == 0
    assert run("r2", False) == 0
    assert "retry" not in json.loads(state.read_text())
    assert run("r1", True) == 0 and calls == ["r1"]


def test_unchanged_failure_across_revisions_alerts_only_after_recovery(tmp_path):
    state = tmp_path / "state.json"
    clock = [10_000]
    pushes = []

    def run(revision, passes=False):
        return check.dev_watch(state, lambda: clock[0], lambda _u: revision, lambda *a: fake_summary(passes),
                               runtime_ready=lambda _rev: True, pusher=lambda t, s: pushes.append(s))

    assert run("first") == 0
    clock[0] += check.RETRY_DELAY
    assert run("first") == 1 and len(pushes) == 1
    assert run("second") == 0
    clock[0] += check.RETRY_DELAY
    assert run("second") == 0 and len(pushes) == 1
    assert run("recovered", passes=True) == 0
    assert run("new-failure") == 0
    clock[0] += check.RETRY_DELAY
    assert run("new-failure") == 1 and len(pushes) == 2


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


def test_run_leg_turns_launch_failure_into_blocked_result(tmp_path, monkeypatch):
    def no_slot(*a):
        raise check.CheckError("no slot")

    monkeypatch.setattr(check, "run_guest", no_slot)
    result = check.run_leg("guest", "dev", "https://x", "abc", tmp_path)
    assert result["status"] == "blocked" and "no slot" in result["error"]



def test_failed_runner_log_checks_for_real_disk_exhaustion(tmp_path):
    (tmp_path / "run.log").write_text("OSError: [Errno 28] No space left on device")
    result = check.evaluate_leg(tmp_path)
    assert result["status"] == "blocked"
    assert result["reason"] == "disk_space"


def test_signed_in_runner_receives_a_fresh_output_path(tmp_path, monkeypatch):
    out = tmp_path / "signed_in"

    def run(command, *, stdout, **kwargs):
        assert command[command.index("--output-dir") + 1] == str(out)
        assert not out.exists()
        stdout.write("OSError: [Errno 28] No space left on device")

    monkeypatch.setattr(check.subprocess, "run", run)
    check.run_signed_in_dev("revision", out)
    assert check.evaluate_leg(out)["reason"] == "disk_space"


def test_actual_disk_failure_cleans_alerts_once_and_retries_after_recovery(tmp_path, monkeypatch):
    state = tmp_path / "state.json"
    clock = [10_000]
    free = [check.MIN_FREE - 2_000_000_000]
    calls, cleanup, pushes = [], [], []
    monkeypatch.setattr(check, "_free_space", lambda: free[0])
    monkeypatch.setattr(check, "_request_disk_cleanup", lambda: cleanup.append(True))

    def checker(*args):
        calls.append(args[4])
        if len(calls) == 1:
            return {"passed": False, "legs": {"signed_in": {"status": "passed"}, "guest": check._blocked_disk()}}
        return fake_summary(True)

    def run():
        return check.dev_watch(state, lambda: clock[0], lambda _url: "r1", checker,
                               runtime_ready=lambda _rev: True,
                               pusher=lambda target, summary: pushes.append(check.failure_message(target, summary)))

    assert run() == 0 and cleanup == [True] and not pushes
    clock[0] += check.RETRY_DELAY
    free[0] += 1_000_000_000
    assert run() == 1
    assert pushes[0].splitlines()[0] == "Dev disk almost full, cleanup recovered 1.0 GB."
    assert calls == [list(check.LEGS)]
    clock[0] += check.RETRY_WINDOW
    assert run() == 0 and len(pushes) == 1
    free[0] += 2_000_000_000
    assert run() == 0
    assert calls == [list(check.LEGS), ["guest"]]
    assert json.loads(state.read_text())["last_result"]["passed"]
