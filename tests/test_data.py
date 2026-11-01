import csv
import json
import tempfile
import unittest
from pathlib import Path
from localqa.data import load_paired_csv, main, pair_json, sample_rows, write_pairs


class DataTests(unittest.TestCase):
    def test_id_pairing_survives_reordering(self):
        en = {'tutorials': [{'id': 'a', 'name': 'Cat'}, {'id': 'b', 'name': 'Dog'}]}
        vi = {'tutorials': [{'id': 'b', 'name': 'Chó'}, {'id': 'a', 'name': 'Mèo'}]}
        rows, report = pair_json(en, vi)
        self.assertEqual([(r['english'], r['vietnamese']) for r in rows], [('Cat', 'Mèo'), ('Dog', 'Chó')])
        self.assertFalse(report['diagnostics'])

    def test_only_display_fields_and_steps(self):
        en = {'tutorials': [{'id': 'a/b~c', 'name': 'Cat', 'image': 'cat.webp', 'category': 'animal',
                             'data': [{'description': 'Fold', 'video': 'a.mp4'}]}]}
        rows, _ = pair_json(en, en)
        self.assertEqual(len(rows), 2)
        self.assertIn('/tutorials/@id=a~1b~0c/data/0/description', {r['key'] for r in rows})
        self.assertNotIn('cat.webp', [r['english'] for r in rows])

    def test_duplicate_ids_are_reported_and_not_silently_overwritten(self):
        rows, report = pair_json({'items': [{'id': 'a', 'title': 'One'}, {'id': 'a', 'title': 'Two'}]},
                                 {'items': [{'id': 'a', 'title': 'Một'}]})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['english'], '')
        self.assertEqual(report['diagnostic_counts']['duplicate_id'], 1)
        self.assertEqual(report['diagnostic_counts']['missing_english'], 1)

    def test_missing_blank_and_non_string(self):
        rows, report = pair_json({'title': 'Title', 'name': 'Name', 'description': 1}, {'title': ''})
        self.assertEqual(len(rows), 2)
        self.assertEqual(set(report['diagnostic_counts']), {'invalid_text_type', 'blank_vietnamese', 'missing_vietnamese'})

    def test_csv_roundtrip_and_deterministic_sample(self):
        rows = [{'key': str(i), 'english': 'One, two\nthree', 'vietnamese': ' Một, hai\nba ', 'context': 'screen'} for i in range(20)]
        self.assertEqual(sample_rows(rows, 5, 29), sample_rows(list(reversed(rows)), 5, 29))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'pairs.csv'; write_pairs(rows, path)
            self.assertEqual(load_paired_csv(path), rows)
            self.assertEqual(main(['sample', str(path), '--count', '5', '--output', str(Path(directory)/'sample.csv')]), 0)
            metadata = json.loads((Path(directory)/'sample.report.json').read_text(encoding='utf-8'))
            self.assertEqual(metadata['sample_rows'], 5)
            self.assertEqual(len(metadata['source_sha256']), 64)

    def test_csv_rejects_duplicate_keys_and_broken_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'pairs.csv'
            for text in ['key,english,vietnamese\na,A,B\na,C,D', 'key,english,vietnamese\na,A',
                         'key,english,vietnamese\na,A,B,C', 'key,english,english,vietnamese\na,A,B,C']:
                path.write_text(text)
                with self.assertRaises(ValueError): load_paired_csv(path)

    def test_sampling_boundaries(self):
        rows = [{'key': 'a', 'english': 'A', 'vietnamese': 'B', 'context': ''}]
        for count in [0, -1, 2]:
            with self.assertRaises(ValueError): sample_rows(rows, count)

    def test_cli_never_overwrites_source(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'pairs.csv'; write_pairs([{'key':'a','english':'A','vietnamese':'B','context':''}], path)
            original = path.read_bytes()
            with self.assertRaises(SystemExit):main(['sample', str(path), '--count', '1', '--output', str(path)])
            self.assertEqual(path.read_bytes(), original)

    def test_strict_pair_cli_outputs_diagnostics(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'en.json').write_text('{"title":"Title"}')
            (root/'vi.json').write_text('{}')
            self.assertEqual(main(['pair-json', str(root/'en.json'), str(root/'vi.json'), '--output', str(root/'out.csv'), '--strict']), 2)
            self.assertEqual(json.loads((root/'out.report.json').read_text(encoding='utf-8'))['diagnostic_counts'], {'missing_vietnamese': 1})


if __name__ == '__main__': unittest.main()
