"""Serialize integration preparation and push among cooperating deployments."""
from contextlib import contextmanager
import fcntl
import time


@contextmanager
def admission_lock(path, *, timeout=900, poll=0.25):
    if timeout <= 0 or poll <= 0:
        raise ValueError("Admission timeout and poll must be positive")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RuntimeError("Deployment admission timed out; another deployment is preparing or pushing")
                time.sleep(min(poll, remaining))
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
