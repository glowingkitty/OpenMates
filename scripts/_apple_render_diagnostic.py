"""Read-only diagnosis of the named TASK-752 Chrome failure.

Authorized by the fresh user instruction to diagnose and complete rendering.
This fixed program accepts no paths, commands, or confirmation arguments.
Apple Remote runs it beneath a deny-all-filesystem-writes sandbox.
It neither clears stop state nor retries the browser or any render operation.
"""
import json
import os
from pathlib import Path
import plistlib
import stat

RUN = Path('/Users/kitty/openmates-marketing/videos/remotion/renders/runs/4ee1ce49a798445794ac296af9bbed23')


def crash_summary(text):
    decoder = json.JSONDecoder()
    first, end = decoder.raw_decode(text)
    report = decoder.raw_decode(text[end:].lstrip())[0] if text[end:].strip() else first
    if report.get('pid') != 15585:
        return None
    summary = {key: report.get(key) for key in ('pid', 'procName', 'captureTime', 'exception', 'termination', 'asi', 'faultingThread')}
    summary['report_fields'] = sorted(report)
    threads = report.get('threads', [])
    index = report.get('faultingThread')
    if isinstance(index, int) and 0 <= index < len(threads):
        summary['faulting_frames'] = threads[index].get('frames', [])[:40]
    summary['confirmed_sandbox_unlink'] = (
        (report.get('termination') or {}).get('namespace') == 'SANDBOX'
        and any(frame.get('symbol') in {'unlink', '__unlink', 'unlinkat', '__unlinkat'}
                for frame in summary.get('faulting_frames', [])))
    for key in report:
        if 'sandbox' in key.lower() or 'violation' in key.lower():
            summary[key] = report[key]
    return summary


def main():
    evidence = {'classification': 'unexplained_SIGKILL_not_proven_deletion', 'pid': 15585, 'files': {}}
    evidence['launch_path_metadata'] = {}
    # Inspect names/links only. Never traverse a socket/profile symlink or read
    # the user's default browser data. This can reveal where the failed launch
    # placed its singleton socket without starting Chrome or deleting fixtures.
    for path in (RUN / 'tmp', RUN / 'browser-profile',
                 *(RUN / 'browser-profile' / name for name in ('SingletonSocket', 'SingletonCookie', 'SingletonLock', 'Crashpad'))):
        try:
            info = path.lstat()
            evidence['launch_path_metadata'][str(path)] = {
                'mode': stat.S_IFMT(info.st_mode),
                'link_target': os.readlink(path) if stat.S_ISLNK(info.st_mode) else None}
        except FileNotFoundError:
            evidence['launch_path_metadata'][str(path)] = {'exists': False}
    with open('/Applications/Google Chrome.app/Contents/Info.plist', 'rb') as file:
        evidence['chrome_version'] = plistlib.load(file).get('CFBundleShortVersionString')
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
    # `log show` explicitly refuses sandboxed execution on this Mac. Keep the
    # read-only boundary and inspect only PID-matched Chrome crash metadata.
    evidence['crash_reports'] = []
    for directory in (Path('/Users/kitty/Library/Logs/DiagnosticReports'), Path('/Library/Logs/DiagnosticReports')):
        if any(p.is_symlink() for p in (directory, *directory.parents)):
            raise ValueError('diagnostic directory contains symlink')
        candidates = sorted(directory.glob('Google Chrome*.ips'), reverse=True)[:50]
        for path in candidates:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            try:
                if os.fstat(fd).st_size > 2 * 1024 * 1024:
                    continue
                summary = crash_summary(os.read(fd, 2 * 1024 * 1024).decode())
                if summary:
                    evidence['crash_reports'].append({'file': str(path), 'summary': summary})
                    if summary['confirmed_sandbox_unlink']:
                        evidence['classification'] = 'sandbox_denied_unlink_target_path_unavailable'
            finally:
                os.close(fd)
    print(json.dumps(evidence))


if __name__ == '__main__':
    main()
