"""Manual notes stay editable and never leak into another sentence's feedback."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from localqa.app import Window
from localqa.core import Project, export_training

RESULT={'status':'REVIEW','issues':['Cần người dùng duyệt'],'reason':'Bản dịch đề xuất.',
        'suggestion':'Xin chào {name}','model_used':'fake-model','used_fallback':False}

class ManualNotesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'notes.lqa'
        with patch('keyring.get_password',return_value=None):self.w=Window()
        self.w.error=lambda error:self.fail(str(error))
    def tearDown(self):
        self.w.worker=None;self.w.close();self.temp.cleanup()
    def project(self):
        p=Project(self.path);p.import_rows([
            {'key':'old','english':'Save','vietnamese':'Lưu'},
            {'key':'next','english':'Cancel','vietnamese':'Hủy'}]);p.close()
        self.w.attach(str(self.path));self.w.table.selectRow(0)
    def translate_manually(self):
        self.w.manual_mode.setChecked(True);self.w.source.setPlainText('Hello {name}')
        self.w._translation_request=(True,{'key':'direct','english':'Hello {name}','vietnamese':'','context':''})
        self.w.translation_ready(dict(RESULT))
    def test_fresh_manual_notes_accept_keyboard_and_save_draft_without_project(self):
        self.assertFalse(self.w.notes.isReadOnly());self.assertTrue(self.w.savenotes.isEnabled())
        QTest.keyClicks(self.w.notes,'Keep the placeholder')
        self.w.savenotes.click()
        self.assertEqual(self.w._manual_notes,'Keep the placeholder')
        self.assertIsNone(self.w.project)
        self.assertIn('phiên này',self.w.status.text())
    def test_switching_modes_keeps_separate_review_and_manual_notes(self):
        self.project();self.w.notes.setPlainText('Review ghi chú cũ')
        self.w.manual_mode.setChecked(True);self.w.source.setPlainText('Hello')
        self.w.notes.setPlainText('Nháp cho câu mới');self.w.savenotes.click()
        self.assertEqual(self.w.project.rows()[0]['notes'],'Review ghi chú cũ')
        self.w.manual_mode.setChecked(False)
        self.assertEqual(self.w.notes.toPlainText(),'Review ghi chú cũ')
        self.w.table.selectRow(1);self.w.notes.setPlainText('Ghi chú câu kế')
        self.w.manual_mode.setChecked(True)
        self.assertEqual(self.w.notes.toPlainText(),'Nháp cho câu mới')
        self.assertEqual(self.w.source.toPlainText(),'Hello')
        rows={r['key']:r for r in self.w.project.rows()}
        self.assertEqual(rows['next']['notes'],'Ghi chú câu kế')
    def test_manual_notes_survive_source_edit_model_failure_and_busy_cycle(self):
        self.project();self.w.manual_mode.setChecked(True);self.w.notes.setPlainText('Cần kiểm tra thuật ngữ')
        self.w.source.setPlainText('New source')
        self.w.worker=object();self.w.busy(True)
        self.assertTrue(self.w.notes.isReadOnly())
        self.w.worker=None;self.w.last_error='Dịch vụ bận';self.w.translation_finished()
        self.assertEqual(self.w.notes.toPlainText(),'Cần kiểm tra thuật ngữ')
        self.assertFalse(self.w.notes.isReadOnly());self.assertTrue(self.w.savenotes.isEnabled())
        self.assertEqual(self.w.project.rows()[0]['notes'],'')
    def test_saving_manual_sentence_attaches_notes_to_new_key_only(self):
        self.project();self.translate_manually();self.w.notes.setPlainText('Cần giữ {name}')
        self.w.save_manual_sentence()
        rows=self.w.project.rows();new=rows[-1]
        self.assertTrue(new['key'].startswith('manual/'))
        self.assertEqual(new['notes'],'Cần giữ {name}');self.assertEqual(rows[0]['notes'],'')
        self.assertFalse(new['reviewed']);self.assertIsNone(new['approved'])
        self.assertEqual(export_training(self.w.project,Path(self.temp.name)/'train.jsonl'),0)
        self.w.manual_mode.setChecked(True);self.assertEqual(self.w.notes.toPlainText(),'')
    def test_first_project_save_captures_notes_before_dialog_changes_selection(self):
        self.translate_manually();self.w.notes.setPlainText('First project note')
        self.w.choose_file=lambda *args:(str(self.path),'')
        self.w.save_manual_sentence()
        row=self.w.project.rows()[0]
        self.assertEqual(row['notes'],'First project note');self.assertEqual(row['english'],'Hello {name}')
    def test_project_manual_draft_restores_after_reopen_without_training_label(self):
        self.project();self.w.manual_mode.setChecked(True);self.w.source.setPlainText('New text')
        self.w.notes.setPlainText('Nháp lưu lâu dài');self.w.close()
        with patch('keyring.get_password',return_value=None):self.w=Window()
        self.w.attach(str(self.path));self.w.manual_mode.setChecked(True)
        self.assertEqual(self.w.notes.toPlainText(),'Nháp lưu lâu dài')
        self.assertEqual(self.w.source.toPlainText(),'New text')
        self.assertEqual(len(self.w.project.rows()),2)
        self.assertTrue(all(not r['reviewed'] and r['approved'] is None for r in self.w.project.rows()))
    def test_cancel_save_keeps_source_notes_and_result(self):
        self.translate_manually();self.w.notes.setPlainText('Do not lose me')
        self.w.choose_file=lambda *args:('','');self.w.save_manual_sentence()
        self.assertEqual(self.w.notes.toPlainText(),'Do not lose me')
        self.assertEqual(self.w.translation.toPlainText(),'Xin chào {name}')
        self.assertTrue(self.w.manual_mode.isChecked())
