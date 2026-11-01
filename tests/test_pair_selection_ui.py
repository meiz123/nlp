import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QFileDialog
from localqa.app import Window
from localqa.core import Project


class PairSelectionUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.path=self.root/'project.lqa';p=Project(self.path)
        p.import_rows([{'key':'existing','english':'Save','vietnamese':'Lưu'}]);p.close()
        with patch('keyring.get_password',return_value=''):
            self.window=Window()
        self.window.attach(str(self.path));self.errors=[];self.window.error=self.errors.append

    def tearDown(self):
        self.window.close();self.tmp.cleanup()

    def make_pair(self,names=('data_home_en.json','data_home_vi.json')):
        paths=[self.root/name for name in names]
        for path,text in zip(paths,['Hello','Xin chào']):path.write_text(json.dumps({'hello':text}),encoding='utf-8')
        return paths

    def test_main_button_imports_reversed_selection_correctly(self):
        en,vi=self.make_pair();self.window.choose_files=lambda *a:[str(vi),str(en)]
        self.window.import_csv();rows={r['key']:r for r in self.window.project.rows()}
        self.assertFalse(self.errors);self.assertEqual(rows['hello']['english'],'Hello')
        self.assertEqual(rows['hello']['vietnamese'],'Xin chào');self.assertEqual(rows['hello']['reviewed'],0)
        self.assertIn('data_home_en.json + data_home_vi.json',self.window.status.text())
        self.assertIsNone(self.window.actions[2].menu())

    def test_single_language_file_requests_user_selected_counterpart(self):
        en,vi=self.make_pair();self.window.choose_files=lambda *a:[str(vi)]
        with patch.object(self.window,'choose_file',return_value=(str(en),'')) as picker:
            self.window.import_csv()
        self.assertTrue(picker.called);self.assertFalse(self.errors)
        self.assertEqual(self.window.project.rows()[-1]['english'],'Hello')

    def test_counterpart_cancel_keeps_project_and_note_draft(self):
        en,vi=self.make_pair();self.window.notes.setPlainText('Keep draft')
        self.window.choose_files=lambda *a:[str(en)]
        with patch.object(self.window,'choose_file',return_value=('','')):
            self.window.import_csv()
        self.assertEqual(len(self.window.project.rows()),1)
        self.assertEqual(self.window.project.rows()[0]['notes'],'')
        self.assertEqual(self.window.notes.toPlainText(),'Keep draft');self.assertFalse(self.errors)

    def test_ambiguous_names_require_explicit_source_selection(self):
        en,vi=self.make_pair(('first.json','second.json'))
        self.window.choose_files=lambda *a:[str(vi),str(en)]
        with patch('localqa.app.QInputDialog.getItem',return_value=(str(en),True)) as chooser:
            self.window.import_csv()
        self.assertTrue(chooser.called);self.assertFalse(self.errors)
        self.assertEqual(self.window.project.rows()[-1]['english'],'Hello')

    def test_ambiguous_cancel_keeps_project(self):
        en,vi=self.make_pair(('first.json','second.json'))
        self.window.choose_files=lambda *a:[str(en),str(vi)]
        with patch('localqa.app.QInputDialog.getItem',return_value=('',False)):
            self.window.import_csv()
        self.assertEqual(len(self.window.project.rows()),1);self.assertFalse(self.errors)

    def test_invalid_multi_selection_never_changes_project(self):
        en,vi=self.make_pair()
        for paths in [[str(en),str(en)], [str(en),'file.csv'], [str(en),str(vi),'third.json']]:
            self.window.choose_files=lambda *a,paths=paths:paths
            self.window.import_csv()
        self.assertEqual(len(self.errors),3);self.assertEqual(len(self.window.project.rows()),1)

    def test_malformed_bilingual_json_does_not_offer_counterpart(self):
        path=self.root/'broken.json';path.write_text(json.dumps({'translations':[{'key':'x','english':5,'vietnamese':'x'}]}))
        self.window.choose_files=lambda *a:[str(path)]
        with patch.object(self.window,'choose_file') as picker:
            self.window.import_csv()
        self.assertFalse(picker.called);self.assertEqual(len(self.errors),1)
        self.assertEqual(len(self.window.project.rows()),1)

    def test_multi_file_picker_supports_existing_files(self):
        en,vi=self.make_pair()
        def accept():
            dialog=self.window.file_dialogs[-1]
            self.assertEqual(dialog.fileMode(),QFileDialog.FileMode.ExistingFiles)
            dialog.selectFile(str(en));dialog.accept()
        QTimer.singleShot(0,accept)
        files=self.window.choose_files('Data','JSON (*.json)')
        self.assertEqual(len(files),1);self.assertTrue(Path(files[0]).samefile(en))


if __name__=='__main__':unittest.main()
