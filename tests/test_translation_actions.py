import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QPoint
from localqa.app import Window

class TranslationActionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        with patch('keyring.get_password',return_value=None):self.w=Window()
        self.errors=[];self.w.error=self.errors.append
    def tearDown(self):self.w.close()
    def test_entry_actions_work_without_project(self):
        self.assertTrue(self.w.actions[2].isEnabled());self.assertTrue(self.w.runbutton.isEnabled())
        self.assertTrue(self.w.translatebelow.isEnabled())
        self.w.source.setPlainText('Hello');self.w.translatebelow.click()
        self.assertEqual(len(self.errors),1);self.assertTrue(self.w.configbutton.isChecked());self.assertIsNone(self.w.worker)
    def test_import_button_creates_project_after_parsing(self):
        with tempfile.TemporaryDirectory() as temp:
            source=Path(temp)/'in.json';source.write_text('[{"key":"a","english":"Hello","vietnamese":"Chào"}]')
            self.w.choose_files=lambda *a:[str(source)]
            self.w.choose_file=lambda *a:(str(Path(temp)/'new.lqa'),'')
            self.w.actions[2].click();self.assertEqual(len(self.w.project.rows()),1);self.w.close();self.w.project=None
    def test_exports_explain_missing_prerequisites(self):
        self.w.actions[3].click();self.w.actions[4].click();self.assertEqual(len(self.errors),2)
        self.assertIn('Chưa có dữ liệu',self.errors[0]);self.assertIn('đã duyệt',self.errors[1])
    def test_lower_translate_button_is_below_source_and_fits_laptop(self):
        self.w.settings.hide();self.w.resize(1020,720);self.w.show();self.app.processEvents()
        source=self.w.source.mapTo(self.w.review_panel,QPoint(0,0));button=self.w.translatebelow.mapTo(self.w.review_panel,QPoint(0,0))
        self.assertGreaterEqual(button.y(),source.y()+self.w.source.height())
        self.assertTrue(self.w.centralWidget().rect().contains(self.w.translatebelow.mapTo(self.w.centralWidget(),QPoint(0,0))))
    def test_busy_disables_all_translate_actions(self):
        self.w.busy(True);self.assertFalse(self.w.translatebelow.isEnabled());self.assertFalse(self.w.actions[2].isEnabled());self.w.busy(False)
