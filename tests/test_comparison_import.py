import csv
import tempfile
import unittest
from pathlib import Path
from localqa.core import Project
from localqa.comparison import import_comparison, load_comparison_csv, REQUIRED_COLUMNS


class ComparisonImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.project = Project(self.directory / 'test.lqa')
        self.row = {'key': 'a', 'english': 'Hello %s', 'original_vietnamese': 'Chào %s',
                    'local_translation': 'Chào %s', 'gemini_translation': 'Xin chào %s',
                    'winner': 'gemini', 'reason': 'Cách nói phù hợp hơn',
                    'human_approved': 'True', 'reviewed': 'True',
                    'review_notes': 'Ghi chú nhập thử', 'approved_translation': 'Xin chào %s'}

    def tearDown(self):
        self.project.close()
        self.temp.cleanup()

    def write(self, rows):
        path = self.directory / 'comparison.csv'
        fields = list(dict.fromkeys([*REQUIRED_COLUMNS, *(key for row in rows for key in row)]))
        with path.open('w', encoding='utf-8-sig', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader(); writer.writerows(rows)
        return path

    def test_originals_and_attribution_survive_reopen_without_auto_approval(self):
        self.assertEqual(import_comparison(self.project, self.write([self.row])), 1)
        self.project.close(); self.project = Project(self.directory / 'test.lqa')
        row = self.project.rows()[0]
        self.assertEqual(row['vietnamese'], 'Chào %s')
        self.assertEqual(row['reviewed'], 0)
        self.assertIsNone(row['approved'])
        backend = self.project.backend_results('a')
        self.assertEqual(backend['local']['translation'], 'Chào %s')
        self.assertEqual(backend['gemini']['translation'], 'Xin chào %s')
        self.assertFalse(backend['comparison']['human_approved'])

    def test_unchanged_source_preserves_existing_context_and_human_feedback(self):
        self.project.import_rows([{'key':'a','english':'Hello %s','vietnamese':'Chào %s','context':'Màn hình chào'}])
        self.project.save_feedback('a', True, 'Đã xem', approved_text='Chào bạn %s')
        import_comparison(self.project, self.write([self.row]))
        row = self.project.rows()[0]
        self.assertEqual(row['context'], 'Màn hình chào')
        self.assertEqual(row['approved'], 'Chào bạn %s')
        self.assertEqual(row['notes'], 'Đã xem')
        self.assertEqual(row['reviewed'], 1)

    def test_changed_source_clears_stale_feedback(self):
        import_comparison(self.project, self.write([self.row]))
        self.project.save_feedback('a', True, 'Cũ', approved_text='Chào %s')
        changed = dict(self.row, english='Welcome %s')
        import_comparison(self.project, self.write([changed]))
        row = self.project.rows()[0]
        self.assertEqual(row['english'], 'Welcome %s')
        self.assertEqual(row['reviewed'], 0)
        self.assertIsNone(row['approved'])
        self.assertEqual(row['notes'], '')

    def test_explicit_blank_approved_target_clears_prior_target(self):
        import_comparison(self.project, self.write([self.row]), import_feedback=True)
        blank = dict(self.row, approved_translation='')
        import_comparison(self.project, self.write([blank]), import_feedback=True)
        self.assertEqual(self.project.rows()[0]['approved'], '')

    def test_all_rows_validated_before_mutation(self):
        with self.assertRaises(ValueError):
            import_comparison(self.project, self.write([self.row, dict(self.row)]))
        self.assertEqual(self.project.rows(), [])
        with self.assertRaises(ValueError):
            import_comparison(self.project, self.write([dict(self.row, winner='unknown')]))
        self.assertEqual(self.project.rows(), [])

    def test_explicit_feedback_import_and_placeholder_validation(self):
        import_comparison(self.project, self.write([self.row]), import_feedback=True)
        row = self.project.rows()[0]
        self.assertEqual(row['approved'], 'Xin chào %s')
        self.assertEqual(row['notes'], 'Ghi chú nhập thử')
        for change in [{'reviewed':'maybe'}, {'reviewed':'False'}, {'approved_translation':'Xin chào'}]:
            with self.assertRaises(ValueError):
                load_comparison_csv(self.write([dict(self.row, **change)]), import_feedback=True)


if __name__ == '__main__':
    unittest.main()
