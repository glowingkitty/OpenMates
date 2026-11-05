"""Finite PID1 negative admission probes, then the exact frozen supervisor.

No positive admission override, alternate supervisor lifecycle or app accounting.
"""
import array
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

SUPERVISOR_SHA256 = "69e4f7ae9d2e716f45ff3facd494ae8ac149c96fac619a4dfed157ebbf804b3f"
NEGATIVES = ("non-socket", "duplicate-channel", "wrong-peer", "wrong-namespace-type", "non-namespace", "extra-fd", "named-channel")


def wrong_peer_pair():
    channel, sender = socket.socketpair()
    child = os.fork()
    if child == 0:
        channel.close()
        first, second = socket.socketpair()
        descriptors = array.array("i", (first.fileno(), second.fileno()))
        sender.sendmsg([b"fds"], [(socket.SOL_SOCKET, socket.SCM_RIGHTS, descriptors)])
        os._exit(0)
    sender.close()
    data, ancillary, flags, _ = channel.recvmsg(3, socket.CMSG_SPACE(8))
    channel.close()
    waited, status = os.waitpid(child, 0)
    assert waited == child and status == 0 and data == b"fds" and not flags
    assert len(ancillary) == 1 and ancillary[0][:2] == (socket.SOL_SOCKET, socket.SCM_RIGHTS)
    descriptors = array.array("i")
    descriptors.frombytes(ancillary[0][2])
    assert len(descriptors) == 2
    return socket.socket(fileno=descriptors[0]), socket.socket(fileno=descriptors[1])


def preflight(cfg, root):
    assert os.getpid() == 1 and os.geteuid() > 0 and os.getegid() > 0
    rows = []
    for name in NEGATIVES:
        owned = []
        endpoint = None
        extra = []
        nsfd = None
        try:
            first, second = wrong_peer_pair() if name == "wrong-peer" else socket.socketpair()
            third, fourth = socket.socketpair()
            owned += [first, second, third, fourth]
            nsfd = os.open("/proc/self/ns/pid", os.O_RDONLY)
            data, control, namespace = second.fileno(), fourth.fileno(), nsfd
            if name == "non-socket":
                read_end, data = os.pipe()
                pipe_observer = os.fdopen(read_end, "rb", buffering=0)
                owned.append(pipe_observer)
                extra.append(data)
            elif name == "duplicate-channel":
                control = os.dup(data)
                extra.append(control)
            elif name == "wrong-namespace-type":
                namespace = os.open("/proc/self/ns/net", os.O_RDONLY)
                extra.append(namespace)
            elif name == "non-namespace":
                namespace = os.open("/dev/null", os.O_RDONLY)
                extra.append(namespace)
            elif name == "extra-fd":
                extra.append(os.open("/dev/null", os.O_RDONLY))
            elif name == "named-channel":
                endpoint = root / "negative.sock"
                directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                    connector = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                    owned += [listener, connector]
                    alias = f"/proc/self/fd/{directory}/negative.sock"
                    listener.bind(alias)
                    listener.listen(1)
                    connector.connect(alias)
                    accepted, _ = listener.accept()
                    owned.append(accepted)
                    data = accepted.fileno()
                finally:
                    os.close(directory)
            control_peer = first if name == "duplicate-channel" else third
            control_peer.sendall(f"D {time.monotonic_ns() + 1_500_000_000}\n".encode())
            observer = pipe_observer if name == "non-socket" else connector if name == "named-channel" else first
            argv = [cfg["meter"]["binary"], str(data), "--owned-memory-v3-contained", "pinned-typescript-owned-tree", str(control), "ephemeral-command", str(namespace), "--", *cfg["argv"]]
            fds = tuple(sorted(set((data, control, namespace, *extra))))
            result = subprocess.run(argv, pass_fds=fds, stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    env=cfg["env"], timeout=2)
            # Gate success emits an authenticated measurement frame before any
            # measured fork. Rejection requires no such frame and no app output.
            os.set_blocking(observer.fileno(), False)
            try:
                frame = os.read(observer.fileno(), 32769)
            except BlockingIOError:
                frame = b""
            assert result.returncode == 125 and not frame and not result.stdout and not result.stderr, name
            rows.append({"case": name, "status": "refused-before-measured-fork", "returncode": result.returncode, "kernelGateFrames": 0})
        finally:
            for item in owned:
                item.close()
            if nsfd is not None:
                os.close(nsfd)
            for fd in extra:
                os.close(fd)
            if endpoint is not None:
                endpoint.unlink()
    (root / "negative-kernel-gates.json").write_text(json.dumps({"cases": rows, "nonzeroCapabilityRuntimeProbe": "unavailable-no-privilege-grant", "acceptanceEligible": False}))


def main():
    cfg = json.loads(Path(sys.argv[1]).read_bytes())
    root = Path(sys.argv[1]).parent
    if cfg["env"].get("OPENMATES_CONTAINED_PREFLIGHT") == "1":
        preflight(cfg, root)
    original = Path(__file__).with_name("ci_client_memory_supervisor.py")
    assert hashlib.sha256(original.read_bytes()).hexdigest() == SUPERVISOR_SHA256
    spec = importlib.util.spec_from_file_location("ci_contained_original_supervisor", original)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.main()


if __name__ == "__main__":
    raise SystemExit(main())
