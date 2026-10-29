import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from localqa.app import Window
from localqa.core import Project


class FeedbackUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'review.lqa'
        project = Project(self.path)
        project.import_rows([
            {'key': 'hello', 'english': 'Hello %s', 'vietnamese': 'Xin chào'},
            {'key': 'save', 'english': 'Save', 'vietnamese': 'Lưu'},
        ])
        project.close()
        # UI tests must not prompt for or access real credentials.
        with patch('keyring.get_password', return_value=''):
            self.window = Window()
        self.window.attach(str(self.path))
        self.window.table.selectRow(0)
        self.errors = []
        self.window.error = self.errors.append

    def tearDown(self):
        self.window.worker = None
        self.window.close()
        self.temp.cleanup()

    def test_checkbox_is_review_not_approval_and_persists(self):
        item = self.window.table.item(0, 4)
        self.assertTrue(item.flags() & Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(Qt.CheckState.Checked)
        row = self.window.project.rows()[0]
        self.assertEqual(row['reviewed'], 1)
        self.assertIsNone(row['approved'])
        self.window.project.close()
        self.window.project = Project(self.path)
        self.window.refresh()
        self.assertEqual(self.window.table.item(0, 4).checkState(), Qt.CheckState.Checked)

    def test_notes_save_without_approving_and_draft_survives_selection(self):
        self.window.notes.setPlainText('Cần giữ tên người dùng và placeholder.')
        self.window.table.selectRow(1)
        self.window.table.selectRow(0)
        self.assertEqual(self.window.notes.toPlainText(), 'Cần giữ tên người dùng và placeholder.')
        self.window.save_review_notes()
        row = self.window.project.rows()[0]
        self.assertEqual(row['notes'], 'Cần giữ tên người dùng và placeholder.')
        self.assertEqual(row['reviewed'], 0)
        self.assertIsNone(row['approved'])

    def test_busy_blocks_feedback_writes(self):
        self.window.worker = object()
        self.window.busy(True)
        self.assertFalse(self.window.reviewcheck.isEnabled())
        self.assertTrue(self.window.notes.isReadOnly())
        self.assertFalse(self.window.table.item(0, 4).flags() & Qt.ItemFlag.ItemIsUserCheckable)
        # A stale signal cannot save user feedback during inference.
        self.window.table.item(0, 4).setCheckState(Qt.CheckState.Checked)
        self.assertEqual(self.window.project.rows()[0]['reviewed'], 0)
        self.window.worker = None
        self.window.busy(False)
        self.window.refresh()

    def test_training_export_only_after_explicit_final_approval(self):
        self.window.notes.setPlainText('Đề xuất AI thiếu placeholder')
        self.window.save_review_notes()
        self.window.reviewcheck.setChecked(True)
        output = Path(self.temp.name) / 'training.jsonl'
        self.window.choose_file = lambda *args: (str(output), 'JSON Lines (*.jsonl)')
        self.window.export_training_data()
        self.assertEqual(output.read_text(), '')
        self.window.translation.setPlainText('Xin chào %s')
        self.window.approve()
        self.window.export_training_data()
        rows = output.read_text(encoding='utf-8').splitlines()
        self.assertEqual(len(rows), 1)
        self.assertIn('Xin chào %s', rows[0])
        self.assertFalse(self.errors)

    def test_comparison_display_does_not_invent_qa_status(self):
        self.window.project.save_backend_result('hello', 'local', {'translation': 'Xin chào'})
        self.window.project.save_backend_result('hello', 'gemini', {'translation': 'Xin chào %s'})
        self.window.project.save_backend_result('hello', 'comparison', {'winner': 'gemini', 'reason': 'Giữ tên người dùng', 'context_needed': ''})
        self.window.refresh()
        self.assertEqual(self.window.table.item(0, 6).text(), 'Xin chào')
        self.assertEqual(self.window.table.item(0, 7).text(), 'Xin chào %s')
        self.assertEqual(self.window.table.item(0, 3).text(), 'Gemini tốt hơn')
        self.assertEqual(self.window.stat_labels[1].text(), '1')
        self.assertEqual(self.window.stat_labels[2].text(), '—')
        self.assertIn('đang xem kết quả so sánh', self.window.detail.toPlainText())
        self.assertIsNone(self.window.project.rows()[0]['result'])
        self.assertIsNone(self.window.project.rows()[0]['approved'])
