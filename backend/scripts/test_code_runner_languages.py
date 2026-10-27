#!/usr/bin/env python3
# contract-test-file: tooling
"""Verify all accepted common-language targets in fresh disposable E2B VMs.

Run inside the API image after bounded provider-cost consent. All sources are
synthetic smoke programs, with no account data, network calls or artifacts.
The actual restricted provider supplies isolation, cancellation and teardown.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import inspect
import json
import os
import time
from pathlib import Path

from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.shared.providers.e2b_code_runner import (
    CODE_RUN_TEMPLATE_ENV, CodeRunFile, get_e2b_api_key_async, run_code_in_e2b,
)


SAMPLES = [
    ('python', 'main.py', 'print("openmates-code-run-ok")\n'),
    ('javascript', 'main.js', 'console.log("openmates-code-run-ok");\n'),
    ('typescript', 'main.ts', 'const message: string = "openmates-code-run-ok"; console.log(message);\n'),
    ('bash', 'main.sh', 'printf "openmates-code-run-ok\\n"\n'),
    ('c', 'main.c', '#include <stdio.h>\nint main(void) { puts("openmates-code-run-ok"); return 0; }\n'),
    ('cpp', 'main.cpp', '#include <iostream>\nint main() { std::cout << "openmates-code-run-ok" << std::endl; }\n'),
    ('rust', 'main.rs', 'fn main() { println!("openmates-code-run-ok"); }\n'),
    ('go', 'main.go', 'package main\nimport "fmt"\nfunc main() { fmt.Println("openmates-code-run-ok") }\n'),
]


async def _api_key() -> str:
    manager = SecretsManager()
    await manager.initialize()
    try:
        return await get_e2b_api_key_async(manager)
    finally:
        await manager.aclose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--template', required=True)
    parser.add_argument('--receipt', type=Path, required=True)
    args = parser.parse_args()
    if not args.execute:
        parser.error('--execute and prior provider-cost consent are required')
    os.environ[CODE_RUN_TEMPLATE_ENV] = args.template
    receipt = {'template_id': args.template, 'provider_sha256': hashlib.sha256(
        Path(inspect.getfile(run_code_in_e2b)).read_bytes()).hexdigest(), 'cases': []}
    key = asyncio.run(_api_key())
    try:
        for language, filename, source in SAMPLES:
            output = []
            started = time.monotonic()
            result = run_code_in_e2b(
                [CodeRunFile(path=filename, language=language, content=source, is_target=True)],
                filename, lambda kind, text: output.append((kind, text)), key,
                enable_internet=False,
            )
            stdout = ''.join(text for kind, text in output if kind == 'stdout')
            passed = result.exit_code == 0 and stdout.strip() == 'openmates-code-run-ok'
            case = {'language': language, 'exit_code': result.exit_code, 'pass': passed,
                    'total_seconds': round(time.monotonic() - started, 3),
                    'execution_seconds': round(result.duration_seconds, 3)}
            receipt['cases'].append(case)
            print(json.dumps(case), flush=True)
            if not passed:
                raise RuntimeError(f'{language} execution did not produce the expected output')
    finally:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(json.dumps(receipt, indent=2) + '\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
