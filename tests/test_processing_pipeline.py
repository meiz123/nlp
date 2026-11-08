"""Regression coverage for reusable results and safe model failover."""
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock
from localqa.core import Project
from localqa.routing import ReviewRouter, ReviewCancelled, task_cache_key

PASS = {'status':'PASS','issues':[],'reason':'Đúng nghĩa.','suggestion':''}
TRANSLATION = {'status':'REVIEW','issues':['Cần người dùng duyệt'],'reason':'Giữ đúng biến.','suggestion':'Lưu {count} mục'}

class ServiceError(Exception):
    def __init__(self, code):self.code=code

class ProcessingPipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.project=Project(Path(self.temp.name)/'project.lqa')
        self.project.import_rows([{'key':'a','english':'Save {count} items','vietnamese':'Lưu {count} mục','context':'Button'}])
        self.row=self.project.rows()[0];self.client=Mock();self.stop=threading.Event()
        self.router=ReviewRouter(self.client,self.project,['primary','backup'],'App context',self.stop,lambda _:None)
    def tearDown(self):self.project.close();self.temp.cleanup()
    def cache(self,result,model='primary',task='review',row=None):
        self.project.cache(task_cache_key(row or self.row,model,'App context',task),result)
    def test_translation_cache_ignores_only_existing_target(self):
        self.cache(TRANSLATION,task='translate')
        changed={**self.row,'vietnamese':'Một bản sửa khác'}
        result=self.router.review(changed,task='translate')
        self.assertTrue(result['cache_hit']);self.assertEqual(result['suggestion'],TRANSLATION['suggestion'])
        self.client.translate.assert_not_called();self.assertEqual(self.router.request_count,0)
        self.assertNotEqual(task_cache_key(changed,'primary','App context','review'),task_cache_key(self.row,'primary','App context','review'))
        self.assertNotEqual(task_cache_key(self.row,'primary','Changed context','translate'),task_cache_key(self.row,'primary','App context','translate'))
        self.assertNotEqual(task_cache_key({**self.row,'english':'Cancel'},'primary','App context','translate'),task_cache_key(self.row,'primary','App context','translate'))
    def test_backup_cache_avoids_primary_api_call(self):
        self.cache(PASS,model='backup');result=self.router.review(self.row)
        self.assertEqual(result['model_used'],'backup');self.assertTrue(result['used_fallback']);self.assertTrue(result['cache_hit'])
        self.client.review.assert_not_called()
    def test_cached_output_of_unavailable_model_is_still_usable(self):
        self.cache(PASS,model='primary');self.router.unavailable.add('primary')
        self.assertEqual(self.router.review(self.row)['model_used'],'primary');self.client.review.assert_not_called()
    def test_invalid_cached_schema_and_placeholder_are_not_used(self):
        for invalid in ({'status':'PASS'}, {**TRANSLATION,'suggestion':'Lưu mục'}):
            with self.subTest(invalid=invalid):
                self.cache(invalid);self.client.review.return_value=PASS
                result=self.router.review(self.row)
                self.assertFalse(result['cache_hit']);self.assertEqual(result['status'],'PASS')
                self.assertEqual(self.project.cached(task_cache_key(self.row,'primary','App context','review')),PASS)
    def test_invalid_primary_cache_can_use_valid_backup_without_api(self):
        self.cache({'status':'PASS'});self.cache(PASS,model='backup')
        self.assertTrue(self.router.review(self.row)['cache_hit']);self.client.review.assert_not_called()
    def test_bad_answer_does_not_blacklist_model_for_other_rows(self):
        self.client.review.side_effect=[{'status':'PASS'},PASS,ServiceError(429),PASS]
        self.assertEqual(self.router.review(self.row)['model_used'],'backup')
        self.assertNotIn('primary',self.router.unavailable)
        nextrow={**self.row,'english':'Show {count} items'}
        self.assertEqual(self.router.review(nextrow)['model_used'],'primary')
        self.assertEqual(self.router.request_count,4)
    def test_cancel_before_cached_lookup_does_not_return_result(self):
        self.cache(PASS);self.stop.set()
        with self.assertRaises(ReviewCancelled):self.router.review(self.row)
        self.client.review.assert_not_called()
    def test_routing_never_changes_review_or_approval(self):
        self.project.approve('a','Lưu {count} mục');before=self.project.rows()[0]
        self.client.translate.return_value=TRANSLATION;self.router.review(self.row,task='translate')
        after=self.project.rows()[0]
        self.assertEqual(before,after)
    def test_review_cache_cannot_satisfy_translation(self):
        self.cache(PASS);self.client.translate.return_value=TRANSLATION
        self.assertEqual(self.router.review(self.row,task='translate')['task'],'translate')
        self.client.translate.assert_called_once()
