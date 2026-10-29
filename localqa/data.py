"""Local-only preparation of paired localization datasets (no API calls)."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
from collections import Counter
from pathlib import Path
from typing import Any

COLUMNS = ('key', 'english', 'vietnamese', 'context')
DISPLAY_FIELDS = frozenset({'title', 'name', 'categoryLabel', 'description'})


def load_paired_csv(path: str | Path) -> list[dict[str, str]]:
    """Read exact strings without trimming translations or silently dropping rows."""
    with Path(path).open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        fields = reader.fieldnames or []
        if len(fields) != len(set(fields)):
            raise ValueError('CSV có tên cột trùng nhau')
        if not {'key', 'english', 'vietnamese'} <= set(fields):
            raise ValueError('CSV cần các cột key, english, vietnamese; context là tùy chọn')
        rows, seen = [], set()
        for line, raw in enumerate(reader, 2):
            if None in raw or any(raw.get(field) is None for field in fields):
                raise ValueError(f'Dòng {line}: số ô không khớp với tiêu đề CSV')
            key = raw['key']
            if not key.strip() or key in seen:
                raise ValueError(f'Dòng {line}: key rỗng hoặc trùng: {key!r}')
            seen.add(key)
            rows.append({field: raw.get(field, '') for field in COLUMNS})
        return rows


def write_pairs(rows: list[dict[str, str]], path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=COLUMNS, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)


def sample_rows(rows: list[dict[str, str]], count: int, seed: int = 29) -> list[dict[str, str]]:
    """Reproducible even when the input CSV row order changes."""
    if count < 1 or count > len(rows):
        raise ValueError(f'Số câu lấy mẫu phải từ 1 đến {len(rows)}')
    keys = [row['key'] for row in rows]
    if len(keys) != len(set(keys)):
        raise ValueError('Không lấy mẫu khi key trùng nhau')
    selected = random.Random(seed).sample(sorted(rows, key=lambda row: row['key']), count)
    return sorted(selected, key=lambda row: row['key'])


def _escape(value: str) -> str:
    return value.replace('~', '~0').replace('/', '~1')


def _leaves(document: Any, language: str) -> tuple[dict[str, str], list[dict[str, str]]]:
    leaves: dict[str, str] = {}
    diagnostics: list[dict[str, str]] = []

    def warn(code: str, path: str, message: str) -> None:
        diagnostics.append({'code': code, 'language': language, 'key': path, 'message': message})

    def visit(value: Any, path: str) -> None:
        if isinstance(value, dict):
            for field, child in value.items():
                child_path = path + '/' + _escape(field)
                if field in DISPLAY_FIELDS:
                    if isinstance(child, str):
                        leaves[child_path] = child
                    else:
                        warn('invalid_text_type', child_path, 'Trường hiển thị phải là chuỗi')
                elif isinstance(child, (dict, list)):
                    visit(child, child_path)
        elif isinstance(value, list):
            ids = [str(item['id']) for item in value if isinstance(item, dict)
                   and isinstance(item.get('id'), (str, int)) and not isinstance(item.get('id'), bool)
                   and str(item['id']).strip()]
            duplicates = {identity for identity, count in Counter(ids).items() if count > 1}
            for identity in sorted(duplicates):
                warn('duplicate_id', path + '/@id=' + _escape(identity),
                     'ID trùng; bỏ qua các đối tượng có ID này để tránh ghép sai')
            for index, child in enumerate(value):
                identity = None
                if isinstance(child, dict) and 'id' in child:
                    raw_id = child['id']
                    if isinstance(raw_id, (str, int)) and not isinstance(raw_id, bool) and str(raw_id).strip():
                        identity = str(raw_id)
                    else:
                        warn('invalid_id', path + '/' + str(index), 'ID rỗng hoặc không hợp lệ; bỏ qua đối tượng')
                        continue
                if identity in duplicates:
                    continue
                # Named objects match by stable ID. Unnamed steps match by index.
                component = '@id=' + _escape(identity) if identity is not None else str(index)
                visit(child, path + '/' + component)

    if not isinstance(document, (dict, list)):
        raise ValueError('JSON gốc phải là object hoặc array')
    visit(document, '')
    return leaves, diagnostics


def pair_json(english: Any, vietnamese: Any) -> tuple[list[dict[str, str]], dict[str, Any]]:
    en, en_issues = _leaves(english, 'en')
    vi, vi_issues = _leaves(vietnamese, 'vi')
    issues = en_issues + vi_issues
    rows = []
    for key in sorted(en.keys() | vi.keys()):
        if key not in en:
            issues.append({'code': 'missing_english', 'language': 'en', 'key': key, 'message': 'Không có trường tiếng Anh tương ứng'})
        if key not in vi:
            issues.append({'code': 'missing_vietnamese', 'language': 'vi', 'key': key, 'message': 'Không có trường tiếng Việt tương ứng'})
        source, target = en.get(key, ''), vi.get(key, '')
        if key in en and not source.strip():
            issues.append({'code': 'blank_english', 'language': 'en', 'key': key, 'message': 'Chuỗi nguồn trống'})
        if key in vi and not target.strip():
            issues.append({'code': 'blank_vietnamese', 'language': 'vi', 'key': key, 'message': 'Bản dịch trống'})
        context = 'Nguồn JSON: ' + key
        if '/data/' in key:
            context += '; bước hướng dẫn ghép theo vị trí trong mảng; cần xác nhận thứ tự bước giống nhau'
        rows.append({'key': key, 'english': source, 'vietnamese': target, 'context': context})
    report = {'format_version': 1, 'display_fields': sorted(DISPLAY_FIELDS),
              'english_fields': len(en), 'vietnamese_fields': len(vi), 'paired_rows': len(rows),
              'diagnostic_counts': dict(Counter(issue['code'] for issue in issues)), 'diagnostics': issues,
              'limitations': ['Các bước không có ID được ghép theo vị trí; không xác minh được việc đổi thứ tự bước.',
                              'Chuỗi giống nhau giữa hai ngôn ngữ không tự động bị coi là lỗi.']}
    return rows, report


def _digest(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Chuẩn bị dữ liệu Anh–Việt trên máy; không gọi AI')
    commands = parser.add_subparsers(dest='command', required=True)
    pair = commands.add_parser('pair-json', help='Ghép hai JSON ngôn ngữ theo ID/đường dẫn')
    pair.add_argument('english'); pair.add_argument('vietnamese'); pair.add_argument('--output', required=True)
    pair.add_argument('--report'); pair.add_argument('--strict', action='store_true', help='Mã thoát 2 khi có cảnh báo dữ liệu')
    sample = commands.add_parser('sample', help='Lấy mẫu CSV có thể tái lập')
    sample.add_argument('input'); sample.add_argument('--output', required=True)
    sample.add_argument('--count', type=int, default=10); sample.add_argument('--seed', type=int, default=29)
    args = parser.parse_args(argv)
    try:
        output = Path(args.output)
        sources = [Path(args.english), Path(args.vietnamese)] if args.command == 'pair-json' else [Path(args.input)]
        if any(output.resolve() == source.resolve() for source in sources):
            raise ValueError('File xuất không được ghi đè file nguồn')
        if args.command == 'pair-json':
            with sources[0].open(encoding='utf-8-sig') as stream: en = json.load(stream)
            with sources[1].open(encoding='utf-8-sig') as stream: vi = json.load(stream)
            rows, report = pair_json(en, vi)
            report['source_sha256'] = {'en': _digest(sources[0]), 'vi': _digest(sources[1])}
            report_path = Path(args.report) if args.report else output.with_suffix('.report.json')
            if report_path.resolve() == output.resolve() or any(report_path.resolve() == source.resolve() for source in sources):
                raise ValueError('File báo cáo phải khác file xuất và các file nguồn')
        else:
            all_rows = load_paired_csv(args.input)
            rows = sample_rows(all_rows, args.count, args.seed)
            report = {'format_version': 1, 'seed': args.seed, 'input_rows': len(all_rows),
                      'sample_rows': len(rows), 'selected_keys': [row['key'] for row in rows],
                      'source_sha256': _digest(args.input)}
            report_path = output.with_suffix('.report.json')
            if report_path.resolve() == output.resolve() or any(report_path.resolve() == source.resolve() for source in sources):
                raise ValueError('File báo cáo phải khác file xuất và file nguồn')
        write_pairs(rows, output)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'Đã xuất {len(rows)} câu: {output}')
        print(f'Báo cáo dữ liệu: {report_path}')
        return 2 if args.command == 'pair-json' and args.strict and report['diagnostics'] else 0
    except (OSError, ValueError, csv.Error) as exc:
        parser.exit(1, f'Lỗi dữ liệu: {exc}\n')


if __name__ == '__main__':
    raise SystemExit(main())
