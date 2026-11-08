import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from localqa.app import Window,Worker
from localqa.core import Project,export_training,fingerprint
from localqa.routing import ReviewRouter
from localqa.translation_worker import TranslationWorker

RESULT={'status':'REVIEW','issues':['Bản dịch mới cần duyệt'],'reason':'Giữ nguyên biến đếm.','suggestion':'Lưu {count} mục','model_used':'backup','used_fallback':True}
class DirectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'p.lqa'
        with patch('keyring.get_password',return_value=None):self.w=Window()
        self.errors=[];self.w.error=self.errors.append
    def tearDown(self):self.w.close();self.tmp.cleanup()
    def project(self):
        p=Project(self.path);p.import_rows([{'key':'a','english':'Save {count} items','vietnamese':'Lưu {count} mục'}]);p.close();self.w.attach(str(self.path))
    def ready(self):
        row={'key':'direct','english':'Save {count} items','vietnamese':'','context':''}
        self.w._translation_request=(True,row);self.w.translation_ready(dict(RESULT));self.w.refresh_controls()
    def test_direct_without_project_and_no_auto_approval(self):
        self.w.manual_mode.setChecked(True);self.w.source.setPlainText('Save {count} items');self.ready()
        self.assertFalse(self.w.source.isReadOnly());self.assertEqual(self.w.current.toPlainText(),'Lưu {count} mục')
        self.assertTrue(self.w.save_sentence.isEnabled());self.assertIsNone(self.w.project)
        self.assertFalse(self.w.approvebutton.isEnabled())
    def test_edit_source_invalidates_previous_result(self):
        self.w.manual_mode.setChecked(True);self.w.source.setPlainText('Save {count} items');self.ready()
        self.w.source.setPlainText('Cancel');self.assertIsNone(self.w._manual_result)
        self.assertFalse(self.w.save_sentence.isEnabled());self.assertEqual(self.w.translation.toPlainText(),'')
    def test_manual_does_not_modify_selected_source(self):
        self.project();self.w.manual_mode.setChecked(True);self.w.source.setPlainText('Different');self.w.translation.setPlainText('Khác')
        self.w.manual_mode.setChecked(False);self.assertEqual(self.w.source.toPlainText(),'Save {count} items')
        self.assertEqual(self.w.project.rows()[0]['english'],'Save {count} items')
    def test_save_creates_pending_new_row_without_overwriting_existing(self):
        self.project();self.w.manual_mode.setChecked(True);self.w.source.setPlainText('Save {count} items');self.ready();self.w.save_manual_sentence()
        rows=self.w.project.rows();self.assertEqual(len(rows),2);self.assertFalse(rows[-1]['reviewed']);self.assertIsNone(rows[-1]['approved'])
        self.assertEqual(json.loads(rows[-1]['result'])['suggestion'],'Lưu {count} mục')
        self.assertEqual(export_training(self.w.project,Path(self.tmp.name)/'t.jsonl'),0)
    def test_cancel_save_keeps_direct_input(self):
        self.w.manual_mode.setChecked(True);self.w.source.setPlainText('Save {count} items');self.ready()
        self.w.choose_file=lambda *a:('','');self.w.save_manual_sentence()
        self.assertTrue(self.w.manual_mode.isChecked());self.assertEqual(self.w.translation.toPlainText(),'Lưu {count} mục')
    def test_selected_translation_is_draft_and_keeps_original_approval(self):
        self.project();self.w.project.approve('a','Lưu {count} mục')
        self.w._translation_request=(False,self.w.project.rows()[0]);self.w.translation_ready(dict(RESULT));self.w.refresh()
        self.assertEqual(self.w.project.rows()[0]['approved'],'Lưu {count} mục')
        self.assertEqual(self.w.project.backend_results('a')['gemini']['model_used'],'backup')
    def test_worker_uses_translation_not_review_for_empty_target(self):
        p=Project(self.path);p.import_rows([{'key':'a','english':'Save {count} items','vietnamese':''}]);p.close()
        with patch('localqa.gemini.Gemini') as client:
            client.return_value.translate.return_value={k:RESULT[k] for k in ('status','issues','reason','suggestion')}
            worker=Worker(str(self.path),'fake','model','',False);errors=[];worker.failed.connect(errors.append);worker.run()
            client.return_value.review.assert_not_called();client.return_value.translate.assert_called_once()
        self.assertFalse(errors);p=Project(self.path);row=p.rows()[0];result=json.loads(row['result']);p.close()
        self.assertEqual(result['task'],'translate');self.assertEqual(result['status'],'REVIEW');self.assertFalse(row['reviewed'])
    def test_no_key_or_blank_source_never_starts_worker(self):
        self.w.manual_mode.setChecked(True);self.w.translate_source();self.w.source.setPlainText('Hello');self.w.translate_source()
        self.assertEqual(len(self.errors),2);self.assertIsNone(self.w.worker)
    def test_single_worker_emits_result_without_writing_source(self):
        self.project();row=self.w.project.rows()[0]
        with patch('localqa.gemini.Gemini') as client:
            client.return_value.translate.return_value={k:RESULT[k] for k in ('status','issues','reason','suggestion')}
            worker=TranslationWorker(str(self.path),row,'fake','model',[],'');ready=[];worker.ready.connect(ready.append);worker.run()
        self.assertEqual(len(ready),1);self.assertIsNone(self.w.project.rows()[0]['result'])
    def test_excel_dispatch_imports_source_only_without_api(self):
        from openpyxl import Workbook
        path=Path(self.tmp.name)/'input.xlsx';book=Workbook();book.active.append(['english']);book.active.append(['Save {count} items']);book.save(path);book.close()
        self.project()
        with patch('localqa.gemini.Gemini') as client:self.w.import_selected_paths([str(path)])
        client.assert_not_called();self.assertEqual(self.w.project.rows()[-1]['vietnamese'],'')
    def test_task_cache_is_separate(self):
        from unittest.mock import Mock
        import threading
        self.project();p=self.w.project;row=p.rows()[0]
        p.cache(fingerprint(row,'model',''),{'status':'PASS','issues':[],'reason':'QA','suggestion':''})
        client=Mock();client.translate.return_value={k:RESULT[k] for k in ('status','issues','reason','suggestion')}
        router=ReviewRouter(client,p,['model'],'',threading.Event(),lambda x:None)
        self.assertEqual(router.review(row,task='translate')['task'],'translate');client.translate.assert_called_once()
