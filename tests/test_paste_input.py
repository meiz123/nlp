import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import unittest
from unittest.mock import patch
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from localqa.app import Window

class PasteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        with patch('keyring.get_password',return_value=None):self.w=Window()
        self.clipboard=self.app.clipboard();self.previous=self.clipboard.text()
    def tearDown(self):self.clipboard.setText(self.previous);self.w.close()
    def test_both_shortcuts_paste_multiple_lines_and_placeholders(self):
        text='Hello {name}\nSave %1$s items\nTiếng Việt có dấu'
        for modifier in (Qt.KeyboardModifier.ControlModifier,Qt.KeyboardModifier.MetaModifier):
            self.w.source.clear();self.clipboard.setText(text)
            QTest.keyClick(self.w.source,Qt.Key.Key_V,modifier)
            self.assertEqual(self.w.source.toPlainText(),text)
    def test_paste_button_replaces_selection_and_is_undoable(self):
        self.w.source.setPlainText('Hello world');cursor=self.w.source.textCursor();cursor.setPosition(6);cursor.setPosition(11,cursor.MoveMode.KeepAnchor);self.w.source.setTextCursor(cursor)
        self.clipboard.setText('{name}\nAgain');self.w.pastebutton.click()
        self.assertEqual(self.w.source.toPlainText(),'Hello {name}\nAgain')
        self.w.source.undo();self.assertEqual(self.w.source.toPlainText(),'Hello world')
    def test_review_source_and_running_input_are_protected(self):
        self.w.manual_mode.setChecked(False);self.clipboard.setText('Do not overwrite')
        QTest.keyClick(self.w.source,Qt.Key.Key_V,Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(self.w.source.toPlainText(),'');self.assertFalse(self.w.pastebutton.isEnabled())
        self.w.manual_mode.setChecked(True);self.w.busy(True)
        QTest.keyClick(self.w.source,Qt.Key.Key_V,Qt.KeyboardModifier.MetaModifier)
        self.assertEqual(self.w.source.toPlainText(),'');self.assertFalse(self.w.pastebutton.isEnabled());self.w.busy(False)
