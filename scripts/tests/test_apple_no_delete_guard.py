"""Local regression proof for the Mac no-delete transport boundary.

No test connects to a Mac or deletes a remote fixture. Injected runners record
whether dispatch occurred; temporary local state proves interruption persistence.
Human provenance is intentionally unavailable: role=user, CLI flags, matching
text and coordinator messages must never release the stop.
"""
# contract-test-file: tooling

import importlib
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_apple_remote_native_debugging import load_apple_remote


@pytest.fixture
def guard(tmp_path, monkeypatch):
    module = importlib.import_module('apple_no_delete_guard')
    monkeypatch.setattr(module, 'STATE_PATH', tmp_path / 'stops.sqlite3')
    monkeypatch.setenv('CODEX_THREAD_ID', 'test-thread')
    monkeypatch.setenv('CODEX_SESSION_ID', 'test-thread')
    monkeypatch.delenv('OPENCODE_SESSION_ID', raising=False)
    return module


@pytest.mark.parametrize('command', [
    'rm -f /tmp/example', 'rmdir /tmp/example', 'find /tmp -delete',
    "python3 -c 'import os; os.unlink(\"/tmp/example\")'",
    "python3 -c 'import shutil; shutil.rmtree(\"/tmp/example\")'",
    "python3 -c 'exec(bytes.fromhex(\"70617373\"))'",
    'bash -lc true', 'sh -c "$COMMAND"', 'env python3 helper.py',
    'rsync --delete src/ dest/', 'rsync src/ dest/', 'git reset --hard',
    'git clean -fd', 'git checkout dev', 'git pull', 'git gc',
    'mv a b', 'cp a b', 'install a b', 'truncate -s 0 a',
    'npm ci', 'npm uninstall example', 'brew cleanup', 'pip uninstall example',
    'xcrun simctl uninstall booted example', 'xcodebuild build',
    'node browser-profile-teardown.js', 'osascript -e "tell app \\\"Finder\\\" to delete every file"',
    'true; rm a', 'true\nrm a', '$(rm a)', '/usr/bin/uname -s; true',
])
def test_unsafe_remote_command_never_dispatches(guard, command):
    remote = load_apple_remote()
    calls = []
    with pytest.raises((guard.MacDeletionStop, guard.UnsupportedRemoteOperation)):
        remote.run_remote(remote.RemoteConfig('example', '/repo', 'test'), command,
                          runner=lambda argv: calls.append(argv), allow_destructive=True)
    assert calls == []
    assert bool(guard.active_stop()) == guard.explicit_deletion(command)


def test_restart_and_alternate_safe_dispatch_stay_blocked(guard):
    remote = load_apple_remote()
    config = remote.RemoteConfig('example', '/repo', 'test')
    with pytest.raises(guard.MacDeletionStop):
        remote.ssh_command(config, 'rm example')
    record = guard.active_stop()
    # A new guard object/process reads the same durable record.
    assert guard.StopStore(guard.STATE_PATH).active(guard.task_identity()) == record
    for alternate in (lambda: remote.ssh_command(config, 'true'),
                      lambda: remote.scp_command(config, '/tmp/a', Path('/tmp/a')),
                      lambda: remote.scp_upload_command(config, Path('/tmp/a'), '/tmp/a')):
        with pytest.raises(guard.MacDeletionStop):
            alternate()
    assert guard.active_stop() == record


@pytest.mark.parametrize('confirmation', [
    {}, {'confirmed': True}, {'role': 'user', 'text': 'I ran the deletion myself'},
    {'role': 'user', 'text': 'I did not want the deletion'},
    {'role': 'user', 'source': 'turn/start', 'text': 'I ran it myself'},
    {'role': 'user', 'source': 'human_keyboard', 'text': 'I ran it myself'},
    {'source': 'coordinator'}, {'source': 'automatic_resume'}, {'timeout': True},
])
def test_untrusted_confirmation_cannot_resume(guard, confirmation, monkeypatch, capsys):
    with pytest.raises(guard.MacDeletionStop):
        guard.require_safe_command('rm example')
    before = guard.active_stop()
    import io
    import json
    monkeypatch.setattr(sys, 'argv', ['apple_no_delete_guard.py', 'hook'])
    monkeypatch.setattr(sys, 'stdin', io.StringIO(json.dumps(confirmation)))
    assert guard.main() == guard.STOP_EXIT_CODE
    assert json.loads(capsys.readouterr().out)['continue'] is False
    assert guard.active_stop() == before


@pytest.mark.parametrize('command', ['true', '/usr/bin/true', '/usr/bin/uname -s', '/bin/df -h'])
def test_fixed_diagnostics_dispatch_without_stop(guard, command):
    remote = load_apple_remote()
    calls = []
    def runner(argv):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, 'ok', '')
    assert remote.run_remote(remote.RemoteConfig('example', '/repo', 'test'), command, runner=runner) == 0
    assert len(calls) == 1
    assert guard.active_stop() is None


def test_preflight_blocks_helper_before_config_credentials_or_dispatch(guard, monkeypatch):
    remote = load_apple_remote()
    calls = []
    monkeypatch.setattr(remote, 'load_local_config', lambda: calls.append('config'))
    with pytest.raises((guard.MacDeletionStop, guard.UnsupportedRemoteOperation)):
        remote.main(['test-ios'])
    assert calls == []


def test_missing_identity_and_corrupt_state_fail_closed(guard, monkeypatch):
    monkeypatch.delenv('CODEX_THREAD_ID')
    monkeypatch.delenv('CODEX_SESSION_ID')
    with pytest.raises(guard.MacDeletionStop):
        guard.require_safe_command('true')
    monkeypatch.setenv('CODEX_THREAD_ID', 'test-thread')
    guard.STATE_PATH.write_bytes(b'corrupt state')
    with pytest.raises(guard.MacDeletionStop):
        guard.require_safe_command('true')


@pytest.mark.parametrize('event', ['PreToolUse', 'PostToolUse', 'Stop', 'SessionStart'])
def test_hook_stops_even_for_read_tools_and_automatic_resume(guard, monkeypatch, capsys, event):
    import io
    import json
    with pytest.raises(guard.MacDeletionStop):
        guard.require_safe_command('rm example')
    before = guard.active_stop()
    monkeypatch.setattr(sys, 'argv', ['apple_no_delete_guard.py', 'hook'])
    monkeypatch.setattr(sys, 'stdin', io.StringIO(json.dumps({
        'hook_event_name': event, 'tool_name': 'read', 'role': 'user',
        'text': 'I did not want deletion', 'confirmed': True,
    })))
    assert guard.main() == guard.STOP_EXIT_CODE
    result = json.loads(capsys.readouterr().out)
    assert result['continue'] is False
    assert 'Do not try another command' in result['stopReason']
    assert guard.active_stop() == before


def test_new_process_and_second_attempt_preserve_original_stop(guard):
    import json
    with pytest.raises(guard.MacDeletionStop):
        guard.require_safe_command('rm first-example')
    record = guard.active_stop()
    # Inject only a temporary LOCAL test database, without a production env bypass.
    code = ('import sys; from pathlib import Path; '
            'sys.path.insert(0, sys.argv[1]); import apple_no_delete_guard as g; '
            'g.STATE_PATH=Path(sys.argv[2]); '
            'g.require_safe_command("rm second-example")')
    result = subprocess.run([sys.executable, '-c', code, str(Path(__file__).resolve().parents[1]),
                             str(guard.STATE_PATH)], capture_output=True, text=True)
    assert result.returncode == guard.STOP_EXIT_CODE
    assert guard.active_stop() == record
    assert record['requested_command'] == 'rm first-example'
    assert json.loads(json.dumps(record)) == record


@pytest.mark.parametrize('bad_record', ['[]', '{}', 'null', 'false', '"confirmed"'])
def test_malformed_record_cannot_implicitly_clear_gate(guard, bad_record):
    with guard.StopStore(guard.STATE_PATH).connect() as connection:
        connection.execute('INSERT INTO stops VALUES (?, ?)', (guard.task_identity(), bad_record))
    with pytest.raises(guard.MacDeletionStop):
        guard.require_safe_command('true')


def test_destructive_cli_flag_cannot_reach_config_or_transport(guard, monkeypatch):
    remote = load_apple_remote()
    monkeypatch.setattr(remote, 'load_local_config', lambda: pytest.fail('must stop before config'))
    with pytest.raises(guard.MacDeletionStop):
        remote.main(['--allow-destructive', 'run', '--', 'rm', 'example'])


def test_all_registered_helpers_have_explicit_fail_closed_classification(guard):
    import argparse
    remote = load_apple_remote()
    action = next(a for a in remote.build_parser()._actions if isinstance(a, argparse._SubParsersAction))
    for name in action.choices:
        if name in {'status', 'run', 'finalize-proof', 'remotion-op'}:
            continue
        # Each independently selected helper is rejected, including future ones.
        with pytest.raises((guard.MacDeletionStop, guard.UnsupportedRemoteOperation)):
            guard.require_safe_operation(name)


@pytest.mark.parametrize('argv', [
    ['ssh', 'example', 'rm example'],
    ['ssh', '-o', 'ProxyCommand=rm example', 'example', 'true'],
    ['scp', 'example', 'host:example'], ['rsync', 'a/', 'host:a/'],
])
def test_direct_default_runner_transport_cannot_bypass_policy(guard, monkeypatch, argv):
    remote = load_apple_remote()
    monkeypatch.setattr(remote.subprocess, 'run', lambda *a, **kw: pytest.fail('must not dispatch'))
    with pytest.raises((guard.MacDeletionStop, guard.UnsupportedRemoteOperation)):
        remote.default_runner(argv)


def test_ssh_target_cannot_inject_proxy_command(guard):
    remote = load_apple_remote()
    with pytest.raises((guard.MacDeletionStop, guard.UnsupportedRemoteOperation)):
        remote.ssh_command(remote.RemoteConfig('-oProxyCommand=example', '/repo', 'test'), 'true')
