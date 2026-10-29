import copy
import json
from pathlib import Path
import tempfile
import unittest

from localqa.input_json import load_json, load_json_pair


class JsonInputTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def write(self, name, document):
        path = self.root / name
        path.write_text(json.dumps(document, ensure_ascii=False), encoding='utf-8-sig')
        return path

    def test_list_preserves_whitespace_placeholders_and_context(self):
        original = [{'key': 'save', 'english': ' Hi %1$s\n', 'vietnamese': ' Chào %1$s\n', 'context': 'Welcome'}]
        path = self.write('input.json', original)
        before = path.read_bytes()
        rows, report = load_json(path)
        self.assertEqual(rows, original)
        self.assertEqual(report['diagnostics'], [])
        self.assertEqual(before, path.read_bytes())
        self.assertEqual(len(report['source_sha256']['input']), 64)

    def test_wrapper_and_key_mapping(self):
        row = {'key': 'a', 'english': 'Save', 'vietnamese': 'Lưu'}
        wrapped, _ = load_json(self.write('wrapped.json', {'translations': [row]}))
        mapped, _ = load_json(self.write('mapped.json', {'a': {'english': 'Save', 'vietnamese': 'Lưu'}}))
        self.assertEqual(wrapped, mapped)
        self.assertEqual(mapped[0]['context'], '')

    def test_missing_languages_are_retained_with_diagnostics(self):
        rows, report = load_json(self.write('maps.json', {'en': {'a': 'Save'}, 'vi': {'b': 'Hủy'}}))
        self.assertEqual([r['key'] for r in rows], ['a', 'b'])
        self.assertEqual(rows[0]['vietnamese'], '')
        self.assertEqual(rows[1]['english'], '')
        self.assertEqual(report['diagnostic_counts'], {'missing_vietnamese': 1, 'missing_english': 1})
        _, single = load_json(self.write('only-en.json', {'en': {'a': 'Save'}}))
        self.assertEqual(single['diagnostic_counts']['missing_vietnamese'], 1)

    def test_blank_strings_remain_data(self):
        rows, report = load_json(self.write('blank.json', [{'key':'a','english':' ','vietnamese':''}]))
        self.assertEqual(rows[0]['english'], ' ')
        self.assertEqual(report['diagnostic_counts'], {'blank_english': 1, 'blank_vietnamese': 1})

    def test_duplicate_json_object_keys_rejected_at_any_depth(self):
        for text in ['{"en":{"a":"one","a":"two"},"vi":{}}', '{"a":{},"a":{}}']:
            path = self.root / 'duplicate.json'
            path.write_text(text)
            with self.assertRaisesRegex(ValueError, 'key trùng'):
                load_json(path)

    def test_duplicate_record_keys_and_invalid_types_rejected(self):
        good = {'key':'a','english':'Save','vietnamese':'Lưu'}
        cases = [[good, good], [{'key':' ','english':'a','vietnamese':'b'}],
                 [{'key':'a','english':1,'vietnamese':'b'}],
                 [{'key':'a','english':'a','vietnamese':None}],
                 [{'key':'a','english':'a','vietnamese':'b','context':[]}],
                 {'a': {'key':'b','english':'a','vietnamese':'b'}},
                 {'en': {'a': []}, 'vi': {}}, {'translations': {}}, []]
        for document in cases:
            with self.subTest(document=document), self.assertRaises(ValueError):
                load_json(self.write('invalid.json', document))

    def test_malformed_and_nonstandard_json(self):
        for text in ['{', '{"en":{"a":NaN},"vi":{}}', '42']:
            path = self.root / 'broken.json'
            path.write_text(text)
            with self.assertRaises(ValueError):load_json(path)

    def test_pair_flat_files(self):
        rows, report = load_json_pair(self.write('en.json', {'a':'Save'}), self.write('vi.json', {'a':'Lưu','b':'Hủy'}))
        self.assertEqual(rows[0]['vietnamese'], 'Lưu')
        self.assertEqual(report['diagnostic_counts'], {'missing_english':1})
        self.assertEqual(set(report['source_sha256']), {'en','vi'})

    def test_pair_assets_matches_ids_even_when_reordered(self):
        en = {'tutorials':[{'id':'a','name':'Cat','data':[{'description':'Fold.'}]}, {'id':'b','name':'Dog'}]}
        vi = {'tutorials':[{'id':'b','name':'Chó'}, {'id':'a','name':'Mèo','data':[{'description':'Gấp.'}]}]}
        original = copy.deepcopy(en)
        rows, report = load_json_pair(self.write('en.json', en), self.write('vi.json', vi))
        mapped = {r['key']: r for r in rows}
        self.assertEqual(mapped['/tutorials/@id=a/name']['vietnamese'], 'Mèo')
        self.assertIn('ghép theo vị trí', mapped['/tutorials/@id=a/data/0/description']['context'])
        self.assertEqual(report['diagnostics'], [])
        self.assertEqual(en, original)

    def test_pair_assets_diagnostics_and_empty_unsupported(self):
        en = {'tutorials':[{'id':'a','name':'Cat'}]}
        rows, report = load_json_pair(self.write('en.json', en), self.write('vi.json', {}))
        self.assertEqual(report['diagnostic_counts']['missing_vietnamese'], 1)
        self.assertEqual(rows[0]['vietnamese'], '')
        with self.assertRaises(ValueError):
            load_json_pair(self.write('en.json', {'unsupported':[1]}), self.write('vi.json', {'unsupported':[2]}))


if __name__ == '__main__':
    unittest.main()
