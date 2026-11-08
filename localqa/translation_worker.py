"""Single-sentence translation without altering source text or approvals."""
import tempfile
import threading
from pathlib import Path
from PySide6.QtCore import QThread, Signal
from .core import Project
from .routing import ReviewRouter, ReviewCancelled, ModelsUnavailable, model_chain


class TranslationWorker(QThread):
    progress = Signal(str)
    failed = Signal(str)
    ready = Signal(dict)

    def __init__(self, path, row, key, model, fallbacks, context, task="translate"):
        super().__init__()
        self.args = path, dict(row), key, model, fallbacks, context
        self.stop = threading.Event();self.task=task

    def run(self):
        from .gemini import Gemini
        p = client = None
        with tempfile.TemporaryDirectory() as temp:
            try:
                path, row, key, model, fallbacks, context = self.args
                p = Project(path or str(Path(temp) / 'translation.lqa'))
                client = Gemini(key)
                router = ReviewRouter(client, p, model_chain(model, fallbacks), context, self.stop, self.progress.emit)
                result = router.review(row, task=self.task)
                if not self.stop.is_set():self.ready.emit(result)
            except ReviewCancelled:
                pass
            except ModelsUnavailable as exc:
                self.failed.emit(str(exc)+'. Nội dung đã nhập được giữ nguyên; thử lại hoặc bổ sung ngữ cảnh.')
            except Exception:
                self.failed.emit('Chưa dịch được. Kiểm tra API key, model, hạn mức và kết nối. Nội dung đã nhập được giữ nguyên.')
            finally:
                if client:client.close()
                if p:p.close()
