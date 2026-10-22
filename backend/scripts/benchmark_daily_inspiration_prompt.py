"""Opt-in EN/DE comparison: original Mercury, clearer Mercury and current Gemini.

Reuses immutable discovery, native accounting and exact production Jev admission.
Prompt selection is diagnostic only; account, pool and runtime writer are untouched.
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import contextmanager, ExitStack
import hashlib
import json
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from backend.scripts import benchmark_daily_inspiration_multilingual as base

ARM_MODELS = {'gemini38_only': 'google/gemini-3.8-flash',
              'mercury3_only': 'inception/mercury-3',
              'mercury3_clear': 'inception/mercury-3'}
ARM_PROFILES = {'gemini38_only': {'temperature': 1.0, 'reasoning_effort': 'provider_default'},
                'mercury3_only': {'temperature': .5, 'reasoning_effort': 'low'},
                'mercury3_clear': {'temperature': .5, 'reasoning_effort': 'low'}}


def transform_request(request, sources, kind, language, arm):
    """Change instructions/evidence presentation alone, keeping Mercury settings fixed."""
    if arm != 'mercury3_clear':
        return request
    from backend.apps.ai.daily_inspiration.writer_prompt import build_writer_request
    evidence = [source['candidate'] if kind == 'video' else source['approved']
                for source in sources]
    prepared = build_writer_request(kind, language, evidence, request['tool_definition'])
    return {**request, **prepared, 'reasoning_effort': 'low', 'temperature': .5}


@contextmanager
def configured_benchmark():
    """Restore every diagnostic seam even on failure; never alter account defaults."""
    qualify, build_manifest = base.qualify_batch, base.build_manifest

    async def qualify_prompt(*args, **kwargs):
        return await qualify(*args, **kwargs, writer_request_transform=transform_request)

    def manifest(options):
        from backend.apps.ai.daily_inspiration import writer_prompt
        unchecked = SimpleNamespace(**{**vars(options), 'expected_source_manifest': None})
        value = build_manifest(unchecked)
        path = Path(writer_prompt.__file__)
        value['source_sha256'][path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        value['prompt_benchmark_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        value['comparison'] = 'original_mercury_vs_clear_mercury_vs_current_gemini'
        base.validate_source_manifest(value['source_sha256'], options.expected_source_manifest)
        return value

    topics = {**base.TOPICS, 'en': 'Aurora borealis|Paper recycling|Seed dispersal',
              'de': 'Polarlicht|Papierrecycling|Samenausbreitung'}
    with ExitStack() as stack:
        for name, value in {
            'ARM_MODELS': ARM_MODELS, 'ARM_PROFILES': ARM_PROFILES, 'ARMS': tuple(ARM_MODELS),
            'ARM_ORDER_SEED': 'daily-inspiration-clear-prompt-v1', 'TOPICS': topics,
            'DISCOVERY_BATCH_SIZE': 1, 'qualify_batch': qualify_prompt, 'build_manifest': manifest,
        }.items():
            stack.enter_context(patch.object(base, name, value))
        yield


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--languages', nargs='+', choices=['en', 'de'], default=['en', 'de'])
    parser.add_argument('--limit', type=int, choices=[1, 2, 3], default=3)
    parser.add_argument('--phase-minutes', type=int, choices=range(1, 31), default=15)
    parser.add_argument('--collect-only', action='store_true')
    parser.add_argument('--expected-source-manifest')
    options = parser.parse_args()
    options.exclude_source_root = None
    options.frozen_source_manifest = None
    if not options.execute:
        print(json.dumps({'execute': False, 'arm_models': ARM_MODELS,
                          'planned_source_slots': len(options.languages) * options.limit * 2,
                          'max_native_writer_calls': len(options.languages) * options.limit * 6,
                          'one_attempt_per_arm_source': True, 'unchanged_jev_gates': True}))
        return
    base.load_runtime()
    logging.basicConfig(level=logging.ERROR)
    with configured_benchmark():
        result = asyncio.run(base.run(options))
    print(json.dumps({'output_dir': options.output_dir, 'arms': {
        arm: {key: values.get(key) for key in ('admitted', 'requested', 'completed_batches',
               'known_supplier_usd_estimate', 'supplier_upper_bound_usd_estimate')}
        for arm, values in result.get('arms', {}).items()}}))


if __name__ == '__main__':
    main()
