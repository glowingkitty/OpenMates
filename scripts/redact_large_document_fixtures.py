#!/usr/bin/env python3
"""Generate deterministic synthetic large documents; never run inference.

Annotations address *every occurrence* in UTF-16 units. ``expected`` is a unique
value inventory for inspection, not an occurrence scorer. Inputs deliberately
vary each filler block so a repeated-sentence cache cannot dominate timings.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import random
import unicodedata

from redact_rust_evaluation import load_fixtures, utf16_length

KINDS = ('prose', 'markdown', 'typescript', 'python-config')
SIZES = (32 * 1024, 128 * 1024)
WORDS = ('amber', 'cobalt', 'woven', 'orbit', 'delta', 'quiet', 'granular',
         'mosaic', 'tidal', 'brisk', 'copper', 'elastic', 'frost', 'meadow',
         'slate', 'ripple', 'lucent', 'fern', 'crisp', 'lattice', 'velvet',
         'glimmer', 'plume', 'quartz', 'reed', 'satin', 'willow', 'dune')


def filler(kind, index, rng):
    words = rng.sample(WORDS, 12)
    if kind == 'prose':
        return (f"Observation {index}: the {words[0]} {words[1]} sample follows a "
                f"{words[2]} path across the {words[3]} surface. Compare "
                f"{' '.join(words[4:8])} with {' '.join(words[8:])}; record texture "
                "and direction without inferring a cause.\r\n")
    if kind == 'markdown':
        return (f"### Trial {index}: {' '.join(words[:3])}\r\n"
                f"- Texture: {' '.join(words[3:7])}\r\n"
                f"- Method: compare {' '.join(words[7:])} before drying.\r\n"
                f"| phase | estimate |\r\n| --- | --- |\r\n| sieve | {index % 97} |\r\n\r\n")
    if kind == 'typescript':
        return (f"const sample_{index} = {{ texture: '{words[0]}', "
                f"tags: {json.dumps(words[1:7])}, enabled: true }};\r\n"
                f"function transform_{index}(items: number[]): number[] {{ "
                f"return items.map(value => value * {index % 17 + 1}); }}\r\n"
                f"// Compare {' '.join(words[7:])} using a bounded buffer.\r\n")
    return (f"def transform_{index}(items):\r\n"
            f"    return [item * {index % 17 + 1} for item in items]\r\n"
            f"# {' '.join(words[:6])}\r\n"
            f"[stage_{index}]\r\nmode = \"{words[6]}\"\r\n"
            f"tags = {json.dumps(words[7:])}\r\n\r\n")


class Document:
    def __init__(self, kind, size):
        self.kind, self.size = kind, size
        self.parts, self.annotations, self.expected = [], [], []
        self.units = self.bytes = self.index = 0
        self.rng = random.Random(f'openmates-synthetic-v1:{kind}:{size}')

    def append(self, text):
        self.parts.append(text)
        self.units += utf16_length(text)
        self.bytes += len(text.encode())

    def add_fixture(self, fixture):
        self.append('// ' if self.kind == 'typescript' else '# ' if self.kind == 'python-config' else '')
        base = self.units
        self.append(fixture['text'])
        for label, value in fixture['expected']:
            cursor = 0
            while (position := fixture['text'].find(value, cursor)) >= 0:
                start = base + utf16_length(fixture['text'][:position])
                self.annotations.append({'label': label, 'start': start,
                                         'end': start + utf16_length(value)})
                cursor = position + len(value)
            if [label, value] not in self.expected:
                self.expected.append([label, value])
        self.append('\r\n')

    def fill_bytes(self, target):
        while self.bytes < target:
            self.append(filler(self.kind, self.index, self.rng))
            self.index += 1

    def row(self, negative=False):
        return {'id': f'q:large-{self.kind}-{self.size}' + ('-negative' if negative else ''),
                'text': ''.join(self.parts), 'expected': self.expected,
                'annotations': self.annotations}


def generate(sizes=SIZES):
    fixtures = {row['id']: row for row in load_fixtures()}
    rows = []
    for size in sizes:
        for kind in KINDS:
            doc = Document(kind, size)
            doc.add_fixture(fixtures['name-emoji'])
            # Place a name across each candidate character chunk boundary.
            # Only ASCII appears after the initial emoji; units account for it.
            for boundary in (150, 300, 600):
                prefix = '// Customer: ' if kind == 'typescript' else '# Customer: ' if kind == 'python-config' else 'Customer: '
                comment = '// ' if kind == 'typescript' else '# ' if kind == 'python-config' else ''
                target = boundary - 5 - utf16_length(prefix + comment)
                doc.append(' ' * max(0, target - doc.units))
                doc.add_fixture({'text': prefix + 'Amina Okafor needs help.',
                                 'expected': [['private_person', 'Amina Okafor']]})
            for key in ('address-uk', 'email-plus', 'account-iban'):
                doc.add_fixture(fixtures[key])
            doc.fill_bytes(size // 2)
            for key in ('name-german', 'address-de', 'email-unicode-context', 'secret-github'):
                doc.add_fixture(fixtures[key])
            doc.append('日本語の試験記録。 العربية: سجل تجريبي. 🌿\r\n')
            doc.fill_bytes(size - 650)
            for key in ('name-emoji', 'address-uk', 'email-plus', 'account-iban'):
                doc.add_fixture(fixtures[key])
            doc.fill_bytes(size)
            rows.append(doc.row())
        doc = Document('typescript', size)
        doc.append('// Synthetic algorithm/config negative control; no person or contact data.\r\n')
        doc.fill_bytes(size)
        rows.append(doc.row(negative=True))
    return rows


def manifest(rows):
    return {'schema_version': 1, 'synthetic_only': True, 'offset_unit': 'utf16',
            'generator_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'rows': [{'id': row['id'], 'utf8_bytes': len(row['text'].encode()),
                      'utf16_units': utf16_length(row['text']),
                      'text_sha256': hashlib.sha256(row['text'].encode()).hexdigest(),
                      'annotations': len(row['annotations'])} for row in rows]}


def score_annotations(fixtures, cases):
    """Report each annotated occurrence, including missed repeats; no recall claim."""
    indexed = {row['id']: row for row in cases}
    if len(indexed) != len(cases) or set(indexed) != {row['id'] for row in fixtures}:
        raise ValueError('Require one result per fixture')
    results = []
    for fixture in fixtures:
        covered = {point for span in indexed[fixture['id']]['spans']
                   for point in range(span['start'], span['end'])}
        encoded = fixture['text'].encode('utf-16-le')
        occurrences = []
        for annotation in fixture['annotations']:
            start, end = annotation['start'], annotation['end']
            value = encoded[start * 2:end * 2].decode('utf-16-le')
            meaningful, cursor = [], start
            for char in value:
                points = range(cursor, cursor + utf16_length(char))
                if unicodedata.category(char)[0] in 'LNM':
                    meaningful.extend(points)
                cursor += utf16_length(char)
            occurrences.append(dict(annotation,
                fully_hidden=all(i in covered for i in range(start, end)),
                letters_digits_marks_hidden=all(i in covered for i in meaningful)))
        results.append({'id': fixture['id'], 'occurrences': occurrences,
                        'negative_false_positive': not occurrences and bool(covered)})
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-directory', type=Path, required=True)
    args = parser.parse_args()
    rows = generate()
    args.output_directory.mkdir(parents=True, exist_ok=True)
    for name, value in (('large-document-inputs.json', rows),
                        ('large-document-manifest.json', manifest(rows))):
        path = args.output_directory / name
        if path.exists():
            parser.error(f'Refusing to replace retained fixture evidence: {path}')
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(manifest(rows), indent=2))


if __name__ == '__main__':
    main()
