#!/usr/bin/env python3
"""Build-time only, digest-pinned Whistle assets; never runs a downloaded engine.

First prepare a verified cache with --fetch. Normal builds stay offline. Paths
are explicit so the root owner can keep evaluation products inside its workspace.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parent
SUPPORTED = {'iphoneos': 'ios-arm64', 'iphonesimulator': 'ios-sim-arm64', 'watchos': 'watchos-arm64'}


def pinned_files():
    lock = json.loads((ROOT / 'whistle-assets.lock.json').read_text())
    for entry in lock['files']:
        parts = Path(entry['path']).parts
        if not parts or any(p in ('..', '.') for p in parts) or Path(entry['path']).is_absolute():
            raise ValueError('unsafe_asset_path')
        if entry['repository'] not in ('Cactus-Compute/whistle', 'Cactus-Compute/needle3'):
            raise ValueError('unsupported_repository')
        if len(entry['revision']) != 40 or any(c not in '0123456789abcdef' for c in entry['revision']):
            raise ValueError('unpinned_revision')
        if len(entry['sha256']) != 64 or any(c not in '0123456789abcdef' for c in entry['sha256']):
            raise ValueError('invalid_digest')
    return lock


def digest(path):
    sha = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            sha.update(block)
    return sha.hexdigest()


def verify(path, entry):
    if path.is_symlink() or not path.is_file() or path.stat().st_size != entry['sizeBytes'] or digest(path) != entry['sha256']:
        raise ValueError('asset_verification_failed:' + entry['path'])


def obtain(cache, entry, fetch=False):
    repo = entry['repository'].split('/')[1]
    target = cache / repo / entry['revision'] / entry['path']
    if target.exists():
        verify(target, entry)
        return target
    if not fetch:
        raise ValueError('offline_asset_missing:' + entry['path'])
    target.parent.mkdir(parents=True, exist_ok=True)
    url = f"https://huggingface.co/{entry['repository']}/resolve/{entry['revision']}/{entry['path']}"
    # Only immutable official files are requested; no Python package, runner or LLM weights.
    with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as tmp:
        temporary = Path(tmp.name)
    try:
        with urllib.request.urlopen(url, timeout=120) as response, temporary.open('wb') as out:
            total = 0
            while block := response.read(1024 * 1024):
                total += len(block)
                if total > entry['sizeBytes']:
                    raise ValueError('asset_larger_than_pin')
                out.write(block)
        verify(temporary, entry)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def prepare(cache, output, platform, *, fetch=False, model_only=False):
    lock = pinned_files()
    if platform not in SUPPORTED and not (platform == 'watchsimulator' and model_only):
        raise ValueError('unsupported_runtime_platform:' + platform)
    folder = SUPPORTED.get(platform)
    selected = [e for e in lock['files'] if e['repository'].endswith('/whistle') or
                (not model_only and (e['path'] == 'LICENSE' or e['path'] in (folder + '/libneedle.a', 'ios-arm64/needle.h')))]
    if output.exists() and any(output.iterdir()):
        raise ValueError('output_must_be_empty_use_fresh_staging_directory')
    # Verify every input before creating bundle products.
    sources = [(e, obtain(cache, e, fetch)) for e in selected]
    output.mkdir(parents=True, exist_ok=True)
    records = []
    for entry, source in sources:
        if entry['repository'].endswith('/whistle'):
            relative = 'bundle/Whistle/' + ('MODEL-LICENSE.txt' if entry['path'] == 'LICENSE' else entry['path'])
        elif entry['path'] == 'LICENSE':
            relative = 'bundle/Whistle/RUNTIME-LICENSE.txt'
        else:
            relative = 'link/' + Path(entry['path']).name
        destination = output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        verify(destination, entry)
        records.append({'path': relative, 'sizeBytes': entry['sizeBytes'], 'sha256': entry['sha256']})
    receipt = {'schemaVersion': 1, 'platform': platform, 'runtimeFolder': None if model_only else folder,
               'minimumOS': None if model_only else lock['runtime']['platforms'][folder]['minimumOS'],
               'modelBytes': lock['model']['sizeBytes'],
               'bundleBytes': sum(x['sizeBytes'] for x in records if x['path'].startswith('bundle/')),
               'documentsBytes': 0, 'containsNeedleLLMWeights': False,
               'nativeActivationAllowed': not model_only, 'modelResidency': 'process_lifetime',
               'reclaimsModelOnSessionEnd': False, 'runtimeScratchErasureVerified': False,
               'files': records}
    (output / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--platform', required=True)
    parser.add_argument('--fetch', action='store_true', help='Explicit build/preparation-time download; never first use.')
    parser.add_argument('--model-only', action='store_true', help='Bundle resource without a runnable native slice.')
    args = parser.parse_args()
    receipt = prepare(args.cache, args.output, args.platform, fetch=args.fetch, model_only=args.model_only)
    print(json.dumps({'platform': receipt['platform'], 'bundleBytes': receipt['bundleBytes'],
                      'nativeActivationAllowed': receipt['nativeActivationAllowed']}))


if __name__ == '__main__':
    main()
