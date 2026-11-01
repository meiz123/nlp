"""Regression checks for user feedback while opening and reviewing data."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication
from localqa.app import Window
from localqa.core import Project


class ReviewWorkflowAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        path = self.root / 'review.lqa'
        project = Project(path)
        project.import_rows([
            {'key': str(i), 'english': f'English {i}', 'vietnamese': f'Việt {i}'}
            for i in range(3)
        ])
        project.close()
        with patch('keyring.get_password', return_value=''):
            self.window = Window()
        self.window.attach(str(path))
        self.window.table.selectRow(0)
        self.errors = []
        self.window.error = self.errors.append

    def tearDown(self):
        self.window.close()
        self.temp.cleanup()

    def test_empty_csv_does_not_create_or_switch_project(self):
        source = self.root / 'empty.csv'
        source.write_text('key,english,vietnamese\n', encoding='utf-8')
        original = self.window.project.path
        self.window.notes.setPlainText('Keep this note draft')
        self.window.choose_files = lambda *args: [str(source)]
        with patch.object(self.window, 'choose_file') as save_picker:
            self.window.open()
        self.assertFalse(save_picker.called)
        self.assertEqual(self.window.project.path, original)
        self.assertEqual(len(self.window.project.rows()), 3)
        self.assertEqual(self.window.notes.toPlainText(), 'Keep this note draft')
        self.assertEqual(len(self.errors), 1)

    def test_translation_draft_survives_review_and_notes_refresh(self):
        self.window.translation.setPlainText('Bản sửa chưa duyệt')
        self.window.notes.setPlainText('Cần diễn đạt tự nhiên hơn')
        self.window.reviewcheck.setChecked(True)
        self.assertEqual(self.window.translation.toPlainText(), 'Bản sửa chưa duyệt')
        self.window.save_review_notes()
        self.assertEqual(self.window.translation.toPlainText(), 'Bản sửa chưa duyệt')
        self.window.table.selectRow(1)
        self.window.table.selectRow(0)
        self.assertEqual(self.window.translation.toPlainText(), 'Bản sửa chưa duyệt')
        row = self.window.project.rows()[0]
        self.assertEqual(row['notes'], 'Cần diễn đạt tự nhiên hơn')
        self.assertIsNone(row['approved'])
        from localqa.core import export_training
        self.assertEqual(export_training(self.window.project, self.root / 'train.jsonl'), 0)

    def test_translation_draft_survives_reopen_without_approval(self):
        self.window.translation.setPlainText('Bản sửa nháp')
        project_path = self.window.project.path
        self.window.close()
        with patch('keyring.get_password', return_value=''):
            self.window = Window()
        self.window.attach(project_path)
        self.window.table.selectRow(0)
        self.assertEqual(self.window.translation.toPlainText(), 'Bản sửa nháp')
        self.assertIsNone(self.window.project.rows()[0]['approved'])

    def test_approve_in_pending_filter_advances_exactly_one_row(self):
        self.window.filter.setCurrentIndex(5)
        self.window.table.selectRow(0)
        self.window.translation.setPlainText('Đã sửa câu đầu')
        self.window.approve()
        self.assertEqual(self.window._selected_key, '1')
        self.assertEqual(self.window.project.rows()[0]['approved'], 'Đã sửa câu đầu')
        self.assertIsNone(self.window.project.rows()[1]['approved'])

    def test_comparison_review_filter_matches_pending_disagreement(self):
        self.window.project.save_comparison('1', {'winner': 'gemini', 'reason': 'Needs review'})
        self.window.refresh()
        self.window.filter.setCurrentIndex(1)
        self.assertFalse(self.window.table.isRowHidden(1))
        self.assertTrue(self.window.table.isRowHidden(0))
        self.assertEqual(self.window._selected_key, '1')

    def test_changed_source_discards_draft_before_and_after_reopen(self):
        self.window.translation.setPlainText('Bản nháp theo nguồn cũ')
        self.window.project.import_rows([
            {'key': '0', 'english': 'Updated English', 'vietnamese': 'Bản Việt mới', 'context': 'New screen'}
        ])
        self.window.refresh()
        self.assertEqual(self.window.translation.toPlainText(), 'Bản Việt mới')
        project_path = self.window.project.path
        self.window.close()
        with patch('keyring.get_password', return_value=''):
            self.window = Window()
        self.window.attach(project_path)
        self.window.table.selectRow(0)
        self.assertEqual(self.window.translation.toPlainText(), 'Bản Việt mới')
        self.assertIsNone(self.window.project.rows()[0]['approved'])
        from localqa.core import export_training
        self.assertEqual(export_training(self.window.project, self.root / 'new-source-train.jsonl'), 0)
