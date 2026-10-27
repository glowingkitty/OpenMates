"""Unit checks for Rust benchmark inputs, scoring and immutable native assets."""
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

import redact_rust_evaluation as evaluation


class RustEvaluationTests(unittest.TestCase):
    # contract-test: supporting surface=cli assertions=pii.surface.semantic-parity
    def test_binary_corpus_counts_utf8_bytes_and_preserves_unicode(self):
        encoded = evaluation.encode_corpus([{'id': 'q:unicode', 'text': 'é👋'}])
        expected = struct.pack('>II', 1, 9) + b'q:unicode' + struct.pack('>I', 6) + 'é👋'.encode()
        self.assertEqual(encoded, expected)

    # contract-test: supporting surface=cli assertions=pii.surface.semantic-parity
    def test_rejects_oversized_input(self):
        with self.assertRaises(ValueError):
            evaluation.encode_corpus([{'id': 'q:large', 'text': 'x' * (1024 * 1024 + 1)}])

    # contract-test: supporting surface=cli assertions=pii.surface.semantic-parity
    def test_same_latency_lengths_as_retained_node_benchmark(self):
        rows = evaluation.corpus([32, 256, 1024, 4096], False)
        self.assertEqual([evaluation.utf16_length(row['text']) for row in rows[1:]],
                         [211, 1695, 6783, 27135])

    def quality_cases(self):
        fixtures = evaluation.load_fixtures()
        cases = []
        for row in fixtures:
            spans = []
            for label, value in row['expected']:
                start = evaluation.utf16_length(row['text'][:row['text'].index(value)])
                spans.append({'label': label, 'start': start,
                              'end': start + evaluation.utf16_length(value)})
            cases.append({'id': 'q:' + row['id'], 'spans': spans})
        return cases

    # contract-test: supporting surface=cli assertions=pii.surface.semantic-parity
    def test_scores_full_unicode_value_coverage_and_negative_cases(self):
        score = evaluation.score_quality(self.quality_cases())
        self.assertEqual(score['fully_hidden'], 50)
        self.assertEqual(score['letters_digits_marks_hidden'], 50)
        self.assertEqual(score['false_positive_cases'], 0)

    # contract-test: supporting surface=cli assertions=pii.surface.semantic-parity
    def test_does_not_hide_a_gap_between_separate_name_components(self):
        cases = self.quality_cases()
        row = next(row for row in cases if row['id'] == 'q:name-support')
        start = row['spans'][0]['start']
        row['spans'] = [{'label': 'GIVEN_NAME', 'start': start, 'end': start + 5},
                        {'label': 'SURNAME', 'start': start + 6, 'end': start + 12}]
        score = evaluation.score_quality(cases)
        self.assertEqual(score['fully_hidden'], 49)
        self.assertEqual(score['letters_digits_marks_hidden'], 50)

    # contract-test: supporting surface=cli assertions=pii.surface.semantic-parity
    def test_refuses_partial_quality_receipts(self):
        with self.assertRaises(ValueError):
            evaluation.score_quality(self.quality_cases()[:-1])

    # contract-test: supporting surface=cli assertions=pii.surface.semantic-parity
    def test_context_sweep_keeps_expected_values_and_requires_every_window(self):
        windows = evaluation.context_fixtures()
        self.assertEqual(len(windows), 32)
        cases = self.quality_cases()
        for fixture in windows:
            spans = []
            for label, value in fixture['expected']:
                start = evaluation.utf16_length(fixture['text'][:fixture['text'].index(value)])
                spans.append({'label': label, 'start': start, 'end': start + evaluation.utf16_length(value)})
            cases.append({'id': 'q:' + fixture['id'], 'spans': spans})
        result = evaluation.score_quality(cases)
        self.assertEqual(result['fully_hidden'], 50)
        self.assertEqual(result['context_boundaries']['fully_hidden'], 32)
        with self.assertRaises(ValueError):
            evaluation.score_quality(cases[:-1])

    # contract-test: supporting surface=cli assertions=pii.surface.semantic-parity
    def test_checks_both_size_and_hash_of_native_package(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            library = root / 'libRedactNode.so'
            library.write_bytes(b'original native fixture')
            item = {'file': library.name, 'bytes': library.stat().st_size,
                    'sha256': hashlib.sha256(library.read_bytes()).hexdigest()}
            (root / 'manifest.json').write_text(json.dumps({'static_host_native_files': [item]}))
            with patch.object(evaluation, 'HISTORY', root):
                self.assertEqual(evaluation.verify_native(root), [item])
                library.write_bytes(b'modified native fixture')
                with self.assertRaises(ValueError):
                    evaluation.verify_native(root)

    # contract-test: supporting surface=cli assertions=pii.surface.semantic-parity
    def test_experiment_requires_the_pinned_source_and_exclusive_chunking_patch(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            native = root / 'native'
            native.mkdir()
            core = native / 'libRedactNode.so'
            core.write_bytes(b'private benchmark fixture')
            patch_file = root / 'benchmark-chunking.patch'
            patch_file.write_text('benchmark-only patch fixture')
            expected = {'file': core.name, 'bytes': core.stat().st_size,
                        'sha256': evaluation.digest(core)}
            (root / 'manifest.json').write_text(json.dumps({'sdk_source_revision': 'pinned',
                                                          'static_host_native_files': []}))
            receipt = {'sdk_commit': 'pinned', 'native_path': str(core),
                       'native_files': [expected], 'chunking_patch_sha256': evaluation.digest(patch_file),
                       'source_integrity_audit': {'changed_tracked_files': ['Sources/Redact/Model.swift'],
                                                  'only_benchmark_chunking_patch': True}}
            receipt_file = root / 'receipt.json'
            receipt_file.write_text(json.dumps(receipt))
            with patch.object(evaluation, 'HISTORY', root):
                self.assertEqual(evaluation.verify_native(native, receipt_file), [expected])
                receipt['source_integrity_audit']['changed_tracked_files'].append('Sources/Usage/Licensing.swift')
                receipt_file.write_text(json.dumps(receipt))
                with self.assertRaises(ValueError):
                    evaluation.verify_native(native, receipt_file)


if __name__ == '__main__':
    unittest.main()
