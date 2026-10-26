#!/usr/bin/env python3
"""Prepare a public-C-API resize probe; model operations require explicit --run.

The generated Rust host retains normal SDK licensing and network sealing. The
probe returns before synthetic input is read and never invokes model inference.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import shutil
import signal
import subprocess
import time

import redact_brotli_guard as brotli
from redact_linux_evaluation import ASSETS, rss_bytes, verify_asset

ROOT = Path(__file__).resolve().parents[1]
WORK = Path('/tmp/openmates-redact-rust-678f/dynamic-shape-probe')
SWIFT = Path('/tmp/openmates-redact-rust-678f/swift-experiment')
RUSTC = Path('/home/superdev/.rustup/toolchains/1.98.1-aarch64-unknown-linux-gnu/bin/rustc')
BROTLIPREFIX = Path('/tmp/openmates-redact-678f-brotli-1.1.1')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, data):
    temporary = path.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(data, indent=2) + '\n')
    temporary.replace(path)


def prepare():
    WORK.mkdir(mode=0o700, parents=True, exist_ok=True)
    host = ROOT / 'scripts/redact_rust_evaluation.rs'
    extension = ROOT / 'scripts/redact_dynamic_shape_probe.rs'
    before = host.read_text()
    anchor = '    stage_receipt(output, 6)?;\n'
    if before.count(anchor) != 1:
        raise ValueError('Unchanged host insertion anchor mismatch')
    insertion = '''    if dynamic_shape_probe(Path::new(&args[1]), Path::new(&args[2]), output, &meta)? {
        drop(model);
        return Ok(());
    }
'''
    generated = before.replace(anchor, anchor + insertion) + '\n' + extension.read_text()
    generated_sha256 = hashlib.sha256(generated.encode()).hexdigest()
    # Each source/supervisor version owns immutable preparation evidence and
    # fresh run directories. Never replace the original WORK/preparation.json.
    preparation_root = WORK / 'preparations' / generated_sha256 / digest(Path(__file__))
    preparation_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    preparation_path = preparation_root / 'preparation.json'
    source = preparation_root / 'licensed-shape-probe.rs'
    if source.exists() and source.read_text() != generated:
        raise ValueError('Generated source identity mismatch')
    if not source.exists():
        with source.open('x') as handle:
            handle.write(generated)
    binary = source.with_suffix('')

    def compile_bounds():
        os.nice(10)
        os.sched_setaffinity(0, {12, 13})

    command = [str(RUSTC), '--edition=2021', '-O', '-C', 'debuginfo=0', str(source), '-o', str(binary)]
    if not binary.exists():
        compiled = subprocess.run(command, capture_output=True, text=True, timeout=120, preexec_fn=compile_bounds)
        (preparation_root / 'compile.log').write_text(compiled.stdout + compiled.stderr)
        compiled.check_returncode()
    if digest(host) != hashlib.sha256(before.encode()).hexdigest():
        raise ValueError('Original host changed during preparation')
    headers = SWIFT / 'source/desert-ant-core-86b9b55fe8c61ec1c27c5b6383f545c6df1d6ceb/Sources/CLiteRt/include'
    abi_source = '''#include <stddef.h>
#include "litert/c/litert_compiled_model.h"
_Static_assert(sizeof(LiteRtLayout)==68, "layout size");
_Static_assert(offsetof(LiteRtLayout, dimensions)==4, "dimensions offset");
_Static_assert(offsetof(LiteRtLayout, strides)==36, "strides offset");
_Static_assert(sizeof(LiteRtParamIndex)==sizeof(size_t), "parameter index");
_Static_assert(sizeof(bool)==1, "C bool");
'''
    abi_command = ['cc', '-x', 'c', '-fsyntax-only', '-I', str(headers), '-']
    abi = subprocess.run(abi_command, input=abi_source, capture_output=True, text=True, timeout=30,
                         preexec_fn=compile_bounds)
    (preparation_root / 'public-header-abi-check.log').write_text(abi.stdout + abi.stderr)
    abi.check_returncode()
    record = {'status': 'prepared-no-model-operations', 'original_host_sha256': digest(host),
              'probe_extension_sha256': digest(extension), 'generated_source': str(source),
              'generated_source_sha256': digest(source), 'binary': str(binary),
              'binary_sha256': digest(binary), 'compile_command': command,
              'rustc': subprocess.check_output([str(RUSTC), '--version'], text=True).strip(),
              'supervisor_sha256': digest(Path(__file__)), 'inference_executed': False,
              'public_header_abi_check': {'passed': True, 'command': abi_command,
                                        'source': abi_source,
                                        'headers': {name: digest(headers / 'litert/c' / name)
                                                    for name in ('litert_layout.h', 'litert_compiled_model.h', 'litert_common.h')}},
              'official_documentation': 'https://developers.google.com/edge/api/litert/c/classlitert/1-1-compiled-model',
              'runtime_exports': {}}
    required = ['LiteRtCompiledModelResizeInputTensorNonStrict', 'LiteRtGetCompiledModelOutputTensorLayouts',
                'LiteRtGetCompiledModelInputTensorLayout', 'LiteRtGetCompiledModelInputBufferRequirements',
                'LiteRtGetCompiledModelOutputBufferRequirements', 'LiteRtGetTensorBufferRequirementsBufferSize']
    for runtime in ('2.2', '2.3.1'):
        folder = WORK / ('runtime-' + runtime)
        native = folder / 'native'
        native.mkdir(parents=True, exist_ok=True)
        original = SWIFT / ('native' if runtime == '2.2' else 'runtime231/native')
        files = []
        for name in ('libRedactNode.so', 'libLiteRt.so'):
            target = native / name
            if target.exists() and digest(target) != digest(original / name):
                raise ValueError('Existing copied native changed')
            if not target.exists():
                shutil.copy2(original / name, target)
            files.append({'file': name, 'sha256': digest(target), 'bytes': target.stat().st_size})
        symbols = subprocess.check_output(['nm', '-D', '--defined-only', str(native / 'libLiteRt.so')], text=True)
        exports = {line.split()[-1].split('@')[0] for line in symbols.splitlines() if line.split()}
        record['runtime_exports'][runtime] = {'native_directory': str(native), 'native_files': files,
                                             'required': {name: name in exports for name in required}}
        if not all(name in exports for name in required):
            raise ValueError('Required public resize API missing; stop before model load')
    encoded = json.dumps(record, indent=2) + '\n'
    if preparation_path.exists():
        if preparation_path.read_text() != encoded:
            raise ValueError('Immutable preparation differs; preserve previous evidence')
    else:
        with preparation_path.open('x') as handle:
            handle.write(encoded)
    return binary, record, preparation_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    execution = parser.add_mutually_exclusive_group()
    execution.add_argument('--run', action='store_true', help='Explicitly run the prepared licensed allocation probe')
    execution.add_argument('--no-run', dest='run', action='store_false', help='Prepare and compile only; preserve all executed evidence')
    parser.set_defaults(run=False)
    parser.add_argument('--runtime', choices=('2.2', '2.3.1'), default='2.2')
    parser.add_argument('--model-directory', type=Path)
    parser.add_argument('--cpus', default='10,11')
    args = parser.parse_args()
    binary, preparation, preparation_path = prepare()
    if not args.run:
        print(json.dumps({'status': preparation['status'], 'receipt': str(preparation_path),
                          'binary': str(binary), 'binary_sha256': preparation['binary_sha256']}))
        return
    if args.model_directory is None:
        parser.error('--run requires --model-directory')
    cpus = {int(value) for value in args.cpus.split(',')}
    if len(cpus) != 2 or not cpus <= os.sched_getaffinity(0):
        parser.error('Exactly two available CPU IDs required')
    model_files = []
    for name in ASSETS:
        path = args.model_directory / name
        verify_asset(name, path.read_bytes())
        model_files.append({'file': name, 'sha256': digest(path), 'bytes': path.stat().st_size})
    folder = preparation_path.parent / 'runs' / ('runtime-' + args.runtime)
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    output = folder / 'allocation-result.json'
    if output.exists():
        parser.error('Fresh allocation result required; preserve previous evidence')
    environment = brotli.child_environment(BROTLIPREFIX, dict(os.environ))
    for key in ('DAL_REDACT_BENCH_WORKERS', 'DAL_REDACT_BENCH_FAST_GAPS', 'DAL_REDACT_BENCH_MAX_CHARS', 'DAL_REDACT_BENCH_CARRY'):
        environment.pop(key, None)
    environment['DAL_LITERT_THREADS'] = '2'
    native = preparation['runtime_exports'][args.runtime]['native_directory']
    command = [str(binary), native, str(args.model_directory.resolve()),
               str(folder / 'input-must-never-be-read.bin'), str(output), '1']

    def bounds():
        os.nice(10)
        os.sched_setaffinity(0, cpus)
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        resource.setrlimit(resource.RLIMIT_CPU, (30, 30))

    start = time.monotonic()
    peak = 0
    stopped = None
    with (folder / 'native-stderr.log').open('xb') as errors:
        child = subprocess.Popen(command, env=environment, stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=errors,
                                 preexec_fn=bounds, start_new_session=True)
        try:
            while child.poll() is None:
                peak = max(peak, rss_bytes(child.pid))
                if peak > 1536 * 1024**2:
                    stopped = '1536MiB-RSS-limit'
                elif time.monotonic() - start > 30:
                    stopped = '30-second-wall-limit'
                if stopped:
                    os.killpg(child.pid, signal.SIGKILL)
                    break
                time.sleep(0.05)
            code = child.wait(timeout=10)
        finally:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait(timeout=10)
    result = {'exit_code': code, 'stopped': stopped, 'seconds': time.monotonic() - start,
              'peak_rss_bytes': peak, 'cpus': sorted(cpus), 'threads': 2,
              'runtime': args.runtime, 'command': command, 'model_files': model_files,
              'preparation_path': str(preparation_path), 'preparation_sha256': digest(preparation_path),
              'result_sha256': digest(output) if output.exists() else None,
              'native_stderr_sha256': digest(folder / 'native-stderr.log'), 'inference_executed': False}
    write_json(folder / 'supervisor-result.json', result)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
