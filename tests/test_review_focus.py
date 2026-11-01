"""The sentence being reviewed and its actions fit a laptop viewport."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication, QScrollArea
from localqa.app import Window
from localqa.core import Project

class ReviewFocusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.path=Path(self.temp.name)/'focus.lqa'
        project=Project(self.path)
        project.import_rows([{'key':f'/tutorials/@id=tutorial-{i}/description','english':f'Fold corner {i} toward the center.','vietnamese':f'Gấp góc {i} vào giữa.'} for i in range(30)])
        project.close()
        with patch('keyring.get_password',return_value='test'):self.window=Window()
        self.window.attach(str(self.path));self.window.settings.hide();self.window.show()
    def tearDown(self):
        self.window.close();self.temp.cleanup()
    def test_core_review_fields_and_actions_fit_small_and_large_window(self):
        for width,height in [(1020,720),(1380,900)]:
            self.window.resize(width,height);self.app.processEvents()
            viewport=self.window.centralWidget().rect()
            for widget in [self.window.source,self.window.current,self.window.translation,self.window.notes,self.window.approvebutton,self.window.nextbutton,self.window.reviewcheck]:
                origin=widget.mapTo(self.window.centralWidget(),QPoint(0,0))
                self.assertTrue(viewport.contains(origin),widget.objectName())
                self.assertTrue(viewport.contains(origin+QPoint(widget.width()-1,widget.height()-1)))
            self.assertFalse(self.window.review_panel.findChildren(QScrollArea))
    def test_active_sentence_is_prominent_and_selection_stays_in_view(self):
        self.window.resize(1020,720);self.window.table.selectRow(15);self.app.processEvents()
        self.assertIn('Câu 16 / 30',self.window.focuslabel.text())
        self.assertEqual(self.window.source.toPlainText(),'Fold corner 15 toward the center.')
        rowrect=self.window.table.visualItemRect(self.window.table.item(15,1))
        self.assertTrue(self.window.table.viewport().rect().contains(rowrect.center()))
        self.window.next_row();self.assertEqual(self.window.table.currentRow(),16)
        self.assertIn('Câu 17 / 30',self.window.focuslabel.text())
