"""Parity and per-occurrence regression checks for the private native benchmark."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import redact_parallel_evaluation as evaluation


class ParallelEvaluationTests(unittest.TestCase):
    def fixture(self):
        return evaluation.annotated({'id': 'q:repeated', 'text': '👋 Amina Okafor; Amina Okafor',
                                     'expected': [['PERSON', 'Amina Okafor']]})

    def result(self, row):
        return {'status': 'complete', 'cases': [{'id': row['id'], 'stable': True,
                'characters_utf16': evaluation.rust.utf16_length(row['text']),
                'spans': [dict(item) for item in row['annotations']]}]}

    # contract-test: supporting surface=cli assertions=pii.surface.semantic-parity
    def test_repeated_values_are_annotated_in_utf16(self):
        self.assertEqual(self.fixture()['annotations'], [
            {'label': 'PERSON', 'start': 3, 'end': 15},
            {'label': 'PERSON', 'start': 17, 'end': 29}])

    # contract-test: supporting surface=cli assertions=pii.surface.semantic-parity
    def test_parity_checks_labels_and_offsets_and_individual_loss(self):
        row = self.fixture()
        baseline = self.result(row)
        candidate = copy.deepcopy(baseline)
        candidate['cases'][0]['spans'][1]['end'] -= 1
        score = evaluation.compare([row], baseline, candidate)
        self.assertFalse(score['span_parity'])
        self.assertEqual(score['annotated_coverage_losses'], [{
            'id': row['id'], 'annotation': 1, 'lost_characters': 1,
            'lost_meaningful_characters': 1}])
        self.assertTrue(evaluation.compare([row], baseline, baseline)['span_parity'])

    # contract-test: supporting surface=cli assertions=pii.surface.semantic-parity
    def test_rejects_missing_duplicate_unstable_or_wrong_length_results(self):
        row = self.fixture()
        good = self.result(row)
        for change in ('missing', 'duplicate', 'unstable', 'length'):
            candidate = copy.deepcopy(good)
            if change == 'missing':
                candidate['cases'] = []
            elif change == 'duplicate':
                candidate['cases'] *= 2
            elif change == 'unstable':
                candidate['cases'][0]['stable'] = False
            else:
                candidate['cases'][0]['characters_utf16'] -= 1
            with self.assertRaises(ValueError):
                evaluation.compare([row], good, candidate)

    # contract-test: supporting surface=cli assertions=pii.surface.semantic-parity
    def test_parallel_build_rejects_licensing_edits_and_runtime_replacement(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            native = root / 'native'
            native.mkdir()
            items = []
            for name in ('libRedactNode.so', 'libLiteRt.so'):
                p = native / name
                p.write_bytes(name.encode())
                items.append({'file': name, 'bytes': p.stat().st_size,
                              'sha256': hashlib.sha256(p.read_bytes()).hexdigest()})
            patch_file = root / 'benchmark-parallel.patch'
            patch_file.write_text('private benchmark fixture')
            (root / 'manifest.json').write_text(json.dumps({'static_host_native_files': items}))
            receipt = {'sdk_commit': evaluation.SDK_COMMIT,
                       'native_path': str(native / 'libRedactNode.so'),
                       'native_files': items, 'parallel_patch_sha256': evaluation.rust.digest(patch_file),
                       'source_integrity_audit': {'changed_tracked_files': evaluation.CHANGED,
                                                  'only_benchmark_parallel_patch': True}}
            path = root / 'receipt.json'
            path.write_text(json.dumps(receipt))
            with patch.object(evaluation.rust, 'HISTORY', root):
                self.assertEqual(evaluation.verify_parallel(native, path), items)
                modified = copy.deepcopy(receipt)
                modified['source_integrity_audit']['changed_tracked_files'].append('Sources/Usage/Licensing.swift')
                path.write_text(json.dumps(modified))
                with self.assertRaises(ValueError):
                    evaluation.verify_parallel(native, path)
                modified = copy.deepcopy(receipt)
                modified['native_files'][1]['bytes'] += 1
                path.write_text(json.dumps(modified))
                with self.assertRaises(ValueError):
                    evaluation.verify_parallel(native, path)

    # contract-test: supporting surface=cli assertions=pii.surface.semantic-parity
    def test_baseline_requires_matching_input_and_published_engine_provenance(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / 'baseline.json'
            path.write_text(json.dumps({'status': 'complete', 'cases': []}))
            (root / 'manifest.json').write_text(json.dumps({'static_host_native_files': []}))
            provenance = {'input_sha256': 'same-input', 'rust_source_sha256': 'host-source',
                          'binary_sha256': 'binary', 'model_files': [],
                          'sdk_source_commit': evaluation.SDK_COMMIT, 'affinity_cpus': [0, 1]}
            receipt = dict(provenance, status='complete', workers=1,
                           build_receipt_sha256=None, result_sha256=evaluation.rust.digest(path),
                           native_files=[])
            sibling = path.with_suffix('.supervisor.json')
            sibling.write_text(json.dumps(receipt))
            with patch.object(evaluation.rust, 'HISTORY', root):
                self.assertEqual(evaluation.verify_baseline(path, provenance)['status'], 'complete')
                for key, value in [('input_sha256', 'different-same-length-text'),
                                   ('build_receipt_sha256', 'experimental'), ('workers', 2),
                                   ('result_sha256', 'wrong-output')]:
                    sibling.write_text(json.dumps(dict(receipt, **{key: value})))
                    with self.assertRaises(ValueError):
                        evaluation.verify_baseline(path, provenance)

    # contract-test: supporting surface=cli assertions=pii.surface.semantic-parity
    def test_optimized_baseline_needs_explicit_matching_build_and_mode(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / 'baseline.json'
            path.write_text(json.dumps({'status': 'complete', 'cases': []}))
            (root / 'manifest.json').write_text(json.dumps({'static_host_native_files': []}))
            provenance = {'input_sha256': 'input', 'rust_source_sha256': 'host',
                          'binary_sha256': 'binary', 'model_files': [],
                          'sdk_source_commit': evaluation.SDK_COMMIT, 'affinity_cpus': [0, 1],
                          'build_receipt_sha256': 'reviewed-fast-build', 'native_files': [],
                          'fast_gaps': 1}
            receipt = dict(provenance, status='complete', workers=1,
                           result_sha256=evaluation.rust.digest(path))
            sibling = path.with_suffix('.supervisor.json')
            sibling.write_text(json.dumps(receipt))
            with patch.object(evaluation.rust, 'HISTORY', root):
                with self.assertRaises(ValueError):
                    evaluation.verify_baseline(path, provenance)
                self.assertEqual(evaluation.verify_baseline(path, provenance, True)['status'], 'complete')
                sibling.write_text(json.dumps(dict(receipt, fast_gaps=0)))
                with self.assertRaises(ValueError):
                    evaluation.verify_baseline(path, provenance, True)


if __name__ == '__main__':
    unittest.main()
