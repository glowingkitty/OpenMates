"""Common nonroot container PID1 lifecycle holder; never reads memory counters.

The application retains its exact ordinary executable path, argv, cwd, env and
stdio. All supervisor overhead belongs to the explicitly reported container total.
"""

import json
import os
import signal
import time
from pathlib import Path


class System:
    def __init__(self):
        self.contained = None

    def prepare_meter(self, cfg, root):
        # -I startup deliberately has no script-dir import fallback. The existing
        # CI owner pins and readonly-mounts this exact finite adapter and binary.
        import hashlib
        import importlib.util
        import sys
        adapter = Path(cfg["meter"]["adapter"])
        if not adapter.is_absolute() or adapter.is_symlink() or hashlib.sha256(adapter.read_bytes()).hexdigest() != cfg["meter"]["adapterSha256"]:
            raise ValueError("pinned_contained_adapter")
        spec = importlib.util.spec_from_file_location("openmates_contained_meter_adapter", adapter)
        if spec is None or spec.loader is None:
            raise ValueError("contained_adapter_loader")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        if module.digest(cfg["meter"]["binary"]) != cfg["meter"]["binarySha256"]:
            raise ValueError("pinned_contained_binary")
        self.contained = module.Inside(cfg, root)
        return self.contained

    def pid(self):
        return os.getpid()

    def uid(self):
        return os.geteuid()

    def now(self):
        return time.monotonic_ns()

    def sleep(self):
        time.sleep(0.01)

    def launch(self, cfg):
        child = os.fork()
        if child == 0:
            try:
                for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
                    signal.signal(sig, signal.SIG_DFL)
                os.setsid()
                os.chdir(cfg["cwd"])
                os.execvpe(cfg["argv"][0], cfg["argv"], cfg["env"])
            except BaseException:
                os._exit(127)
        return child

    def reap(self):
        try:
            return os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            return None

    def terminate_namespace(self, sig):
        # Runtime entry refuses unless this is the private container's nonroot PID1.
        # All other namespace processes descend from its one application child.
        try:
            os.kill(-1, sig)
        except ProcessLookupError:
            pass

    def requested(self, root, label):
        return (root / label).is_file()

    def record(self, root, row):
        raw = json.dumps(row, separators=(",", ":")).encode()
        path = root / "status.tmp"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        try:
            os.write(fd, raw)
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(path, root / "status.json")


def supervise(cfg, root, system=None, cancelled=None):
    system = system or System()
    cancelled = cancelled or [False]
    if system.pid() != 1 or system.uid() == 0:
        return 125
    deadline = cfg["deadlineNs"]
    work_end = cfg["workDeadlineNs"]
    grace = cfg["termGraceNs"]
    child = None
    code = None
    term_at = None
    kill_sent = False
    reaped = 0
    row = {
        "nonce": cfg["nonce"],
        "state": "ready",
        "applicationExit": None,
        "childrenDrained": False,
        "cancelled": False,
    }
    meter = system.prepare_meter(cfg, root) if cfg.get("meter") is not None else None
    system.record(root, row)
    if meter is not None:
        meter.admit()
    while not system.requested(root, "go"):
        if cancelled[0] or system.now() >= work_end:
            return 125
        system.sleep()
    if cancelled[0]:
        return 125
    child = meter.fork_meter() if meter is not None else system.launch(cfg)
    while system.now() < deadline:
        if meter is not None:
            meter.poll()
        # One terminal-wait owner for both original child and adopted descendants.
        found = system.reap()
        if found is None:
            if code is None:
                return 125
            break
        pid, status = found
        if pid:
            reaped += 1
            if pid == child:
                code = os.waitstatus_to_exitcode(status)
            continue
        if cancelled[0] or system.now() >= work_end:
            if term_at is None:
                term_at = system.now()
                system.terminate_namespace(signal.SIGTERM)
            elif not kill_sent and system.now() - term_at >= grace:
                system.terminate_namespace(signal.SIGKILL)
                kill_sent = True
        system.sleep()
    else:
        return 125
    row.update(
        state="held",
        applicationExit=code,
        childrenDrained=True,
        cancelled=cancelled[0] or term_at is not None,
        reapedChildren=reaped,
    )
    if meter is not None:
        row["containedMeter"] = meter.completed()
    system.record(
        root, row
    )  # Allocate/write terminal metadata BEFORE outside peak read.
    while not system.requested(root, "release"):
        if system.now() >= deadline:
            return 125
        system.sleep()
    return 125 if row["cancelled"] else code if 0 <= code <= 255 else 128 - code


def main():
    import sys

    cfg = json.loads(Path(sys.argv[1]).read_bytes())
    root = Path(sys.argv[1]).parent
    if not (
        os.getpid() == 1
        and os.geteuid() != 0
        and type(cfg.get("argv")) is list
        and cfg["argv"]
        and os.path.isabs(cfg["argv"][0])
    ):
        return 125
    cancelled = [False]

    def stop(signum, frame):
        cancelled[0] = True

    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, stop)
    system = System()
    try:
        return supervise(cfg, root, system=system, cancelled=cancelled)
    except BaseException:
        if system.contained is not None:
            try:
                system.record(root, {"nonce": cfg["nonce"], "state": "failed", "childrenDrained": False,
                    "containedMeterPartial": {"kernelGate": system.contained.gate, "final": system.contained.final,
                    "markerCount": system.contained.sequence}})
            except BaseException:
                pass
        raise
    finally:
        if system.contained is not None:
            system.contained.close()


if __name__ == "__main__":
    raise SystemExit(main())
