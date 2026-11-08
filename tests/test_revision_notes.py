import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import json,tempfile,threading,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from PySide6.QtWidgets import QApplication
from localqa.app import Window
from localqa.core import Project,export_training
from localqa.gemini import Gemini
from localqa.routing import ReviewRouter,task_cache_key,ModelsUnavailable
RESULT={'status':'REVIEW','issues':['Đã sửa cách diễn đạt'],'reason':'Bớt cấu trúc sát chữ.','suggestion':'Xin chào {name}'}
ROW={'key':'a','english':'Hello {name}','vietnamese':'Chào {name}','context':'Greeting','revision_notes':'Tự nhiên hơn'}
class RevisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'p.lqa'
        with patch('keyring.get_password',return_value=None):self.w=Window()
        self.errors=[];self.w.error=self.errors.append
    def tearDown(self):self.w.close();self.tmp.cleanup()
    def test_revision_cache_depends_on_notes_target_context_and_task(self):
        key=task_cache_key(ROW,'m','c','revise')
        for field,value in [('revision_notes','Khác'),('vietnamese','Xin chào {name}'),('context','Button')]:
            self.assertNotEqual(key,task_cache_key({**ROW,field:value},'m','c','revise'))
        self.assertNotEqual(key,task_cache_key(ROW,'m','c','translate'))
    @patch('localqa.gemini.genai.Client')
    def test_adapter_sends_source_translation_notes_as_data(self,client):
        client.return_value.models.generate_content.return_value=SimpleNamespace(text=json.dumps(RESULT))
        adapter=Gemini('fake');self.assertEqual(adapter.revise(ROW,'m','c'),RESULT)
        payload=json.loads(client.return_value.models.generate_content.call_args.kwargs['contents'])
        self.assertEqual(payload['review_notes'],ROW['revision_notes']);self.assertEqual(payload['current_translation'],ROW['vietnamese']);self.assertEqual(payload['english'],ROW['english']);adapter.close()
    def test_bad_placeholder_uses_fallback_for_revision(self):
        p=Project(self.path);client=Mock();client.revise.side_effect=[{**RESULT,'suggestion':'Xin chào'},RESULT]
        router=ReviewRouter(client,p,['a','b'],'',threading.Event(),lambda x:None)
        self.assertEqual(router.review(ROW,task='revise')['model_used'],'b');p.close()
    def test_button_requires_notes_and_current_translation(self):
        self.w.key.setText('fake');self.w.source.setPlainText(ROW['english']);self.w.revisebutton.click()
        self.assertIn('ghi chú',self.errors[-1]);self.w.notes.setPlainText('Tự nhiên hơn');self.w.revisebutton.click()
        self.assertIn('bản dịch hiện tại',self.errors[-1]);self.assertIsNone(self.w.worker)
    def test_manual_revision_keeps_before_and_after_without_approval(self):
        self.w.source.setPlainText(ROW['english']);self.w.notes.setPlainText(ROW['revision_notes'])
        self.w._translation_request=(True,dict(ROW));self.w.translation_ready({**RESULT,'task':'revise','model_used':'m'})
        self.assertEqual(self.w.current.toPlainText(),ROW['vietnamese']);self.assertEqual(self.w.translation.toPlainText(),RESULT['suggestion'])
        self.assertEqual(self.w.before_revision.toPlainText(),ROW['vietnamese']);self.assertEqual(self.w.reviewtabs.currentIndex(),2)
        self.assertIsNone(self.w.project);self.assertEqual(self.w.notes.toPlainText(),ROW['revision_notes'])
    def test_project_revision_draft_survives_refresh_and_keeps_approval(self):
        p=Project(self.path);p.import_rows([ROW]);p.approve('a','Chào {name}');p.close();self.w.attach(str(self.path))
        request={**ROW,'vietnamese':'Bản đang sửa {name}'};self.w._translation_request=(False,request)
        self.w.translation_ready({**RESULT,'task':'revise','model_used':'m'});self.w.refresh()
        self.assertEqual(self.w.translation.toPlainText(),RESULT['suggestion'])
        self.assertEqual(self.w.project.rows()[0]['approved'],'Chào {name}')
        history=self.w.project.backend_results('a')['gemini']['revisions'];self.assertEqual(history[0]['notes'],ROW['revision_notes'])
        self.assertEqual(history[0]['before'],'Bản đang sửa {name}')
    def test_click_routes_explicit_notes_only_to_revise_worker(self):
        self.w.key.setText('fake');self.w.source.setPlainText(ROW['english']);self.w.notes.setPlainText(ROW['revision_notes']);self.w.translation.setPlainText(ROW['vietnamese'])
        with patch('localqa.app.TranslationWorker') as cls:
            cls.return_value.stop=threading.Event();cls.return_value.isRunning.return_value=False
            self.w.revisebutton.click();args=cls.call_args
            self.assertEqual(args.kwargs['task'],'revise');self.assertEqual(args.args[1]['revision_notes'],ROW['revision_notes']);self.assertEqual(args.args[1]['vietnamese'],ROW['vietnamese'])
        self.w.worker=None;self.w.busy(False)
