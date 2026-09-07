"""Exercise remote patch safety against real temporary Git checkouts.

The fixed helper runs locally here; no Mac, user repository or network is used.
Tests cover dry runs, stale files, unlisted paths, private paths and media.
The transport test verifies pre-dispatch rejection of the Python helper.
"""
# contract-test-file: tooling
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from _apple_remote_patch import execute, PatchError  # noqa: E402
from test_apple_remote_native_debugging import load_apple_remote  # noqa: E402


@pytest.fixture
def repo(tmp_path):
    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True)
    (tmp_path / 'src').mkdir()
    (tmp_path / 'src/Root.tsx').write_text('const value = 1;\n')
    (tmp_path / 'footage.mp4').write_bytes(b'private original footage')
    return tmp_path


def request(repo):
    snapshot = execute({'action': 'snapshot', 'repo': str(repo), 'files': ['src/Root.tsx']})
    return {'action': 'apply', 'repo': str(repo), 'expected': snapshot['files'],
            'patch': '--- a/src/Root.tsx\n+++ b/src/Root.tsx\n@@ -1 +1 @@\n-const value = 1;\n+const value = 2;\n'}


def test_dry_run_then_apply_preserves_unrelated_files_and_index(repo):
    r = request(repo)
    assert execute(r)['status'] == 'checked'
    assert (repo / 'src/Root.tsx').read_text() == 'const value = 1;\n'
    r['apply'] = True
    assert execute(r)['status'] == 'applied'
    assert (repo / 'src/Root.tsx').read_text() == 'const value = 2;\n'
    assert (repo / 'footage.mp4').read_bytes() == b'private original footage'
    assert subprocess.check_output(['git', '-C', str(repo), 'diff', '--cached']) == b''


def test_stale_preimage_rejected_even_when_context_would_apply(repo):
    r = request(repo)
    (repo / 'src/Root.tsx').write_text('const value = 1;\n// unrelated new user edit\n')
    r['apply'] = True
    with pytest.raises(PatchError, match='Source changed'):
        execute(r)
    assert 'user edit' in (repo / 'src/Root.tsx').read_text()


@pytest.mark.parametrize('name', ['../outside.ts', '/tmp/outside.ts', '.git/config', '.env', '.ssh/key.txt', 'footage.mp4', 'src/../Root.tsx'])
def test_unsafe_paths_rejected(repo, name):
    with pytest.raises(PatchError):
        execute({'action': 'snapshot', 'repo': str(repo), 'files': [name]})


def test_symlink_parent_rejected(repo, tmp_path_factory):
    outside = tmp_path_factory.mktemp('outside')
    (outside / 'private.ts').write_text('secret')
    (repo / 'link').symlink_to(outside, target_is_directory=True)
    with pytest.raises(PatchError, match='Symlink'):
        execute({'action': 'snapshot', 'repo': str(repo), 'files': ['link/private.ts']})


def test_unlisted_patch_path_rejected_before_writing(repo):
    r = request(repo)
    r['patch'] = r['patch'].replace('Root.tsx', 'Other.tsx')
    with pytest.raises(PatchError, match='exactly match'):
        execute(r)


def test_new_gitignore_supported_without_touching_media(repo):
    r = {'action': 'apply', 'repo': str(repo), 'expected': {'.gitignore': None},
         'patch': '--- /dev/null\n+++ b/.gitignore\n@@ -0,0 +1 @@\n+input-media/\n', 'apply': True}
    assert execute(r)['status'] == 'applied'
    assert (repo / '.gitignore').read_text() == 'input-media/\n'


def test_delete_and_binary_changes_rejected(repo):
    r = request(repo)
    r['patch'] = '--- a/src/Root.tsx\n+++ /dev/null\n@@ -1 +0,0 @@\n-const value = 1;\n'
    with pytest.raises(PatchError, match='Deleting'):
        execute(r)
    r['patch'] = 'GIT binary patch\nliteral 0\n'
    with pytest.raises(PatchError, match='Binary'):
        execute(r)


def test_transport_rejects_python_helper_before_dispatch(monkeypatch, tmp_path):
    remote = load_apple_remote()
    patch = tmp_path / 'review.patch'
    patch.write_text('reviewed diff')
    hashes = tmp_path / 'hashes.json'
    hashes.write_text(json.dumps({'files': {'src/Root.tsx': 'a'*64}}))
    args = remote.build_parser().parse_args(['apply-patch', '--repo', '/repo with spaces', '--patch', str(patch), '--expected', str(hashes)])
    captured = {}
    def run(command, **kwargs):
        captured.update(command=command, **kwargs)
        return subprocess.CompletedProcess(command, 0, '{"status":"checked"}', '')
    monkeypatch.setattr(remote.subprocess, 'run', run)
    with pytest.raises(remote.no_delete_guard.MacDeletionStop):
        remote.reviewed_remote_patch(remote.RemoteConfig('private-host', '/repo with spaces', 'configured'), args)
    assert captured == {}
    assert remote.no_delete_guard.active_stop() is not None
