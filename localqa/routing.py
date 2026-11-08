"""Bounded failover within the user's configured Gemini models."""
import json
import re
import httpx
from .core import fingerprint, technical, PROMPT_VERSION

DEFAULT_FALLBACKS = 'gemini-2.5-flash'


class ReviewCancelled(Exception):
    pass


class ModelsUnavailable(Exception):
    def __init__(self, models, code=None):
        self.code = code
        super().__init__('Các model đã cấu hình chưa trả được kết quả hợp lệ: ' + ', '.join(models))


def model_chain(primary, fallbacks):
    values = re.split(r'[,;\n]+', fallbacks) if isinstance(fallbacks, str) else list(fallbacks or [])
    models = list(dict.fromkeys(x.strip() for x in [primary, *values] if x.strip()))
    if not models:
        raise ValueError('Nhập ít nhất một tên model')
    if len(models) > 4:
        raise ValueError('Chọn tối đa 4 model gồm model chính và dự phòng')
    return models


class ReviewRouter:
    def __init__(self, client, project, models, context, stop, notify):
        self.client, self.project, self.models = client, project, models
        self.context, self.stop, self.notify = context, stop, notify
        self.unavailable = set()
        self.active = models[0]

    def review(self, row, task="review"):
        if task not in ("review", "translate"):raise ValueError("Tác vụ không hợp lệ")
        from .gemini import ReviewValidationError, parse_review
        order = [self.active] + [m for m in self.models if m != self.active]
        candidates = [m for m in order if m not in self.unavailable]
        last_code = None
        for index, model in enumerate(candidates):
            if self.stop.is_set():
                raise ReviewCancelled()
            cache_key = fingerprint(row, model if task == "review" else "translate-v1:" + model, self.context)
            result = self.project.cached(cache_key)
            if result is None:
                for attempt in range(3):
                    try:
                        result = getattr(self.client, task)(row, model, self.context)
                        # Apply the same contract even when adapters are replaced.
                        result = parse_review(json.dumps(result, ensure_ascii=False))
                        if task == 'translate' and (result['status'] != 'REVIEW' or not result['suggestion'].strip()):
                            raise ReviewValidationError('Chưa có bản dịch hợp lệ')
                        if result['suggestion'] and 'Placeholder không khớp' in technical(row['english'], result['suggestion']):
                            raise ReviewValidationError('Đề xuất làm thay đổi placeholder')
                        if self.stop.is_set():
                            raise ReviewCancelled()
                        self.project.cache(cache_key, result)
                        break
                    except ReviewCancelled:
                        raise
                    except Exception as exc:
                        last_code = str(getattr(exc, 'code', ''))
                        recoverable = last_code in ('404', '429', '500', '502', '503', '504') or isinstance(exc, (TimeoutError, ConnectionError, httpx.TransportError, ReviewValidationError))
                        if not recoverable:
                            # Invalid credentials/requests are not fixed by model switching.
                            raise
                        has_next = index + 1 < len(candidates)
                        if has_next or attempt == 2 or last_code == '404' or isinstance(exc, ReviewValidationError):
                            self.unavailable.add(model)
                            result = None
                            if has_next:
                                self.notify(f'{model} chưa dùng được; chuyển sang {candidates[index + 1]}.')
                            break
                        self.notify(f'{model} chưa phản hồi; thử lại sau {15 * (attempt + 1)} giây…')
                        if self.stop.wait(15 * (attempt + 1)):
                            raise ReviewCancelled()
            if result is not None:
                self.active = model
                return {**result, 'model_used': model, 'primary_model': self.models[0],
                        'used_fallback': model != self.models[0], 'prompt_version': PROMPT_VERSION, 'task': task}
        raise ModelsUnavailable(self.models, last_code)
