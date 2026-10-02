"""Static Apple readiness must not execute Mac tools or admit native workloads."""
# contract-test-file: tooling
from __future__ import annotations

import importlib
import json
from pathlib import Path
import plistlib
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture
def static_mac(tmp_path, monkeypatch):
    native = importlib.import_module('_apple_native_remote')
    root = tmp_path / 'OpenMates'
    (root / '.git/refs/heads').mkdir(parents=True)
    (root / '.git/config').write_text(
        '[remote "origin"]\nurl = https://github.com/glowingkitty/OpenMates.git\n'
        '[core]\nfsmonitor = /tmp/untrusted-hook\n')
    (root / '.git/HEAD').write_text('ref: refs/heads/dev\n')
    (root / '.git/refs/heads/dev').write_text('a' * 40 + '\n')
    project = root / 'apple/OpenMates.xcodeproj'
    (project / 'xcshareddata/xcschemes').mkdir(parents=True)
    (project / 'project.pbxproj').write_text('project')
    (project / 'xcshareddata/xcschemes/OpenMates_iOS.xcscheme').write_text('scheme')
    xcode = tmp_path / 'Applications/Xcode.app'
    developer = xcode / 'Contents/Developer'
    (developer / 'usr/bin').mkdir(parents=True)
    (developer / 'usr/bin/xcodebuild').write_text('binary fixture')
    (developer / 'Platforms/iPhoneSimulator.platform/Developer/SDKs/iPhoneSimulator26.sdk').mkdir(parents=True)
    (xcode / 'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleShortVersionString': '26.0'}))
    (xcode / 'Contents/version.plist').write_bytes(plistlib.dumps({'ProductBuildVersion': '26A1'}))
    runtimes = tmp_path / 'Library/Developer/CoreSimulator/Profiles/Runtimes'
    (runtimes / 'iOS 26.simruntime').mkdir(parents=True)
    monkeypatch.setattr(native, 'XCODE', xcode)
    monkeypatch.setattr(native, 'SYSTEM_RUNTIMES', runtimes)
    return native, root


def test_static_doctor_reads_bounded_metadata_without_running_git_or_xcode(static_mac, monkeypatch):
    native, root = static_mac
    monkeypatch.setattr(subprocess, 'run', lambda *args, **kwargs:
                        pytest.fail('static doctor invoked an executable'))
    result = native.execute({'action': 'doctor', 'repo': str(root)})
    assert result['status'] == 'passed'
    assert result['remote_head'] == 'a' * 40
    assert result['dirty_status'] == 'unverified_without_git_execution'
    assert result['xcode_version'] == '26.0'
    assert result['xcode_build'] == '26A1'
    assert result['sdks']['iPhoneSimulator']['names'] == ['iPhoneSimulator26.sdk']
    assert result['system_simulator_runtimes']['names'] == ['iOS 26.simruntime']
    assert result['scheme_files']['names'] == ['OpenMates_iOS.xcscheme']
    assert result['native_execution'] == 'unsupported_descendant_seatbelt_stop_not_observable'


def test_workspace_info_rejects_symlink_git_head_and_ignores_fsmonitor(static_mac, tmp_path, monkeypatch):
    native, root = static_mac
    monkeypatch.setattr(subprocess, 'run', lambda *args, **kwargs:
                        pytest.fail('Git hook or subprocess invoked'))
    assert native.execute({'action': 'workspace-info', 'repo': str(root)})['remote_head'] == 'a' * 40
    head = root / '.git/HEAD'
    head.unlink()
    outside = tmp_path / 'outside-head'
    outside.write_text('b' * 40)
    head.symlink_to(outside)
    with pytest.raises(native.RequestError, match='symlink'):
        native.execute({'action': 'workspace-info', 'repo': str(root)})
    head.unlink()
    import os
    os.mkfifo(head)
    with pytest.raises(native.RequestError, match='bounded regular metadata'):
        native.execute({'action': 'workspace-info', 'repo': str(root)})


def test_workspace_info_caps_checkout_config_before_policy_parser(static_mac):
    native, root = static_mac
    (root / '.git/config').write_bytes(b'x' * (native.MAX_METADATA + 1))
    with pytest.raises(native.RequestError, match='bounded regular metadata'):
        native.execute({'action': 'workspace-info', 'repo': str(root)})


@pytest.mark.parametrize('action', ['stage-source', 'build-ios', 'build-macos', 'build-watch',
                                    'build-for-testing-ios', 'test-without-building-ios', 'run', 'shell'])
def test_remote_helper_rejects_workloads_without_child_execution(static_mac, action, monkeypatch):
    native, root = static_mac
    monkeypatch.setattr(subprocess, 'run', lambda *args, **kwargs:
                        pytest.fail('unsupported operation invoked an executable'))
    with pytest.raises(native.RequestError, match='unsupported'):
        native.execute({'action': action, 'repo': str(root)})


def test_native_transport_remains_exact_and_stop_is_terminal(isolate_apple_stop_state, monkeypatch):
    import apple_no_delete_guard as guard
    monkeypatch.setenv('CODEX_THREAD_ID', 'native-test')
    command = guard.native_command()
    guard.require_safe_operation('native-op')
    guard.require_safe_command(command)
    with pytest.raises(guard.UnsupportedRemoteOperation):
        guard.require_safe_command(command + ' extra')
    with pytest.raises(guard.MacDeletionStop):
        guard.require_safe_command('rm /tmp/outside')
    with pytest.raises(guard.MacDeletionStop):
        guard.require_safe_operation('native-op')
    with pytest.raises(guard.MacDeletionStop):
        guard.require_safe_command(command)


def test_wrapper_dispatches_only_exact_static_request(isolate_apple_stop_state, monkeypatch, tmp_path):
    from test_apple_remote_native_debugging import load_apple_remote
    remote = load_apple_remote()
    monkeypatch.setattr(remote, 'load_local_config', lambda: {})
    monkeypatch.setattr(remote, 'resolve_remote_config', lambda **kwargs:
                        remote.RemoteConfig('example', '/verified/OpenMates', 'test'))
    calls = []
    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, stdout=json.dumps({'status': 'passed'}), stderr='')
    monkeypatch.setattr(remote.subprocess, 'run', fake_run)
    request = tmp_path / 'request.json'
    output = tmp_path / 'output.json'
    request.write_text(json.dumps({'action': 'workspace-info'}))
    assert remote.main(['native-op', '--request', str(request), '--output', str(output)]) == 0
    assert len(calls) == 1
    argv, kwargs = calls[0]
    assert argv == remote.ssh_command(remote.RemoteConfig('example', '/verified/OpenMates', 'test'),
                                      remote.no_delete_guard.native_command())
    assert json.loads(kwargs['input']) == {'action': 'workspace-info', 'repo': '/verified/OpenMates'}
    assert output.read_text() == json.dumps({'status': 'passed'})


@pytest.mark.parametrize('payload,bundle', [
    ({'action': 'stage-source'}, None),
    ({'action': 'build-ios'}, None),
    ({'action': 'doctor', 'repo': '/tmp/untrusted'}, None),
    ({'action': 'doctor', 'command': 'rm /tmp/example'}, None),
    ({'action': ['doctor']}, None),
    ({'action': {'name': 'doctor'}}, None),
    ({'action': 'doctor'}, '/tmp/untrusted.tar.gz'),
])
def test_wrapper_rejects_unavailable_or_extra_fields_before_config(
        isolate_apple_stop_state, monkeypatch, tmp_path, payload, bundle):
    from test_apple_remote_native_debugging import load_apple_remote
    remote = load_apple_remote()
    monkeypatch.setattr(remote, 'load_local_config', lambda:
                        pytest.fail('rejected request loaded credentials/config'))
    request = tmp_path / 'request.json'
    request.write_text(json.dumps(payload))
    argv = ['native-op', '--request', str(request), '--output', str(tmp_path / 'response.json')]
    if bundle:
        argv += ['--bundle', bundle]
    with pytest.raises(remote.no_delete_guard.UnsupportedRemoteOperation):
        remote.main(argv)


def test_wrapper_caps_request_before_config(isolate_apple_stop_state, monkeypatch, tmp_path):
    from test_apple_remote_native_debugging import load_apple_remote
    remote = load_apple_remote()
    monkeypatch.setattr(remote, 'load_local_config', lambda:
                        pytest.fail('oversized request loaded config'))
    request = tmp_path / 'request.json'
    request.write_bytes(b'x' * 4097)
    assert remote.main(['native-op', '--request', str(request),
                        '--output', str(tmp_path / 'response.json')]) == 2
    request.unlink()
    request.write_text('{"action":"build-ios","action":"doctor"}')
    assert remote.main(['native-op', '--request', str(request),
                        '--output', str(tmp_path / 'response.json')]) == 2
    request.unlink()
    outside = tmp_path / 'outside.json'
    outside.write_text('{"action":"doctor"}')
    request.symlink_to(outside)
    assert remote.main(['native-op', '--request', str(request),
                        '--output', str(tmp_path / 'response.json')]) == 2
    request.unlink()
    import os
    os.mkfifo(request)
    assert remote.main(['native-op', '--request', str(request),
                        '--output', str(tmp_path / 'response.json')]) == 2
