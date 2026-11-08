import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import json,tempfile,threading,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from localqa.app import Worker,Window
from localqa.core import Project,fingerprint
PASS={'status':'PASS','issues':[],'reason':'Đúng nghĩa.','suggestion':''}
class CountingStop(threading.Event):
    def __init__(self):super().__init__();self.waits=[]
    def wait(self,timeout=None):self.waits.append(timeout);return self.is_set()
class PipelineWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def test_batch_cache_has_no_pacing_delay_or_api_calls(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Project(Path(temp)/'p.lqa');p.import_rows([{'key':str(i),'english':f'Save {i}','vietnamese':f'Lưu {i}'} for i in range(3)])
            for row in p.rows():p.cache(fingerprint(row,'model',''),PASS)
            path=p.path;p.close();worker=Worker(path,'fake','model','',False);worker.stop=CountingStop();errors=[];worker.failed.connect(errors.append)
            with patch('localqa.gemini.Gemini') as adapter:worker.run();adapter.return_value.review.assert_not_called()
            self.assertFalse(errors);self.assertEqual(worker.stop.waits,[])
            p=Project(path);self.assertTrue(all(json.loads(r['result'])['cache_hit'] for r in p.rows()));p.close()
    def test_fresh_requests_keep_pacing_and_reviewed_rows_are_skipped(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Project(Path(temp)/'p.lqa');p.import_rows([{'key':str(i),'english':f'Save {i}','vietnamese':f'Lưu {i}'} for i in range(3)])
            p.approve('2','Lưu 2');path=p.path;p.close();worker=Worker(path,'fake','model','',False);worker.stop=CountingStop()
            with patch('localqa.gemini.Gemini') as adapter:
                adapter.return_value.review.return_value=PASS;worker.run();self.assertEqual(adapter.return_value.review.call_count,2)
            self.assertEqual(worker.stop.waits,[5]);p=Project(path);self.assertEqual(p.rows()[-1]['approved'],'Lưu 2');p.close()
    def test_cancelled_translation_does_not_claim_new_result_and_keeps_notes(self):
        with patch('keyring.get_password',return_value=None):w=Window()
        w.source.setPlainText('Hello');w.notes.setPlainText('Cần giọng thân thiện')
        stop=threading.Event();stop.set();w.worker=SimpleNamespace(stop=stop);w._translation_received=False
        w.translation_finished();self.assertIn('Đã dừng dịch',w.status.text());self.assertEqual(w.notes.toPlainText(),'Cần giọng thân thiện');self.assertFalse(w.notes.isReadOnly());w.close()
