import os,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication
from localqa.app import Window
from localqa.core import Project
class OpenDataTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
  with patch('keyring.get_password',return_value=''):self.window=Window()
  self.errors=[];self.window.error=self.errors.append
 def tearDown(self):self.window.close();self.temp.cleanup()
 def pair(self):
  en=self.root/'data_home_en.json';vi=self.root/'data_home_vi.json'
  en.write_text(json.dumps({'save':'Save'}),encoding='utf-8');vi.write_text(json.dumps({'save':'Lưu'}),encoding='utf-8');return en,vi
 def test_open_pair_without_existing_project(self):
  en,vi=self.pair();dest=self.root/'review.lqa'
  self.window.choose_files=lambda *a:[str(vi),str(en)];self.window.choose_file=lambda *a:(str(dest),'')
  self.window.open();self.assertFalse(self.errors);self.assertEqual(self.window.project.rows()[0]['vietnamese'],'Lưu');self.assertTrue(dest.exists())
 def test_cancel_save_preserves_existing_project(self):
  en,vi=self.pair();old=self.root/'old.lqa';p=Project(old);p.import_rows([{'key':'old','english':'Old','vietnamese':'Cũ'}]);p.close();self.window.attach(str(old))
  self.window.choose_files=lambda *a:[str(en),str(vi)];self.window.choose_file=lambda *a:('','')
  self.window.open();self.assertEqual(self.window.project.rows()[0]['key'],'old');self.assertFalse(self.errors)
 def test_mixed_project_and_source_rejected(self):
  en,vi=self.pair();self.window.choose_files=lambda *a:[str(en),str(self.root/'project.lqa')]
  self.window.open();self.assertEqual(len(self.errors),1);self.assertIsNone(self.window.project)
 def test_open_saved_project(self):
  dest=self.root/'saved.lqa';Project(dest).close();self.window.choose_files=lambda *a:[str(dest)]
  self.window.open();self.assertFalse(self.errors);self.assertEqual(Path(self.window.project.path),dest)
 def test_bad_input_does_not_prompt_save(self):
  bad=self.root/'bad.json';bad.write_text('{',encoding='utf-8');self.window.choose_files=lambda *a:[str(bad)]
  with patch.object(self.window,'choose_file') as save:self.window.open()
  self.assertFalse(save.called);self.assertEqual(len(self.errors),1);self.assertIsNone(self.window.project)
 def test_existing_destination_is_not_merged(self):
  en,vi=self.pair();dest=self.root/'existing.lqa';Project(dest).close()
  self.window.choose_files=lambda *a:[str(en),str(vi)];self.window.choose_file=lambda *a:(str(dest),'')
  self.window.open();self.assertEqual(len(self.errors),1);self.assertIsNone(self.window.project)
