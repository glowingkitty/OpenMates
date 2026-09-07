"""Read-only diagnosis of the named TASK-752 Chrome failure.

Authorized by the fresh user instruction to diagnose and complete rendering.
This fixed program accepts no paths, commands, or confirmation arguments.
Apple Remote runs it beneath a deny-all-filesystem-writes sandbox.
It neither clears stop state nor retries the browser or any render operation.
"""
import json
import os
from pathlib import Path
import subprocess

RUN = Path('/Users/kitty/openmates-marketing/videos/remotion/renders/runs/4ee1ce49a798445794ac296af9bbed23')


def main():
    evidence = {'classification': 'unexplained_SIGKILL_not_proven_deletion', 'pid': 15585, 'files': {}}
    for name in ('browser.log', 'supervisor-result.json', 'bundle/stderr.log', 'bundle/result.json'):
        path = RUN / name
        if any(p.is_symlink() for p in (path, *path.parents)):
            raise ValueError('diagnostic path contains symlink')
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        except FileNotFoundError:
            continue
        try:
            os.lseek(fd, max(0, os.fstat(fd).st_size - 65536), os.SEEK_SET)
            evidence['files'][name] = os.read(fd, 65536).decode(errors='replace')
        finally:
            os.close(fd)
    result = subprocess.run(['/usr/bin/log', 'show', '--last', '24h', '--style', 'ndjson',
                             '--predicate', 'eventMessage CONTAINS "15585" AND (process == "kernel" OR process == "sandboxd")'],
                            capture_output=True, text=True, timeout=45,
                            env={'PATH': '/usr/bin:/bin'})
    evidence['os_log'] = {'exit_code': result.returncode, 'stdout': result.stdout[-65536:], 'stderr': result.stderr[-3000:]}
    print(json.dumps(evidence))


if __name__ == '__main__':
    main()
