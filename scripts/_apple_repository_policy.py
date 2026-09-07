"""Repository-scoped Mac filesystem policy for TASK-752.

The user replaced blanket no-delete with two verified checkout boundaries.
Profiles constrain native descendants; Python checks defend typed interfaces.
Original media and checkout roots remain protected from deletion/overwrite.
The named legacy stop is superseded by policy change, never human-delete proof.
See docs/architecture/apple-no-delete-safety.md for authority and limitations.
"""
from __future__ import annotations
import configparser
import json
import os
from pathlib import Path
import stat

POLICY_VERSION = 'mac-repository-scope-v2-2026-09-07'
AUTHORITY = {
    'source': 'explicit user policy-change instruction relayed from codex://threads/01a07d05-4f27-7111-91fb-9ef6fa875c9b',
    'decision': 'Allow deletion only within verified OpenMates and openmates-marketing checkouts; protect originals and checkout roots.',
    'manual_deletion_performed': False,
}
SUPERSEDED_STOP = 'e30e581ca54143adb3705cf158dd7444'
SUPERSEDED_TASK = 'codex:01a07d2c-3fd1-7152-b623-52782c73de4c'
ORIGINS = {'OpenMates': 'https://github.com/glowingkitty/OpenMates.git',
           'openmates-marketing': 'https://github.com/glowingkitty/openmates-marketing.git'}


class ScopeError(ValueError):
    pass


def canonical_directory(path):
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts:
        raise ScopeError('absolute traversal-free directory required')
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ScopeError('symlink checkout/ancestor refused')
    if not path.is_dir():
        raise ScopeError('checkout directory unavailable')
    return path.resolve(strict=True)


def verify_checkout(path, name):
    path = canonical_directory(path)
    git = path / '.git'
    canonical_directory(git)
    config = git / 'config'
    if config.is_symlink() or not config.is_file():
        raise ScopeError('ordinary checkout Git config required')
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(config)
    origin = parser.get('remote "origin"', 'url', fallback='')
    accepted = {ORIGINS[name], ORIGINS[name].removesuffix('.git'),
                ORIGINS[name].replace('https://github.com/', 'git@github.com:')}
    if origin not in accepted:
        raise ScopeError('checkout origin does not match the authorized GitHub repository')
    if parser.getboolean('core', 'bare', fallback=False):
        raise ScopeError('bare repository is not an authorized checkout')
    return path


def workspace(project):
    project = canonical_directory(project)
    marketing = verify_checkout(project.parent.parent, 'openmates-marketing')
    if project != marketing / 'videos/remotion' or marketing.name != 'openmates-marketing':
        raise ScopeError('unexpected marketing project location')
    app = marketing.parent / 'OpenMates'
    roots = [marketing]
    if app.exists() or app.is_symlink():
        roots.append(verify_checkout(app, 'OpenMates'))
    protected = [project / 'input-media', project / 'renders/mac-local/announcement-video/originals']
    return {'roots': roots, 'marketing': marketing, 'app': app, 'protected': protected}


def require_descendant(path, roots, protected=()):
    raw = Path(path)
    if not raw.is_absolute() or '..' in raw.parts:
        raise ScopeError('absolute path without traversal required')
    resolved = raw.resolve(strict=False)
    if not any(resolved != root and resolved.is_relative_to(root) for root in roots):
        raise ScopeError('operation would affect a checkout root or escape verified roots')
    if any(resolved == p or resolved.is_relative_to(p) for p in protected):
        raise ScopeError('original media is protected')
    return resolved


def profile(roots, protected=()):
    # Seatbelt evaluates resolved filesystem objects, not caller string prefixes.
    # The checkout directory itself is explicitly denied even though subpath
    # also matches it. Protected originals deny writes as well as unlinks.
    roots = [canonical_directory(p) for p in roots]
    scopes = ' '.join('(subpath ' + json.dumps(str(p)) + ')' for p in roots)
    exact = ' '.join('(literal ' + json.dumps(str(p)) + ')' for p in roots)
    rules = ['(version 1)(allow default)',
             '(deny file-write-unlink (with send-signal SIGKILL) (require-not (require-any ' + scopes + ')))',
             '(deny file-write-unlink (with send-signal SIGKILL) (require-any ' + exact + '))']
    for p in protected:
        rules.append('(deny file-write* (with send-signal SIGKILL) (subpath ' + json.dumps(str(p.resolve(strict=False))) + '))')
    return ''.join(rules)


def exclusive_directory(path):
    path = Path(path)
    parent = canonical_directory(path.parent)
    fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.mkdir(path.name, 0o700, dir_fd=fd)
    finally:
        os.close(fd)
    return canonical_directory(path)


def identity(path):
    info = Path(path).stat()
    if not stat.S_ISDIR(info.st_mode):
        raise ScopeError('expected directory')
    return {'path': str(path), 'device': info.st_dev, 'inode': info.st_ino}
