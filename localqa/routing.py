"""Bounded failover and task-aware caching for configured Gemini models."""
import json
import re
import httpx
from .core import fingerprint, technical, PROMPT_VERSION

DEFAULT_FALLBACKS = 'gemini-2.5-flash'
TRANSLATION_PROMPT_VERSION = '2'


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


def task_cache_key(row, model, context, task):
    if task == 'review':
        return fingerprint(row, model, context)
    if task != 'translate':
        raise ValueError('Tác vụ không hợp lệ')
    # The translation request never sends the existing Vietnamese text. A target
    # edit must not invalidate an otherwise identical translation request.
    source = {**row, 'vietnamese': ''}
    return fingerprint(source, f'translate-v{TRANSLATION_PROMPT_VERSION}:' + model, context)


def validate_result(result, row, task):
    from .gemini import ReviewValidationError, parse_review
    result = parse_review(json.dumps(result, ensure_ascii=False))
    if task == 'translate' and (result['status'] != 'REVIEW' or not result['suggestion'].strip()):
        raise ReviewValidationError('Chưa có bản dịch hợp lệ')
    if result['suggestion'] and 'Placeholder không khớp' in technical(row['english'], result['suggestion']):
        raise ReviewValidationError('Đề xuất làm thay đổi placeholder')
    return result


class ReviewRouter:
    def __init__(self, client, project, models, context, stop, notify):
        self.client, self.project, self.models = client, project, models
        self.context, self.stop, self.notify = context, stop, notify
        self.unavailable = set()
        self.active = models[0]
        self.request_count = 0

    def _result(self, result, model, task, *, cached):
        self.active = model
        return {**result, 'model_used': model, 'primary_model': self.models[0],
                'used_fallback': model != self.models[0], 'prompt_version': PROMPT_VERSION,
                'task': task, 'cache_hit': cached}

    def review(self, row, task='review'):
        if task not in ('review', 'translate'):
            raise ValueError('Tác vụ không hợp lệ')
        from .gemini import ReviewValidationError
        order = [self.active] + [m for m in self.models if m != self.active]
        if self.stop.is_set():
            raise ReviewCancelled()
        # A valid result from any configured model avoids a network call, even
        # if that model is currently unavailable for fresh requests.
        for model in order:
            try:
                result = self.project.cached(task_cache_key(row, model, self.context, task))
                if result is not None:
                    result = validate_result(result, row, task)
                    if self.stop.is_set():
                        raise ReviewCancelled()
                    return self._result(result, model, task, cached=True)
            except (ValueError, TypeError):
                # Old/malformed cache records are not accepted as model output.
                # A successful fresh call will replace this record.
                continue
        candidates = [m for m in order if m not in self.unavailable]
        last_code = None
        for index, model in enumerate(candidates):
            if self.stop.is_set():
                raise ReviewCancelled()
            cache_key = task_cache_key(row, model, self.context, task)
            for attempt in range(3):
                try:
                    self.request_count += 1
                    result = getattr(self.client, task)(row, model, self.context)
                    result = validate_result(result, row, task)
                    if self.stop.is_set():
                        raise ReviewCancelled()
                    self.project.cache(cache_key, result)
                    return self._result(result, model, task, cached=False)
                except ReviewCancelled:
                    raise
                except Exception as exc:
                    last_code = str(getattr(exc, 'code', ''))
                    invalid_output = isinstance(exc, ReviewValidationError)
                    recoverable = last_code in ('404', '429', '500', '502', '503', '504') or isinstance(exc, (TimeoutError, ConnectionError, httpx.TransportError)) or invalid_output
                    if not recoverable:
                        # Invalid credentials/requests are not fixed by switching.
                        raise
                    has_next = index + 1 < len(candidates)
                    if has_next or attempt == 2 or last_code == '404' or invalid_output:
                        # A bad answer is row-specific. It is not evidence that a
                        # model is unavailable for the remaining project rows.
                        if not invalid_output:
                            self.unavailable.add(model)
                        if has_next:
                            self.notify(f'{model} chưa dùng được; chuyển sang {candidates[index + 1]}.')
                        break
                    self.notify(f'{model} chưa phản hồi; thử lại sau {15 * (attempt + 1)} giây…')
                    if self.stop.wait(15 * (attempt + 1)):
                        raise ReviewCancelled()
        raise ModelsUnavailable(self.models, last_code)
