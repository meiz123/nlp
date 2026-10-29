import os,tempfile,unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
from PySide6.QtWidgets import QApplication
from localqa.app import Window,Worker
from localqa.core import Project
class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def test_offline_and_review(self):
        with tempfile.TemporaryDirectory() as d:
            path=str(Path(d)/'test.lqa');p=Project(path);p.import_rows([{'key':'welcome','english':'Hi %s','vietnamese':'Chào'}]);p.close()
            worker=Worker(path,'','','',True);errors=[];worker.failed.connect(errors.append);worker.run();self.assertEqual(errors,[])
            w=Window();w.attach(path);self.assertEqual(w.table.rowCount(),1);w.table.selectRow(0);w.translation.setPlainText('Chào %s');w.approve();self.assertEqual(w.project.rows()[0]['approved'],'Chào %s');w.close()

class ReviewWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def test_filters_and_placeholder_guard(self):
        with tempfile.TemporaryDirectory() as d:
            path=str(Path(d)/'test.lqa');p=Project(path)
            p.import_rows([{'key':'bad','english':'Hello %s','vietnamese':'Chào'},{'key':'good','english':'Save','vietnamese':'Lưu'}])
            p.save_result('bad',{'status':'FAIL','issues':['missing placeholder'],'reason':'','suggestion':'Chào %s'});p.close()
            w=Window();w.attach(path);w.filter.setCurrentIndex(2)
            self.assertFalse(w.table.isRowHidden(0));self.assertTrue(w.table.isRowHidden(1))
            w.translation.setPlainText('Chào');errors=[];w.error=errors.append;w.approve()
            self.assertEqual(len(errors),1);self.assertEqual(w.project.rows()[0]['reviewed'],0)
            w.translation.setPlainText('Chào %s');w.approve();self.assertEqual(w.project.rows()[0]['reviewed'],1)
            w.filter.setCurrentIndex(0);w.search.setText('save');self.assertTrue(w.table.isRowHidden(0));self.assertFalse(w.table.isRowHidden(1));w.close()
    def test_cached_ai_preserves_technical_failures(self):
        from unittest.mock import patch
        from localqa.core import fingerprint
        with tempfile.TemporaryDirectory() as d:
            path=str(Path(d)/'test.lqa');p=Project(path);p.import_rows([{'key':'a','english':'Hi %s','vietnamese':'Chào'}]);row=p.rows()[0]
            p.cache(fingerprint(row,'model',''),{'status':'PASS','issues':[],'reason':'','suggestion':''});p.close()
            with patch('localqa.gemini.Gemini') as mock:
                worker=Worker(path,'test','model','',False);worker.run();mock.return_value.review.assert_not_called()
            p=Project(path);import json
            self.assertEqual(json.loads(p.rows()[0]['result'])['status'],'FAIL');p.close()
