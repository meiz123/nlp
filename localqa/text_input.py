"""Plain text entry with both Mac and Windows paste shortcuts."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QPlainTextEdit


class SourceTextEdit(QPlainTextEdit):
    def keyPressEvent(self, event):
        modifiers = event.modifiers()
        explicit_paste = event.key() == Qt.Key.Key_V and modifiers in (
            Qt.KeyboardModifier.ControlModifier, Qt.KeyboardModifier.MetaModifier)
        if event.matches(QKeySequence.StandardKey.Paste) or explicit_paste:
            if not self.isReadOnly():self.paste()
            event.accept()
            return
        super().keyPressEvent(event)
