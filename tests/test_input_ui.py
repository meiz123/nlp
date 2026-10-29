import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication
from localqa.app import Window
from localqa.core import Project


class InputUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.path=self.root/'project.lqa';p=Project(self.path)
        p.import_rows([{'key':'existing','english':'Save','vietnamese':'Lưu'}]);p.close()
        with patch('keyring.get_password',return_value=''):
            self.window=Window()
        self.window.attach(str(self.path));self.errors=[];self.window.error=self.errors.append

    def tearDown(self):
        self.window.close();self.temp.cleanup()

    def choose(self,path):
        self.window.choose_file=lambda *args:(str(path),'')

    def test_json_dispatch_preserves_existing_rows_and_no_review(self):
        path=self.root/'translations.json';path.write_text(json.dumps([
            {'key':'hello','english':'Hello %s','vietnamese':'Xin chào %s','context':'Greeting'}
        ]),encoding='utf-8')
        self.choose(path);self.window.import_csv()
        self.assertFalse(self.errors)
        rows={r['key']:r for r in self.window.project.rows()}
        self.assertEqual(set(rows),{'existing','hello'})
        self.assertEqual(rows['hello']['reviewed'],0);self.assertIsNone(rows['hello']['approved'])
        self.assertEqual(rows['hello']['context'],'Greeting')
        self.assertEqual(self.window.actions[2].text(),'Nhập dữ liệu')
        self.assertEqual(len(self.window.actions[2].menu().actions()),2)

    def test_parse_error_does_not_flush_notes_or_mutate_project(self):
        self.window.notes.setPlainText('Unsaved human note')
        path=self.root/'bad.json';path.write_text('{bad',encoding='utf-8')
        self.choose(path);self.window.import_csv()
        self.assertEqual(len(self.errors),1)
        rows=self.window.project.rows();self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['notes'],'')
        self.assertEqual(self.window.notes.toPlainText(),'Unsaved human note')

    def test_warning_can_cancel_without_mutation(self):
        path=self.root/'missing.json';path.write_text(json.dumps({'en':{'new':'New'},'vi':{}}))
        self.choose(path)
        with patch.object(self.window,'confirm_input_report',return_value=False) as confirm:
            self.window.import_csv()
        self.assertTrue(confirm.call_args.args[1]['diagnostics'])
        self.assertEqual([r['key'] for r in self.window.project.rows()],['existing'])
        self.assertFalse(self.errors)

    def test_explicit_json_pair_uses_english_then_vietnamese(self):
        english=self.root/'en.json';vietnamese=self.root/'vi.json'
        english.write_text(json.dumps({'greeting':'Hi'}));vietnamese.write_text(json.dumps({'greeting':'Chào'}))
        choices=iter([(str(english),''),(str(vietnamese),'')]);self.window.choose_file=lambda *args:next(choices)
        self.window.import_json_pair()
        rows={r['key']:r for r in self.window.project.rows()}
        self.assertEqual(rows['greeting']['english'],'Hi');self.assertEqual(rows['greeting']['vietnamese'],'Chào')
        self.assertFalse(self.errors)

    def test_json_pair_cancel_does_not_write(self):
        choices=iter([('english.json',''),('','')]);self.window.choose_file=lambda *args:next(choices)
        self.window.import_json_pair()
        self.assertEqual(len(self.window.project.rows()),1);self.assertFalse(self.errors)

    def test_word_dispatch_imports_validated_rows(self):
        path=self.root/'translations.DOCX';self.choose(path)
        rows=[{'key':'word','english':'Open','vietnamese':'Mở','context':'Button'}]
        with patch('localqa.input_word.load_word',return_value=rows) as reader:
            self.window.import_csv()
        reader.assert_called_once_with(str(path))
        self.assertEqual(self.window.project.rows()[-1]['key'],'word')
        self.assertFalse(self.errors)

    def test_legacy_doc_error_keeps_project_and_feedback(self):
        self.window.notes.setPlainText('Keep this draft')
        path=self.root/'translations.doc';self.choose(path)
        with patch('localqa.input_word.load_word',side_effect=ValueError('Lưu thành .docx để nhập')):
            self.window.import_csv()
        self.assertEqual(len(self.window.project.rows()),1)
        self.assertEqual(self.window.notes.toPlainText(),'Keep this draft')
        self.assertIn('.docx',str(self.errors[0]))

    def test_busy_input_does_not_open_file_picker(self):
        self.window.worker=object()
        with patch.object(self.window,'choose_file') as picker:
            self.window.import_csv();self.window.import_json_pair()
        self.assertFalse(picker.called);self.window.worker=None
