"""Bounded Linux child-group lifecycle; import is inert, no product-specific code."""

import json
import os
import signal
import subprocess
import time
from pathlib import Path

SIGNALS = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)


def group_state(group):
    live = []
    zombies = []
    unknown = False
    try:
        entries = list(Path("/proc").iterdir())
    except OSError:
        return {"live": [], "zombies": [], "inspectionUnknown": True}
    for p in entries:
        if not p.name.isdigit():
            continue
        try:
            fields = (p / "stat").read_text().rsplit(")", 1)[1].split()
            if int(fields[2]) == group:
                (zombies if fields[0] in ("Z", "X") else live).append(int(p.name))
        except (FileNotFoundError, ProcessLookupError):
            continue
        except (OSError, ValueError, IndexError):
            unknown = True
    return {"live": live, "zombies": zombies, "inspectionUnknown": unknown}


def anchored(child):
    # WNOWAIT preserves the owned leader PID even after exit, avoiding PGID reuse.
    try:
        os.waitid(os.P_PID, child.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
        return True
    except ChildProcessError:
        return False


def exited(child):
    return (
        os.waitid(os.P_PID, child.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is not None
    )


def drain(child, term_seconds=3, kill_seconds=3):
    result = {
        "scope": "owned inherited process group",
        "anchorHeld": False,
        "liveMembersDrained": False,
        "groupEmpty": False,
        "inspectionUnknown": True,
        "directChildReaped": False,
    }
    if not anchored(child):
        return result
    result["anchorHeld"] = True
    for signum, seconds in (
        (signal.SIGTERM, term_seconds),
        (signal.SIGKILL, kill_seconds),
    ):
        # The unreaped direct child retains this process-group identity throughout.
        try:
            os.killpg(child.pid, signum)
        except ProcessLookupError:
            pass
        deadline = time.monotonic() + seconds
        while True:
            state = group_state(child.pid)
            if not state["live"] and not state["inspectionUnknown"]:
                break
            if time.monotonic() >= deadline:
                break
            time.sleep(min(0.02, max(0, deadline - time.monotonic())))
        if not state["live"] and not state["inspectionUnknown"]:
            break
    result.update(
        liveMembersDrained=not state["live"] and not state["inspectionUnknown"],
        inspectionUnknown=state["inspectionUnknown"],
        remainingLiveMembers=len(state["live"]),
        remainingZombieMembers=len(state["zombies"]),
    )
    try:
        child.wait(timeout=0.1)
        result["directChildReaped"] = True
    except subprocess.TimeoutExpired:
        pass
    final = group_state(child.pid)
    result["groupEmpty"] = (
        not final["live"] and not final["zombies"] and not final["inspectionUnknown"]
    )
    return result


def run_owned(argv, *, cwd, env, out, attempt, timeout=1800):
    """Handlers are active before launch; cancellation during Popen is deferred.

    Only the inherited group is covered. Detached/setsid children are outside this
    contract. Unknown inspection or unverified drain always makes the run fail.
    """
    out = Path(out)
    child = None
    log = None
    cancel = []
    previous = {}
    code = 1
    reason = "launch_failed"
    cleanup = None

    def interrupted(signum, frame):
        if not cancel:
            cancel.append(signum)

    def save():
        temporary = out / "attempt.next.json"
        temporary.write_text(json.dumps(attempt, indent=2) + "\n")
        temporary.replace(out / "attempt.json")

    try:
        # No asynchronous exception can cross Popen before ownership is recorded.
        for signum in SIGNALS:
            previous[signum] = signal.signal(signum, interrupted)
        if signal.getsignal(signal.SIGCHLD) not in (signal.SIG_DFL, None):
            raise RuntimeError("child_reaping_policy")
        attempt.update(status="started", cleanupVerified=False)
        save()
        log = (out / "process.log").open("xb")
        if cancel:
            reason = "interrupted"
            code = 128 + cancel[0]
        else:
            child = subprocess.Popen(
                argv,
                cwd=cwd,
                env=env,
                start_new_session=True,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            deadline = time.monotonic() + timeout
            while True:
                if cancel:
                    reason = "interrupted"
                    code = 128 + cancel[0]
                    break
                if exited(child):
                    reason = "exited"
                    break
                if time.monotonic() >= deadline:
                    reason = "timeout"
                    code = 124
                    break
                time.sleep(min(0.02, max(0, deadline - time.monotonic())))
    except BaseException:
        reason = "interrupted" if cancel else "lifecycle_failed"
        code = 128 + cancel[0] if cancel else 1
    finally:
        # Repeated signals remain deferred until owned cleanup and terminal receipt.
        if child is not None:
            try:
                cleanup = drain(child)
            except BaseException:
                cleanup = {
                    "scope": "owned inherited process group",
                    "liveMembersDrained": False,
                    "inspectionUnknown": True,
                    "directChildReaped": False,
                }
            if reason == "exited":
                code = child.returncode if child.returncode is not None else 1
            if not (
                cleanup.get("liveMembersDrained") and cleanup.get("directChildReaped")
            ):
                code = 1
                reason = "cleanup_unverified"
        if cancel and reason not in ("cleanup_unverified",):
            reason = "interrupted"
            code = 128 + cancel[0]
        if log is not None:
            log.close()
        attempt.update(
            status="interrupted"
            if reason == "interrupted"
            else "completed"
            if code == 0
            else "failed",
            reason=reason,
            returncode=code,
            signal=cancel[0] if cancel else None,
            reportWritten=(out / "result.json").is_file(),
            cleanup=cleanup,
            cleanupVerified=bool(
                cleanup
                and cleanup.get("liveMembersDrained")
                and cleanup.get("directChildReaped")
            ),
        )
        try:
            save()
        finally:
            for signum, handler in previous.items():
                signal.signal(signum, handler)
    return code
