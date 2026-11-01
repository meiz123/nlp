import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication,QFileDialog,QLineEdit
from localqa.app import Window
from localqa.core import Project

class DesktopStabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def window(self):
        with patch('keyring.get_password',return_value=None):
            return Window()

    def test_file_picker_accepts_existing_project_without_completer(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'sample.lqa';Project(path).close()
            window=self.window()
            def accept():
                dialog=window.file_dialogs[-1]
                self.assertEqual(dialog.viewMode(),QFileDialog.ViewMode.List)
                self.assertIsNone(dialog.findChild(QLineEdit,'fileNameEdit').completer())
                dialog.selectFile(str(path));dialog.accept()
            QTimer.singleShot(0,accept)
            selected,_=window.choose_file('Open','Project (*.lqa)')
            self.assertTrue(Path(selected).samefile(path))
            window.attach(selected)
            self.assertTrue(Path(window.project.path).samefile(path))
            window.close()

    def test_refresh_preserves_item_objects_and_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'sample.lqa';project=Project(path)
            project.import_rows([{'key':'one','english':'Save','vietnamese':'Lưu'}]);project.close()
            window=self.window();window.attach(str(path));window.table.selectRow(0)
            item=window.table.item(0,0)
            window.project.save_result('one',{'status':'PASS','issues':[],'reason':'Good','suggestion':''})
            window.refresh()
            self.assertIs(window.table.item(0,0),item)
            self.assertEqual(window.table.currentRow(),0)
            self.assertEqual(window.table.item(0,3).text(),'Ổn')
            window.close()

    def test_export_picker_preserves_two_name_filters(self):
        window=self.window()
        def cancel():
            dialog=window.file_dialogs[-1]
            self.assertEqual(dialog.nameFilters(),['CSV (*.csv)','Excel (*.xlsx)'])
            dialog.reject()
        QTimer.singleShot(0,cancel)
        self.assertEqual(window.choose_file('Export','CSV (*.csv);;Excel (*.xlsx)',True),('',''))
        window.close()
