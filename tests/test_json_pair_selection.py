import json
from pathlib import Path
import tempfile
import unittest

from localqa.input_json import (AmbiguousJSONPairError, SingleLanguageJSONError,
                               load_json, load_json_pair, resolve_json_pair)


class JsonPairSelectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def write(self, name, content=None):
        path = self.root / name
        path.write_text(json.dumps(content or {'title': 'Title'}), encoding='utf-8')
        return path

    def test_reversed_selection_uses_locale_filename_tokens(self):
        en = self.write('data_home_en.json')
        vi = self.write('data_home_vi.json')
        self.assertEqual(resolve_json_pair([vi, en]), (en, vi))
        upper_en = self.write('APP-EN.JSON')
        upper_vi = self.write('APP-VI.JSON')
        self.assertEqual(resolve_json_pair([upper_vi, upper_en]), (upper_en, upper_vi))
        bare_en = self.write('en.json')
        bare_vi = self.write('vi.json')
        self.assertEqual(resolve_json_pair([bare_en, bare_vi]), (bare_en, bare_vi))

    def test_ambiguous_names_never_guess_from_content_or_order(self):
        for en_name, vi_name in [('source.json', 'target.json'), ('menu.json', 'view.json'),
                                 ('app_en_vi.json', 'other_vi.json'), ('first_en.json', 'second_en.json')]:
            en = self.write(en_name, {'title': 'English title'})
            vi = self.write(vi_name, {'title': 'Tiếng Việt'})
            with self.assertRaises(AmbiguousJSONPairError):
                resolve_json_pair([en, vi])

    def test_invalid_file_selection_is_not_role_ambiguity(self):
        en = self.write('en.json')
        vi = self.write('vi.json')
        invalid = self.write('target.txt')
        for selection in [[en], [en, vi, invalid], [en, en], [en, invalid],
                          [en, self.root/'missing_vi.json'], str(en)]:
            with self.subTest(selection=selection):
                with self.assertRaises(ValueError) as caught:
                    resolve_json_pair(selection)
                self.assertNotIsInstance(caught.exception, AmbiguousJSONPairError)

    def test_symlink_to_same_file_is_rejected(self):
        en = self.write('en.json')
        alias = self.root/'vi.json'
        try:
            alias.symlink_to(en)
        except (OSError, NotImplementedError):
            self.skipTest('Symlinks unavailable on this host')
        with self.assertRaisesRegex(ValueError, 'hai file riêng'):
            resolve_json_pair([en, alias])
        with self.assertRaisesRegex(ValueError, 'hai file riêng'):
            load_json_pair(en, alias)

    def test_single_language_assets_and_flat_maps_have_actionable_error(self):
        documents = [
            {'save': 'Save', 'cancel': 'Cancel'},
            {'schemaVersion': 1, 'tutorials': [{'id': 'cat', 'name': 'Cat',
                                               'data': [{'description': 'Fold the paper.'}]}]},
        ]
        for document in documents:
            with self.subTest(document=document):
                path = self.write('data_home_en.json', document)
                before = path.read_bytes()
                with self.assertRaisesRegex(SingleLanguageJSONError, 'ngôn ngữ còn lại'):
                    load_json(path)
                self.assertEqual(path.read_bytes(), before)

    def test_malformed_paired_data_does_not_trigger_pairing(self):
        malformed = [
            {'a': {'english': 'Save'}},
            {'key': 'a', 'english': 'Save', 'vietnamese': 'Lưu'},
            {'translations': {'a': {'english': 'Save'}}},
            {'en': {'a': []}, 'vi': {}},
            {'unsupported': [1, 2]},
        ]
        for document in malformed:
            with self.subTest(document=document):
                with self.assertRaises(ValueError) as caught:
                    load_json(self.write('invalid.json', document))
                self.assertNotIsInstance(caught.exception, SingleLanguageJSONError)
        path = self.root/'broken.json';path.write_text('{', encoding='utf-8')
        with self.assertRaises(ValueError) as caught:
            load_json(path)
        self.assertNotIsInstance(caught.exception, SingleLanguageJSONError)

    def test_existing_bilingual_and_asset_pair_imports_remain_valid(self):
        row = {'key': 'a', 'english': 'Save', 'vietnamese': 'Lưu'}
        self.assertEqual(load_json(self.write('paired.json', [row]))[0][0]['vietnamese'], 'Lưu')
        en = self.write('data_home_en.json', {'tutorials': [{'id': 'cat', 'name': 'Cat'}]})
        vi = self.write('data_home_vi.json', {'tutorials': [{'id': 'cat', 'name': 'Mèo'}]})
        ordered = resolve_json_pair([vi, en])
        rows, report = load_json_pair(*ordered)
        self.assertEqual(rows[0]['english'], 'Cat')
        self.assertEqual(rows[0]['vietnamese'], 'Mèo')
        self.assertEqual(report['diagnostics'], [])


if __name__ == '__main__':
    unittest.main()
