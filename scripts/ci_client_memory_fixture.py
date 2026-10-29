#!/usr/local/bin/python3 -I
"""Fixed harmless Linux fixtures; no product/account or external access."""
import json
import os
import resource
import sys
import threading


def main(mode):
    if mode not in ('leaf', 'threads', 'child'):
        raise ValueError('fixed fixture required')
    retained = bytearray(4 * 1024 * 1024)
    retained[::4096] = b'x' * (len(retained) // 4096)
    if mode == 'threads':
        barrier = threading.Barrier(3)
        def work():
            memory = bytearray(8 * 1024 * 1024)
            memory[::4096] = b'y' * (len(memory) // 4096)
            barrier.wait(timeout=5)
            barrier.wait(timeout=5)
        workers = [threading.Thread(target=work) for _ in range(2)]
        for worker in workers:
            worker.start()
        barrier.wait(timeout=5)
        barrier.wait(timeout=5)
        for worker in workers:
            worker.join(timeout=5)
            if worker.is_alive():
                raise RuntimeError('thread not drained')
    if mode == 'child':
        child = os.fork()
        if child == 0:
            allocation = bytearray(16 * 1024 * 1024)
            allocation[::4096] = b'z' * (len(allocation) // 4096)
            os._exit(0)
        if os.waitpid(child, 0) != (child, 0):
            raise RuntimeError('child not drained')
    print(json.dumps({'fixture': mode, 'unit': 'KiB',
        'rootThreadGroupPeakRssKiB': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        'wholeFixturePeakRssKiB': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss if mode != 'child' else None,
        'rssScope': 'one-known-thread-group' if mode != 'child' else 'root-only-child-aggregate-unavailable',
        'acceptanceEligible': False}))


if __name__ == '__main__':
    main(sys.argv[1])
