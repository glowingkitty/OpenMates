#!/usr/bin/env python3
"""Static, repository-scoped Mac readiness metadata without native execution.

This fixed helper receives one typed JSON request. It never invokes Git, Xcode,
Simulator, a shell, or source from the checkout. Native workloads remain closed
until descendant Seatbelt denials can be reported reliably to the wrapper.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import plistlib
import re
import stat
import sys
import types

POLICY_CODE = None
if POLICY_CODE is None:
    import _apple_repository_policy as policy
else:
    policy = types.ModuleType('_apple_repository_policy')
    exec(POLICY_CODE, policy.__dict__)

MAX_REQUEST = 4096
MAX_METADATA = 1024 * 1024
MAX_ENTRIES = 64
SHA = re.compile(r'[0-9a-fA-F]{40}\Z')
REF = re.compile(r'refs/(?:heads|tags)/[A-Za-z0-9._/-]+\Z')
XCODE = Path('/Applications/Xcode.app')
SYSTEM_RUNTIMES = Path('/Library/Developer/CoreSimulator/Profiles/Runtimes')
SDK_PLATFORMS = ('iPhoneOS', 'iPhoneSimulator', 'MacOSX', 'WatchOS', 'WatchSimulator')


class RequestError(ValueError):
    pass


def regular_bytes(path):
    """Read only bounded regular metadata, never a symlink or device."""
    path = Path(path)
    policy.canonical_directory(path.parent)
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError as exc:
        raise RequestError('metadata symlink or unavailable file refused') from exc
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_METADATA:
            raise RequestError('bounded regular metadata file required')
        data = os.read(descriptor, MAX_METADATA + 1)
    finally:
        os.close(descriptor)
    if len(data) > MAX_METADATA:
        raise RequestError('metadata changed while reading')
    return data


def git_head(root):
    git = root / '.git'
    head = regular_bytes(git / 'HEAD').decode('ascii').strip()
    if SHA.fullmatch(head):
        return head.lower()
    if not head.startswith('ref: '):
        raise RequestError('unsupported Git HEAD format')
    ref = head[5:]
    if not REF.fullmatch(ref) or any(part in ('.', '..') for part in ref.split('/')):
        raise RequestError('invalid Git HEAD reference')
    loose = git / ref
    if loose.exists() or loose.is_symlink():
        value = regular_bytes(loose).decode('ascii').strip()
        if not SHA.fullmatch(value):
            raise RequestError('invalid loose Git reference')
        return value.lower()
    packed = git / 'packed-refs'
    if not packed.exists():
        raise RequestError('Git HEAD reference unavailable')
    for line in regular_bytes(packed).decode('ascii').splitlines():
        value, _, name = line.partition(' ')
        if name == ref and SHA.fullmatch(value):
            return value.lower()
    raise RequestError('Git HEAD reference unavailable')


def listed_entries(path, suffix, *, directories):
    """A bounded directory-name inventory; no account tree or file content."""
    path = Path(path)
    if not path.exists():
        return {'present': False, 'names': []}
    policy.canonical_directory(path)
    names = []
    count = 0
    with os.scandir(path) as entries:
        for entry in entries:
            count += 1
            if count > MAX_ENTRIES:
                raise RequestError('metadata directory entry limit exceeded')
            wanted = entry.is_dir(follow_symlinks=False) if directories else entry.is_file(follow_symlinks=False)
            if entry.name.endswith(suffix) and wanted:
                names.append(entry.name)
    return {'present': True, 'names': sorted(names)}


def workspace_info(root):
    return {'status': 'passed', 'policy_version': policy.POLICY_VERSION,
            'checkout': policy.identity(root), 'remote_head': git_head(root),
            'dirty_status': 'unverified_without_git_execution'}


def doctor(root):
    result = workspace_info(root)
    result['doctor_scope'] = 'static_metadata_only'
    developer = XCODE / 'Contents/Developer'
    version = XCODE / 'Contents/version.plist'
    try:
        version_info = plistlib.loads(regular_bytes(XCODE / 'Contents/Info.plist'))
        build_info = plistlib.loads(regular_bytes(version))
        result['xcode_version'] = str(version_info.get('CFBundleShortVersionString') or 'unknown')[:64]
        result['xcode_build'] = str(build_info.get('ProductBuildVersion') or 'unknown')[:64]
    except (OSError, ValueError, TypeError, plistlib.InvalidFileException):
        result['xcode_version'] = 'unavailable'
        result['xcode_build'] = 'unavailable'
    result['developer_directory_present'] = developer.is_dir() and not developer.is_symlink()
    result['xcodebuild_binary_present'] = (developer / 'usr/bin/xcodebuild').is_file() and not (developer / 'usr/bin/xcodebuild').is_symlink()
    result['sdks'] = {name: listed_entries(developer / 'Platforms' / (name + '.platform') / 'Developer/SDKs', '.sdk', directories=True)
                      for name in SDK_PLATFORMS}
    result['system_simulator_runtimes'] = listed_entries(SYSTEM_RUNTIMES, '.simruntime', directories=True)
    result['project_present'] = (root / 'apple/OpenMates.xcodeproj/project.pbxproj').is_file()
    result['scheme_files'] = listed_entries(root / 'apple/OpenMates.xcodeproj/xcshareddata/xcschemes', '.xcscheme', directories=False)
    result['native_execution'] = 'unsupported_descendant_seatbelt_stop_not_observable'
    return result


def execute(request):
    if not isinstance(request, dict) or set(request) != {'action', 'repo'}:
        raise RequestError('exact typed request fields required')
    if not isinstance(request['action'], str) or request['action'] not in {'workspace-info', 'doctor'}:
        raise RequestError('native workload unsupported: descendant Seatbelt stop is not observable')
    if not isinstance(request['repo'], str):
        raise RequestError('absolute OpenMates checkout path required')
    # The shared policy parser reads .git/config; bound that input first.
    candidate = policy.canonical_directory(request['repo'])
    regular_bytes(candidate / '.git/config')
    root = policy.verify_checkout(request['repo'], 'OpenMates')
    if root.name != 'OpenMates':
        raise RequestError('unexpected OpenMates checkout name')
    return workspace_info(root) if request['action'] == 'workspace-info' else doctor(root)


def main():
    try:
        raw = sys.stdin.buffer.read(MAX_REQUEST + 1)
        if len(raw) > MAX_REQUEST:
            raise RequestError('native request exceeds 4 KiB')
        result = execute(json.loads(raw))
        print(json.dumps(result))
        return 0
    except (OSError, ValueError, TypeError, KeyError, UnicodeError) as exc:
        print(json.dumps({'status': 'failed', 'error': type(exc).__name__ + ': ' + str(exc)}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
