"""Import saved model comparisons without calling a model or approving its output."""
from __future__ import annotations

import csv
from pathlib import Path
from .core import technical

REQUIRED_COLUMNS = (
    'key', 'english', 'original_vietnamese',
    'local_translation', 'gemini_translation', 'winner', 'reason',
)
WINNERS = {'local', 'gemini', 'tie', 'unresolved'}


def _boolean(value: str, *, line: int) -> bool:
    normalized = value.strip().casefold()
    if normalized in ('true', '1', 'yes', 'có', 'đã review'):
        return True
    if normalized in ('false', '0', 'no', 'không', ''):
        return False
    raise ValueError(f'Dòng {line}: reviewed phải là TRUE hoặc FALSE')


def load_comparison_csv(path: str | Path, *, import_feedback: bool = False) -> list[dict]:
    """Validate the entire input before the project is changed.

    ``human_approved`` is deliberately ignored: model/assistant provenance is not
    permission to mark a record as reviewed or use it as training data.
    """
    with Path(path).open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        columns = reader.fieldnames or []
        if len(columns) != len(set(columns)):
            raise ValueError('CSV so sánh có tên cột trùng nhau')
        missing = set(REQUIRED_COLUMNS) - set(columns)
        if missing:
            raise ValueError('CSV so sánh thiếu cột: ' + ', '.join(sorted(missing)))
        rows, seen = [], set()
        for line, raw in enumerate(reader, 2):
            if None in raw or any(raw.get(column) is None for column in columns):
                raise ValueError(f'Dòng {line}: số ô không khớp tiêu đề CSV')
            key = raw['key']
            if not key.strip() or key in seen:
                raise ValueError(f'Dòng {line}: key rỗng hoặc trùng: {key!r}')
            seen.add(key)
            winner = raw['winner'].strip().casefold()
            if winner not in WINNERS:
                raise ValueError(f'Dòng {line}: winner không hợp lệ: {raw["winner"]!r}')
            record = dict(raw, winner=winner)
            if import_feedback:
                if 'reviewed' not in columns:
                    raise ValueError('Muốn nhập feedback cần cột reviewed rõ ràng')
                record['_reviewed'] = _boolean(raw['reviewed'], line=line)
                approved = raw.get('approved_translation', '')
                if approved.strip() and not record['_reviewed']:
                    raise ValueError(f'Dòng {line}: bản sửa đã duyệt cần reviewed=TRUE')
                if approved.strip():
                    blocking = set(technical(raw['english'], approved)) & {
                        'Placeholder không khớp', 'Thiếu bản dịch tiếng Việt',
                    }
                    if blocking:
                        raise ValueError(f'Dòng {line}: bản sửa đã duyệt không hợp lệ: ' + ', '.join(sorted(blocking)))
            rows.append(record)
    if not rows:
        raise ValueError('CSV so sánh chưa có câu nào')
    return rows


def import_comparison(project, path: str | Path, *, import_feedback: bool = False) -> int:
    """Import original inputs + separately attributed results; return row count.

    The default never restores human feedback from a model-result CSV. Callers
    must explicitly choose ``import_feedback=True`` for a user-edited feedback
    file. Source changes rely on Project.import_rows to invalidate stale state.
    """
    records = load_comparison_csv(path, import_feedback=import_feedback)
    existing = {row['key']: row for row in project.rows()}
    originals = []
    for row in records:
        context = row.get('context')
        if context is None:
            context = existing.get(row['key'], {}).get('context', '')
        originals.append({
            'key': row['key'], 'english': row['english'],
            'vietnamese': row['original_vietnamese'], 'context': context,
        })
    project.import_rows(originals)
    for row in records:
        key = row['key']
        project.save_backend_result(key, 'local', {
            'translation': row['local_translation'],
            'reviewer_findings': row.get('local_reviewer_findings', ''),
            'origin': 'imported_comparison_csv',
        })
        project.save_backend_result(key, 'gemini', {
            'translation': row['gemini_translation'],
            'reviewer_findings': row.get('gemini_reviewer_findings', ''),
            'origin': 'imported_comparison_csv',
        })
        project.save_backend_result(key, 'comparison', {
            'winner': row['winner'], 'reason': row['reason'],
            'context_needed': row.get('context_needed', ''),
            'origin': 'imported_comparison_csv',
            'human_approved': False,
        })
        if import_feedback:
            approved = row.get('approved_translation', '')
            project.save_feedback(
                key, row['_reviewed'], row.get('review_notes', ''),
                approved_text=approved if 'approved_translation' in row else None,
            )
    return len(records)
