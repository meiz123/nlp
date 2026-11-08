import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from localqa.core import Project, fingerprint, export_rows, export_training
from localqa.routing import ReviewRouter, ModelsUnavailable, ReviewCancelled, model_chain

PASS = {'status':'PASS','issues':[],'reason':'Giữ đúng nghĩa.','suggestion':''}
class ServiceError(Exception):
    def __init__(self, code):self.code=code
class NoWait(threading.Event):
    def wait(self, timeout=None):return self.is_set()

class FallbackTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.p=Project(Path(self.tmp.name)/'p.lqa')
        self.p.import_rows([{'key':'a','english':'Save {count}','vietnamese':'Lưu {count}'}]);self.row=self.p.rows()[0]
        self.client=Mock();self.stop=NoWait();self.messages=[]
        self.router=ReviewRouter(self.client,self.p,['primary','backup'],'context',self.stop,self.messages.append)
    def tearDown(self):self.p.close();self.tmp.cleanup()
    def test_quota_switches_and_stays_on_backup(self):
        self.client.review.side_effect=[ServiceError(429),dict(PASS)]
        result=self.router.review(self.row);self.assertEqual(result['model_used'],'backup');self.assertTrue(result['used_fallback'])
        self.assertEqual([c.args[1] for c in self.client.review.call_args_list],['primary','backup'])
        self.assertEqual(self.router.review(self.row)['model_used'],'backup');self.assertEqual(self.client.review.call_count,2)
        self.assertFalse(self.p.rows()[0]['reviewed']);self.assertIsNone(self.p.rows()[0]['approved'])
    def test_credentials_do_not_trigger_failover(self):
        for code in (400,401,403):
            with self.subTest(code=code):
                self.client.review.reset_mock();self.client.review.side_effect=ServiceError(code)
                with self.assertRaises(ServiceError):self.router.review(self.row)
                self.assertEqual(self.client.review.call_count,1)
    def test_wrong_placeholder_falls_back_without_caching_invalid_output(self):
        bad={'status':'REVIEW','issues':['Chưa tự nhiên'],'reason':'Cần sửa','suggestion':'Lưu'}
        self.client.review.side_effect=[bad,dict(PASS)]
        self.assertEqual(self.router.review(self.row)['model_used'],'backup')
        self.assertIsNone(self.p.cached(fingerprint(self.row,'primary','context')))
    def test_invalid_schema_falls_back(self):
        self.client.review.side_effect=[{'status':'PASS'},dict(PASS)]
        self.assertEqual(self.router.review(self.row)['model_used'],'backup')
    def test_exhaustion_is_bounded_and_leaves_row_pending(self):
        self.client.review.side_effect=ServiceError(429)
        with self.assertRaises(ModelsUnavailable):self.router.review(self.row)
        self.assertEqual(self.client.review.call_count,4)
        self.assertIsNone(self.p.rows()[0]['result'])
    def test_cancel_during_call_does_not_cache_or_save(self):
        def reply(*args):self.stop.set();return dict(PASS)
        self.client.review.side_effect=reply
        with self.assertRaises(ReviewCancelled):self.router.review(self.row)
        self.assertIsNone(self.p.cached(fingerprint(self.row,'primary','context')))
    def test_cache_does_not_cross_model_or_context(self):
        self.p.cache(fingerprint(self.row,'backup','context'),dict(PASS))
        self.client.review.side_effect=ServiceError(404)
        self.assertEqual(self.router.review(self.row)['model_used'],'backup')
        self.assertEqual(self.client.review.call_count,0)
        other=ReviewRouter(self.client,self.p,['backup'],'different',self.stop,self.messages.append)
        with self.assertRaises(ModelsUnavailable):other.review(self.row)
    def test_chain_deduplicates_and_limits(self):
        self.assertEqual(model_chain('a','a, b; b\nc'),['a','b','c'])
        with self.assertRaises(ValueError):model_chain('a','b,c,d,e')
    def test_worker_saves_origin_and_export_without_approval(self):
        from localqa.app import Worker
        with patch('localqa.gemini.Gemini') as cls:
            cls.return_value.review.side_effect=[ServiceError(429),dict(PASS)]
            worker=Worker(str(self.p.path),'fake','primary','context',False,'backup');errors=[]
            worker.failed.connect(errors.append);worker.run()
        self.assertEqual(errors,[])
        result=json.loads(self.p.rows()[0]['result']);self.assertEqual(result['model_used'],'backup')
        target=Path(self.tmp.name)/'train.jsonl';self.assertEqual(export_training(self.p,target),0)
        report=Path(self.tmp.name)/'report.csv';export_rows(self.p,report)
        self.assertIn('model_used',report.read_text(encoding='utf-8-sig'))

    def test_ui_persists_fallbacks_and_shows_provenance(self):
        import os
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication
        from localqa.app import Window
        app=QApplication.instance() or QApplication([])
        with patch('keyring.get_password',return_value=None):
            w=Window();w.attach(str(self.p.path));w.fallback_models.setText('backup, third')
            self.p.save_result('a',{**PASS,'model_used':'backup','used_fallback':True})
            w.refresh();w.table.selectRow(0);w.select()
            self.assertIn('backup (dự phòng)',w.detail.toPlainText());w.close()
            w=Window();w.attach(str(self.p.path));self.assertEqual(w.fallback_models.text(),'backup, third');w.close()
