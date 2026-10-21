"""Opt-in granular Jev text/image qualification on public controlled evidence.

Runs inside the API container for Vault access. No account, chat, feed or pool
writes occur. JPEG panels are prepared offline with a separate renderer. Labels
and translations are automated, not native-speaker approval. Requests, decisions,
input hashes and partial receipts are retained; no paid case is silently rerun.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
from pathlib import Path
import time
from unittest.mock import patch

FIXTURES = Path(__file__).with_name('fixtures')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    temporary.replace(path)


def scrub(value):
    if isinstance(value, dict):
        return {key: ({'sha256': hashlib.sha256(base64.b64decode(item)).hexdigest()}
                      if key == 'data_base64' else scrub(item)) for key, item in value.items()}
    if isinstance(value, list):
        return [scrub(item) for item in value]
    return value


def cases_for(options):
    fixture = FIXTURES / {'text': 'daily_inspiration_editorial_v6.json',
                          'images': 'daily_inspiration_thumbnail_v6.json',
                          'regressions': 'daily_inspiration_prior_findings_v6.json'}[options.mode]
    payload = json.loads(fixture.read_text())
    cases = payload['cases']
    if options.languages:
        cases = [case for case in cases if case['language'] in options.languages]
    if options.limit:
        cases = cases[:options.limit]
    if not cases or len({case['id'] for case in cases}) != len(cases):
        raise ValueError('Empty or duplicate control catalogue')
    return fixture, cases


async def run(options):
    from backend.apps.ai.daily_inspiration import decisions, thumbnail_review, writer
    from backend.core.api.app.utils.secrets_manager import SecretsManager
    from backend.shared.providers.typesafe.client import JevDecisionClient
    fixture, cases = cases_for(options)
    root = options.output_dir
    source_hashes = {Path(module.__file__).name: digest(Path(module.__file__))
                     for module in (decisions, thumbnail_review, writer)}
    if options.expected_source_manifest:
        expected = json.loads(options.expected_source_manifest.read_text())
        if any(expected.get(key) != value for key, value in source_hashes.items()):
            raise ValueError('Runtime differs from the reviewed candidate')
    image_manifest, images = None, {}
    if options.mode == 'images':
        if not options.image_root:
            raise ValueError('Images require --image-root from the offline renderer')
        image_manifest = json.loads((options.image_root / 'manifest.json').read_text())
        if image_manifest['fixture_sha256'] != digest(fixture):
            raise ValueError('Image fixture differs from the reviewed text')
        rendered = {item['id']: item for item in image_manifest['cases']}
        for case in cases:
            panel = rendered[case['id']]
            case_hash = hashlib.sha256(json.dumps(case, sort_keys=True, separators=(',', ':'),
                                                 ensure_ascii=False).encode()).hexdigest()
            readable = panel['readability']
            if (panel['case_sha256'] != case_hash or panel['status'] != 'rendered'
                    or not panel['font']['glyph_coverage']['complete']
                    or panel['shaping']['engine'] != 'RAQM'
                    or not readable['within_canvas'] or readable['truncated']
                    or not readable['text_preserved'] or not 20 <= readable['font_size_px'] <= 34
                    or panel['image_file'] != case['id'] + '.jpg'):
                raise ValueError('Unverified or unreadable image control')
            raw = (options.image_root / panel['image_file']).read_bytes()
            if (hashlib.sha256(raw).hexdigest() != panel['image_sha256']
                    or len(raw) != panel['image_bytes'] or len(raw) > 1_048_576):
                raise ValueError('Image control bytes differ from verified rendering')
            images[case['id']] = raw
    manifest = {'mode': options.mode, 'policy': decisions.POLICY_VERSION,
                'sources': source_hashes, 'fixture_sha256': digest(fixture),
                'case_ids': [case['id'] for case in cases],
                'script_sha256': digest(Path(__file__)),
                'image_manifest_sha256': digest(options.image_root / 'manifest.json') if image_manifest else None,
                'labels': 'Automated controlled labels; not native-speaker or human gold.'}
    manifest_path = root / 'manifest.json'
    if manifest_path.exists() and json.loads(manifest_path.read_text()) != manifest:
        raise ValueError('Retain original receipts; changed input needs a new output directory')
    save(manifest_path, manifest)
    manager = SecretsManager()
    await manager.initialize()
    results = []
    try:
        for case in cases:
            path = root / 'cases' / (case['id'] + '.json')
            if path.exists():
                old = json.loads(path.read_text())
                if old.get('status') == 'complete':
                    results.append(old)
                    continue
                raise ValueError('Interrupted paid case retained; explicitly archive before retry')
            row = {'id': case['id'], 'language': case['language'], 'family': case['family'],
                   'expected': case['expected'], 'status': 'started', 'decisions': [], 'accounting': []}
            save(path, row)
            class Client:
                def __init__(self, **kwargs):
                    self.real = JevDecisionClient(**{**kwargs, 'max_retries': 0, 'accounting': row['accounting']})
                async def evaluate(self, **kwargs):
                    entry = {'request': scrub(kwargs)}
                    row['decisions'].append(entry)
                    save(path, row)
                    try:
                        response = await self.real.evaluate(**kwargs)
                        entry['response'] = response.model_dump(mode='json')
                        return response
                    finally:
                        save(path, row)
            start = time.monotonic()
            try:
                if options.mode != 'images':
                    with patch.object(decisions, 'JevDecisionClient', Client):
                        actual = await decisions.review_candidates([case['candidate']], manager)
                else:
                    # Renderer files are fixed by the controlled case ID and hash.
                    image = images[case['id']]
                    row['image_sha256'] = hashlib.sha256(image).hexdigest()
                    async def pixels(_identity):
                        return image
                    with patch.object(thumbnail_review, 'fetch_thumbnail', pixels):
                        actual = await thumbnail_review.review_thumbnails([case['candidate']],
                            Client(secrets_manager=manager, telemetry_purpose='inspiration_decision'))
                row['actual'] = 'allow' if actual else 'reject'
            except Exception as error:
                row['error'] = type(error).__name__
            row['seconds'] = time.monotonic() - start
            row['available'] = bool(row['decisions']) and all('response' in d for d in row['decisions'])
            row['correct'] = (row['available'] and row.get('actual') == row['expected']
                              if row['expected'] != 'uncertain' else None)
            row['status'] = 'complete'
            save(path, row)
            results.append(row)
            print(json.dumps({key: row.get(key) for key in ('id', 'expected', 'actual', 'correct', 'available')}), flush=True)
    finally:
        await manager.aclose()
    summary = {'total': len(results), 'scored_total': sum(r['expected'] != 'uncertain' for r in results),
               'correct': sum(r['correct'] is True for r in results),
               'false_admissions': sum(r['available'] and r['expected'] == 'reject' and r.get('actual') == 'allow' for r in results),
               'false_rejections': sum(r['available'] and r['expected'] == 'allow' and r.get('actual') == 'reject' for r in results),
               'unavailable': sum(not r['available'] for r in results),
               'jev_input_tokens': sum(a.get('input_tokens') or 0 for r in results for a in r['accounting']),
               'limitations': manifest['labels']}
    summary['known_jev_usd_estimate'] = summary['jev_input_tokens'] * .042 / 1_000_000
    save(root / 'summary.json', summary)
    print(json.dumps(summary, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--mode', choices=['text', 'images', 'regressions'], default='text')
    parser.add_argument('--languages', nargs='+')
    parser.add_argument('--limit', type=int, choices=range(1, 121))
    parser.add_argument('--image-root', type=Path)
    parser.add_argument('--expected-source-manifest', type=Path)
    options = parser.parse_args()
    if options.execute:
        asyncio.run(run(options))
    else:
        fixture, cases = cases_for(options)
        print(json.dumps({'execute': False, 'mode': options.mode, 'cases': len(cases),
                          'fixture_sha256': digest(fixture)}, indent=2))


if __name__ == '__main__':
    main()
