#!/usr/bin/env python3
"""Supervise synthetic inference performed entirely by the native Rust binary.

Python only verifies/downloads public assets, compiles, applies resource bounds,
and scores recorded spans. It never executes model inference.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import struct
import subprocess
import sys
import time
import unicodedata

import redact_brotli_guard as brotli
from redact_linux_evaluation import ASSETS, prepare_assets, rss_bytes, verify_asset

ROOT = Path(__file__).resolve().parents[1]
RUSTC = Path('/home/superdev/.rustup/toolchains/1.98.1-aarch64-unknown-linux-gnu/bin/rustc')
WORK = Path('/tmp/openmates-redact-rust-678f')
HISTORY = ROOT / 'docs/architecture/privacy/evaluations/2026-10-26-redact'


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_fixtures():
    def join_synthetic(value):
        if set(value) == {'synthetic_parts'} and isinstance(value['synthetic_parts'], list):
            if not all(isinstance(part, str) for part in value['synthetic_parts']):
                raise ValueError('Invalid split synthetic fixture')
            return ''.join(value['synthetic_parts'])
        return value
    return json.loads((ROOT / 'scripts/fixtures/privacy-filter-synthetic.json').read_text(),
                      object_hook=join_synthetic)


def corpus(units, quality):
    rows = []
    if quality:
        for fixture in [*load_fixtures(), *context_fixtures()]:
            rows.append({'id': 'q:' + fixture['id'], 'text': fixture['text']})
    rows.append({'id': 'lat:address', 'text': 'Our customer Amina Okafor needs help. Her address is 42 Maple Avenue, Bristol BS1 4QA.'})
    words = ['The', 'ordinary', 'document', 'has', 'useful', 'context', 'for', 'review.']
    rows.extend({'id': f'lat:{count}', 'text': ' '.join(words[i % len(words)] for i in range(count))} for count in units)
    return rows


def context_fixtures():
    selected = {'name-support', 'name-emoji', 'name-german', 'address-us',
                'address-uk', 'address-de', 'email-plus', 'account-iban'}
    neutral = 'The ordinary document has useful context for review. '
    return [dict(row, id=f'window-{count}-{row["id"]}',
                 text=neutral * count + row['text'] + ' ' + neutral * 3)
            for row in load_fixtures() if row['id'] in selected
            for count in (2, 5, 11, 23)]


def encode_corpus(rows):
    data = bytearray(struct.pack('>I', len(rows)))
    for row in rows:
        for field in ('id', 'text'):
            value = row[field].encode('utf-8')
            if len(value) > 1024 * 1024:
                raise ValueError('Synthetic field exceeds bound')
            data.extend(struct.pack('>I', len(value)))
            data.extend(value)
    return bytes(data)


def utf16_length(text):
    return len(text.encode('utf-16-le')) // 2


def score_quality(cases):
    indexed = {row['id'][2:]: row for row in cases if row['id'].startswith('q:')}
    if not indexed:
        return None
    fixtures = load_fixtures()
    windows = context_fixtures() if any(key.startswith('window-') for key in indexed) else []
    if set(indexed) != {row['id'] for row in [*fixtures, *windows]}:
        raise ValueError('Incomplete quality receipt')
    result = score_set(fixtures, indexed)
    if windows:
        result['context_boundaries'] = score_set(windows, indexed)
    return result


def score_set(fixtures, indexed):
    expected = strict = content = negative = false_positive = 0
    for fixture in fixtures:
        spans = indexed[fixture['id']]['spans']
        covered = {i for span in spans for i in range(span['start'], span['end'])}
        for _category, value in fixture['expected']:
            start = utf16_length(fixture['text'][:fixture['text'].index(value)])
            positions = []
            cursor = start
            meaningful = []
            for character in value:
                points = list(range(cursor, cursor + utf16_length(character)))
                positions.extend(points)
                if unicodedata.category(character)[0] in 'LNM':
                    meaningful.extend(points)
                cursor += len(points)
            expected += 1
            strict += all(point in covered for point in positions)
            content += all(point in covered for point in meaningful)
        if not fixture['expected']:
            negative += 1
            false_positive += bool(spans)
    return {'expected_values': expected, 'fully_hidden': strict,
            'letters_digits_marks_hidden': content, 'negative_cases': negative,
            'false_positive_cases': false_positive}


def verify_native(directory, experiment=None):
    manifest = json.loads((HISTORY / 'manifest.json').read_text())
    files = manifest['static_host_native_files']
    if experiment:
        rebuilt = json.loads(experiment.read_text())
        audit = rebuilt.get('source_integrity_audit', {})
        if (rebuilt.get('sdk_commit') != manifest['sdk_source_revision']
                or audit.get('changed_tracked_files') != ['Sources/Redact/Model.swift']
                or audit.get('only_benchmark_chunking_patch') is not True
                or Path(rebuilt['native_path']).resolve().parent != directory.resolve()
                or digest(experiment.parent / 'benchmark-chunking.patch') != rebuilt['chunking_patch_sha256']):
            raise ValueError('Verified Linux-only benchmark build receipt required')
        files = rebuilt['native_files']
    result = []
    for item in files:
        path = directory / item['file']
        if path.stat().st_size != item['bytes'] or digest(path) != item['sha256']:
            raise ValueError('Published native package integrity mismatch')
        result.append(item)
    return result


def compile_binary():
    source = ROOT / 'scripts/redact_rust_evaluation.rs'
    WORK.mkdir(parents=True, exist_ok=True)
    binary = WORK / ('redact-rust-' + digest(source)[:16])
    if not binary.exists():
        subprocess.run([str(RUSTC), '--edition=2021', '-O', '-C', 'debuginfo=0',
                        str(source), '-o', str(binary)], check=True, timeout=120,
                       capture_output=True)
    return binary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native-directory', required=True, type=Path)
    parser.add_argument('--model-directory', required=True, type=Path)
    parser.add_argument('--brotli-prefix', required=True, type=Path)
    parser.add_argument('--experimental-build-receipt', type=Path)
    parser.add_argument('--max-chars', type=int, choices=[150, 300, 600])
    parser.add_argument('--carry', type=int, choices=[0, 1])
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--cores', type=int, choices=range(1, 9), default=2)
    parser.add_argument('--threads', choices=['default', *map(str, range(1, 9))], default='default')
    parser.add_argument('--units', type=int, nargs='+', choices=[32, 256, 1024, 4096], default=[32, 256, 4096])
    parser.add_argument('--quality', action='store_true')
    parser.add_argument('--repeats', type=int, choices=range(3, 8), default=3)
    parser.add_argument('--timeout-seconds', type=int, choices=range(30, 601), default=300)
    parser.add_argument('--download', action='store_true')
    parser.add_argument('--run', action='store_true')
    args = parser.parse_args()
    if not args.run:
        parser.error('Explicit --run required for this Rust evaluation')
    if args.output.exists() or args.output.with_suffix('.supervisor.json').exists():
        parser.error('Choose a fresh evidence path; preserve previous runs')
    if (args.max_chars is not None or args.carry is not None) and not args.experimental_build_receipt:
        parser.error('Chunk settings require the private experiment build receipt')
    native = verify_native(args.native_directory.resolve(), args.experimental_build_receipt)
    env = brotli.child_environment(args.brotli_prefix, dict(os.environ))
    if args.threads == 'default':
        env.pop('DAL_LITERT_THREADS', None)
    else:
        env['DAL_LITERT_THREADS'] = args.threads
    env.update({'OMP_NUM_THREADS': str(args.cores), 'OPENBLAS_NUM_THREADS': str(args.cores)})
    for name in ('DAL_REDACT_BENCH_MAX_CHARS', 'DAL_REDACT_BENCH_CARRY'):
        env.pop(name, None)
    if args.max_chars is not None:
        env['DAL_REDACT_BENCH_MAX_CHARS'] = str(args.max_chars)
    if args.carry is not None:
        env['DAL_REDACT_BENCH_CARRY'] = str(args.carry)
    # This is a library-loader-only child preflight: no model, input or licensing.
    probe = subprocess.run([sys.executable, str(ROOT / 'scripts/redact_brotli_guard.py'),
                            '--probe', '--prefix', str(args.brotli_prefix), '--native-core',
                            str(args.native_directory / 'libRedactNode.so')], env=env,
                           capture_output=True, text=True, check=True, timeout=30)
    decoder = json.loads(probe.stdout)
    if args.download:
        prepare_assets(args.model_directory)
    for name in ASSETS:
        verify_asset(name, (args.model_directory / name).read_bytes())
    binary = compile_binary()
    rows = corpus(args.units, args.quality)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    input_file = WORK / (args.output.stem + '.inputs.bin')
    input_file.write_bytes(encode_corpus(rows))
    cpus = sorted(os.sched_getaffinity(0))[:args.cores]
    if len(cpus) != args.cores:
        parser.error('Requested CPU budget unavailable')

    def bounds():
        os.nice(10)
        os.sched_setaffinity(0, cpus)

    started = time.monotonic()
    child = subprocess.Popen([str(binary), str(args.native_directory.resolve()),
                              str(args.model_directory.resolve()), str(input_file),
                              str(args.output.resolve()), str(args.repeats)],
                             env=env, cwd=ROOT, preexec_fn=bounds, start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    peak = 0
    stopped = None
    while child.poll() is None:
        peak = max(peak, rss_bytes(child.pid))
        if peak > 1536 * 1024**2:
            stopped = 'rss-limit'
        elif time.monotonic() - started > args.timeout_seconds:
            stopped = 'wall-time-limit'
        if stopped:
            os.killpg(child.pid, signal.SIGKILL)
            break
        time.sleep(0.1)
    code = child.wait()
    receipt = {'status': 'complete' if code == 0 and not stopped else 'failed',
               'inference_host': 'standalone Rust binary; no Node or Python model execution',
               'exit_code': code, 'stopped_by_supervisor': stopped,
               'wall_seconds': time.monotonic() - started, 'sampled_peak_rss_bytes': peak,
               'affinity_cpus': cpus, 'niceness_increment': 10,
               'dal_litert_threads': args.threads, 'timeout_seconds': args.timeout_seconds,
               'native_build': 'private Linux chunking experiment' if args.experimental_build_receipt else 'published SDK',
               'experimental_build_receipt_sha256': digest(args.experimental_build_receipt) if args.experimental_build_receipt else None,
               'chunking_max_chars': args.max_chars, 'chunking_carry': args.carry,
               'rustc': subprocess.check_output([str(RUSTC), '--version'], text=True).strip(),
               'binary_sha256': digest(binary), 'source_sha256': digest(ROOT / 'scripts/redact_rust_evaluation.rs'),
               'supervisor_sha256': digest(Path(__file__)), 'input_sha256': digest(input_file),
               'input_lengths': [{'id': row['id'], 'characters_utf16': utf16_length(row['text'])} for row in rows],
               'native_files': native, 'patched_decoder': decoder}
    if code == 0 and not stopped:
        result = json.loads(args.output.read_text())
        receipt['quality'] = score_quality(result['cases'])
    args.output.with_suffix('.supervisor.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({key: receipt[key] for key in ('status', 'exit_code', 'wall_seconds', 'sampled_peak_rss_bytes', 'dal_litert_threads')}))
    if code != 0 or stopped:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
