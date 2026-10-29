import csv
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from localqa.core import Project, export_rows, export_training

class FeedbackDataTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name)/'project.lqa'
    def tearDown(self): self.tmp.cleanup()
    def project(self):
        p=Project(self.path)
        p.import_rows([{'key':'a','english':'Hello %s','vietnamese':'Xin chào','context':'Welcome'}])
        return p
    def test_v1_migrates_without_losing_feedback(self):
        db=sqlite3.connect(self.path)
        db.executescript("CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT); INSERT INTO meta VALUES('schema','1'); CREATE TABLE rows(key TEXT PRIMARY KEY,english TEXT,vietnamese TEXT,context TEXT DEFAULT '',result TEXT,approved TEXT,reviewed INTEGER DEFAULT 0); INSERT INTO rows(key,english,vietnamese,approved,reviewed) VALUES('a','Save','Lưu','Lưu',1);")
        db.commit();db.close()
        p=Project(self.path);r=p.rows()[0]
        self.assertEqual((r['approved'],r['reviewed'],r['notes']),('Lưu',1,''))
        self.assertEqual(p.setting('schema'),'2');p.close()
    def test_review_is_not_approval_and_notes_survive_reopen(self):
        p=self.project();p.set_reviewed('a',True);p.save_notes('a','Gợi ý còn gượng');p.close()
        p=Project(self.path);r=p.rows()[0]
        self.assertIsNone(r['approved']);self.assertEqual(r['notes'],'Gợi ý còn gượng')
        dest=Path(self.tmp.name)/'train.jsonl'
        self.assertEqual(export_training(p,dest),0);self.assertEqual(dest.read_text(),'');p.close()
    def test_training_uses_approved_target_only_and_uncheck_excludes(self):
        p=self.project();p.save_result('a',{'suggestion':'Wrong suggestion'})
        p.save_feedback('a',True,'Cần giữ tên người dùng','Xin chào %s')
        dest=Path(self.tmp.name)/'train.jsonl';self.assertEqual(export_training(p,dest),1)
        record=json.loads(dest.read_text());self.assertEqual(record['output']['vietnamese'],'Xin chào %s')
        self.assertEqual(record['input']['vietnamese_current'],'Xin chào')
        self.assertTrue(record['metadata']['human_approved'])
        p.set_reviewed('a',False);self.assertEqual(p.rows()[0]['approved'],'Xin chào %s')
        self.assertEqual(export_training(p,dest),0);p.close()
    def test_placeholder_error_does_not_truncate_destination(self):
        p=self.project();p.approve('a','Xin chào');dest=Path(self.tmp.name)/'train.jsonl';dest.write_text('existing')
        with self.assertRaises(ValueError):export_training(p,dest)
        self.assertEqual(dest.read_text(),'existing')
        with self.assertRaises(ValueError):export_training(p,self.path)
        p.close()
    def test_input_changes_clear_feedback_and_backend_results(self):
        p=self.project();p.approve('a','Xin chào %s');p.save_notes('a','Reviewed old wording')
        p.save_backend_result('a','local',{'translation':'A'});p.save_comparison('a',{'winner':'tie'})
        p.import_rows([{'key':'a','english':'Goodbye %s','vietnamese':'Tạm biệt','context':'Exit'}])
        r=p.rows()[0];self.assertEqual((r['reviewed'],r['notes'],r['approved']),(0,'',None));self.assertEqual(p.backend_results('a'),{});p.close()
    def test_backend_update_does_not_change_human_feedback(self):
        p=self.project();p.approve('a','Xin chào %s');p.save_notes('a','Approved manually')
        p.save_backend_result('a','gemini',{'translation':'Chào %s'});p.save_comparison('a',{'winner':'gemini'})
        r=p.rows()[0];self.assertEqual((r['reviewed'],r['notes'],r['approved']),(1,'Approved manually','Xin chào %s'))
        self.assertEqual(p.get_comparison('a')['winner'],'gemini');p.close()
    def test_export_contains_separate_feedback_fields(self):
        p=self.project();p.save_notes('a','Bad suggestion');p.set_reviewed('a',True)
        dest=Path(self.tmp.name)/'report.csv';export_rows(p,dest)
        with dest.open(encoding='utf-8-sig',newline='') as f:r=next(csv.DictReader(f))
        self.assertEqual(r['notes'],'Bad suggestion');self.assertEqual(r['reviewed'],'True');self.assertEqual(r['approved_translation'],'');p.close()

if __name__=='__main__':unittest.main()
