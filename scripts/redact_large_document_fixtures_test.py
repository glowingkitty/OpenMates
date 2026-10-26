"""Synthetic corpus integrity checks; no inference, network, or model assets."""
import hashlib
import unittest

import redact_large_document_fixtures as fixtures


class LargeDocumentFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = fixtures.generate()

    # contract-test: supporting surface=cli assertions=pii.surface.semantic-parity
    def test_deterministic_varied_corpus_and_size_bounds(self):
        self.assertEqual(self.rows, fixtures.generate())
        self.assertEqual(len(self.rows), 10)
        self.assertEqual(len({row['id'] for row in self.rows}), 10)
        for row in self.rows:
            target = next(int(part) for part in row['id'].split('-') if part.isdigit())
            self.assertGreaterEqual(len(row['text'].encode()), target)
            self.assertLess(len(row['text'].encode()), target + 1024)
            lines = [line for line in row['text'].splitlines() if len(line) > 50]
            self.assertGreater(len(set(lines)) / len(lines), 0.90)
        for row, entry in zip(self.rows, fixtures.manifest(self.rows)['rows']):
            self.assertEqual(entry['text_sha256'], hashlib.sha256(row['text'].encode()).hexdigest())

    # contract-test: supporting surface=cli assertions=pii.surface.semantic-parity
    def test_every_annotation_matches_a_value_and_repeats_have_distinct_offsets(self):
        for row in self.rows:
            encoded = row['text'].encode('utf-16-le')
            found = []
            for item in row['annotations']:
                value = encoded[item['start'] * 2:item['end'] * 2].decode('utf-16-le')
                self.assertIn([item['label'], value], row['expected'])
                found.append(value)
            if not row['annotations']:
                self.assertEqual(row['expected'], [])
                continue
            self.assertEqual(found.count('Amina Okafor'), 3)
            self.assertEqual(found.count('Élodie Moreau'), 2)
            self.assertIn('\r\n', row['text'])
            self.assertIn('🌿', row['text'])
            for boundary in (150, 300, 600):
                self.assertTrue(any(a['start'] < boundary < a['end']
                                    for a in row['annotations']))
            self.assertTrue(any(a['start'] > fixtures.utf16_length(row['text']) * .95
                                for a in row['annotations']))

    # contract-test: supporting surface=cli assertions=pii.surface.semantic-parity
    def test_occurrence_scoring_does_not_reuse_first_person_match(self):
        row = next(row for row in self.rows if row['annotations'])
        cases = [{'id': row['id'], 'spans': row['annotations'][:1]}]
        result = fixtures.score_annotations([row], cases)[0]['occurrences']
        self.assertTrue(result[0]['fully_hidden'])
        self.assertFalse(result[-4]['fully_hidden'])
        complete = fixtures.score_annotations([row], [{'id': row['id'], 'spans': row['annotations']}])
        self.assertTrue(all(item['fully_hidden'] for item in complete[0]['occurrences']))
        with self.assertRaises(ValueError):
            fixtures.score_annotations([row], [])
        with self.assertRaises(ValueError):
            fixtures.score_annotations([row], cases * 2)

    # contract-test: supporting surface=cli assertions=pii.surface.semantic-parity
    def test_negative_control_scores_false_positive(self):
        row = next(row for row in self.rows if not row['annotations'])
        result = fixtures.score_annotations([row], [{'id': row['id'], 'spans': [
            {'start': 0, 'end': 4, 'label': 'PERSON'}]}])
        self.assertTrue(result[0]['negative_false_positive'])


if __name__ == '__main__':
    unittest.main()
