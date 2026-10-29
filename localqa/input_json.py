"""Strict, local-only JSON import for paired localization input.

No model is called. Original strings are retained, including placeholders and
whitespace. Missing language-map entries are explicit diagnostic records.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
from typing import Any

from .data import pair_json


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'JSON có key trùng: {key!r}')
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError(f'JSON có giá trị không hợp lệ: {value}')


def _read(path):
    source = Path(path)
    raw = source.read_bytes()
    try:
        document = json.loads(raw.decode('utf-8-sig'), object_pairs_hook=_unique_object,
                              parse_constant=_invalid_constant)
    except UnicodeDecodeError as exc:
        raise ValueError('JSON phải được mã hóa UTF-8') from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f'JSON không hợp lệ tại dòng {exc.lineno}, cột {exc.colno}: {exc.msg}') from exc
    return document, hashlib.sha256(raw).hexdigest()


def _warning(code, key, language, message):
    return {'code': code, 'key': key, 'language': language, 'message': message}


def _report(format_name, rows, diagnostics, hashes):
    return {'format_version': 1, 'format': format_name, 'paired_rows': len(rows),
            'source_sha256': hashes, 'diagnostics': diagnostics,
            'diagnostic_counts': dict(Counter(item['code'] for item in diagnostics))}


def _check_key(key, seen):
    if not isinstance(key, str) or not key.strip():
        raise ValueError('Mỗi câu cần key là chuỗi không rỗng')
    if key in seen:
        raise ValueError(f'Key câu bị trùng: {key!r}')
    seen.add(key)


def _blank_warnings(row):
    warnings = []
    for field, language in [('english', 'en'), ('vietnamese', 'vi')]:
        if not row[field].strip():
            warnings.append(_warning('blank_' + field, row['key'], language,
                                     'Chuỗi nguồn trống' if field == 'english' else 'Bản dịch trống'))
    return warnings


def _records(records, *, mapping=False):
    rows, diagnostics, seen = [], [], set()
    iterable = records.items() if mapping else enumerate(records, 1)
    for identity, record in iterable:
        if not isinstance(record, dict):
            raise ValueError(f'Câu {identity!r} phải là object có english và vietnamese')
        if mapping:
            key = identity
            if 'key' in record and record['key'] != key:
                raise ValueError(f'Key bên trong object không khớp key {key!r}')
        else:
            key = record.get('key')
        _check_key(key, seen)
        row = {'key': key}
        for field in ('english', 'vietnamese'):
            if field not in record or not isinstance(record[field], str):
                raise ValueError(f'{key!r}: trường {field} phải là chuỗi')
            row[field] = record[field]
        context = record.get('context', '')
        if not isinstance(context, str):
            raise ValueError(f'{key!r}: trường context phải là chuỗi')
        row['context'] = context
        rows.append(row)
        diagnostics.extend(_blank_warnings(row))
    if not rows:
        raise ValueError('JSON chưa có cặp câu nào')
    return rows, diagnostics


def _language_maps(english, vietnamese):
    for name, values in [('en', english), ('vi', vietnamese)]:
        if not isinstance(values, dict):
            raise ValueError(f'Ngôn ngữ {name} phải là object key → chuỗi')
        for key, value in values.items():
            if not key.strip() or not isinstance(value, str):
                raise ValueError(f'{name}/{key}: key phải khác rỗng và nội dung phải là chuỗi')
    rows, diagnostics = [], []
    for key in sorted(english.keys() | vietnamese.keys()):
        row = {'key': key, 'english': english.get(key, ''),
               'vietnamese': vietnamese.get(key, ''), 'context': ''}
        for values, language, field in [(english, 'en', 'english'), (vietnamese, 'vi', 'vietnamese')]:
            if key not in values:
                diagnostics.append(_warning('missing_' + field, key, language,
                                            'Không có câu tiếng Anh tương ứng' if language == 'en' else 'Không có câu tiếng Việt tương ứng'))
            elif not values[key].strip():
                diagnostics.append(_warning('blank_' + field, key, language,
                                            'Chuỗi nguồn trống' if language == 'en' else 'Bản dịch trống'))
        rows.append(row)
    if not rows:
        raise ValueError('JSON chưa có cặp câu nào')
    return rows, diagnostics


def load_json(path: str | Path) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """Import one explicitly bilingual JSON file; return rows and diagnostics.

    Supported: paired record list, {translations: list}, key→record mapping,
    or {en: key→string, vi: key→string}. No automatic language detection.
    """
    document, digest = _read(path)
    if isinstance(document, list):
        rows, diagnostics = _records(document)
        name = 'paired_record_list'
    elif isinstance(document, dict) and 'translations' in document:
        if not isinstance(document['translations'], list):
            raise ValueError('Trường translations phải là danh sách các cặp câu')
        rows, diagnostics = _records(document['translations'])
        name = 'translations_wrapper'
    elif isinstance(document, dict) and document and set(document) <= {'en', 'vi'}:
        rows, diagnostics = _language_maps(document.get('en', {}), document.get('vi', {}))
        name = 'language_maps'
    elif isinstance(document, dict):
        rows, diagnostics = _records(document, mapping=True)
        name = 'paired_record_mapping'
    else:
        raise ValueError('JSON gốc phải là danh sách cặp câu hoặc object song ngữ')
    return rows, _report(name, rows, diagnostics, {'input': digest})


def load_json_pair(english_path: str | Path, vietnamese_path: str | Path
                   ) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """Pair two language files: flat maps or asset trees supported by data.pair_json.

    The argument order is explicit. The importer does not guess which file is
    English. Asset object IDs are preferred; unkeyed steps remain positional.
    """
    english, en_hash = _read(english_path)
    vietnamese, vi_hash = _read(vietnamese_path)
    flat = (isinstance(english, dict) and isinstance(vietnamese, dict)
            and all(isinstance(v, str) for v in english.values())
            and all(isinstance(v, str) for v in vietnamese.values()))
    if flat:
        rows, diagnostics = _language_maps(english, vietnamese)
        report = _report('paired_flat_language_files', rows, diagnostics, {'en': en_hash, 'vi': vi_hash})
    else:
        rows, report = pair_json(english, vietnamese)
        if not rows:
            raise ValueError('Hai JSON chưa có trường hiển thị để ghép; dùng title, name, categoryLabel hoặc description, hoặc JSON song ngữ chuẩn')
        report.update(format='paired_asset_files', source_sha256={'en': en_hash, 'vi': vi_hash})
    return rows, report
