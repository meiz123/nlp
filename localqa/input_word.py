"""Read explicitly paired Word translations locally, without guessing language pairs."""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
COLUMNS = ('key', 'english', 'vietnamese', 'context')
ALIASES = {
    'key': 'key', 'mã': 'key', 'mã câu': 'key', 'khóa': 'key',
    'english': 'english', 'en': 'english', 'tiếng anh': 'english',
    'vietnamese': 'vietnamese', 'vi': 'vietnamese', 'tiếng việt': 'vietnamese',
    'bản dịch tiếng việt': 'vietnamese',
    'context': 'context', 'ngữ cảnh': 'context',
}
MAX_DOCUMENT_BYTES = 20 * 1024 * 1024
MAX_ARCHIVE_BYTES = 100 * 1024 * 1024


def _paragraph_text(paragraph: ET.Element) -> str:
    parts = []
    for node in paragraph.iter():
        if node.tag == W + 't':
            parts.append(node.text or '')
        elif node.tag in (W + 'br', W + 'cr'):
            parts.append('\n')
        elif node.tag == W + 'tab':
            parts.append('\t')
    return ''.join(parts)


def _cell_text(cell: ET.Element) -> str:
    return '\n'.join(_paragraph_text(p) for p in cell.findall(W + 'p'))


def _validate(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    if not rows:
        raise ValueError('Không tìm thấy cặp dịch. Word cần bảng key, english, vietnamese hoặc các khối Key:/English:/Vietnamese:.')
    seen = set()
    for index, row in enumerate(rows, 1):
        missing = {'key', 'english', 'vietnamese'} - row.keys()
        if missing:
            raise ValueError(f'Mục {index}: thiếu trường ' + ', '.join(sorted(missing)))
        if not row['key'].strip() or row['key'] in seen:
            raise ValueError(f'Mục {index}: key rỗng hoặc trùng: {row["key"]!r}')
        if not row['english'].strip():
            raise ValueError(f'Mục {index}: câu tiếng Anh không được trống')
        seen.add(row['key'])
    return [{field: row.get(field, '') for field in COLUMNS} for row in rows]


def _table_rows(table: ET.Element, number: int) -> list[dict[str, str]]:
    xmlrows = table.findall(W + 'tr')
    if not xmlrows:
        return []
    header = [_cell_text(cell).strip().casefold() for cell in xmlrows[0].findall(W + 'tc')]
    mapped = [ALIASES.get(value) for value in header]
    if not {'key', 'english', 'vietnamese'} <= set(mapped):
        raise ValueError(f'Bảng {number}: hàng đầu cần các cột key, english, vietnamese (ngữ cảnh là tùy chọn).')
    if len([value for value in mapped if value]) != len(set(value for value in mapped if value)):
        raise ValueError(f'Bảng {number}: tên cột trùng nhau')
    result = []
    for index, row in enumerate(xmlrows[1:], 2):
        cells = row.findall(W + 'tc')
        if any(cell.find('.//' + W + 'gridSpan') is not None or cell.find('.//' + W + 'vMerge') is not None for cell in cells):
            raise ValueError(f'Bảng {number}, dòng {index}: không hỗ trợ ô gộp trong dữ liệu dịch')
        values = [_cell_text(cell) for cell in cells]
        if not any(value.strip() for value in values):
            continue
        if len(values) != len(header):
            raise ValueError(f'Bảng {number}, dòng {index}: số ô không khớp tiêu đề')
        result.append({field: value for field, value in zip(mapped, values) if field})
    return result


def _paragraph_rows(paragraphs: list[str]) -> list[dict[str, str]]:
    rows, current, active = [], {}, None
    for paragraph in paragraphs:
        for line in paragraph.split('\n'):
            match = re.match(r'^\s*([^:：]+)[:：](.*)$', line)
            field = ALIASES.get(match[1].strip().casefold()) if match else None
            if field:
                if field == 'key' and current:
                    rows.append(current)
                    current, active = {}, None
                if not current and field != 'key':
                    raise ValueError('Khối dịch Word phải bắt đầu bằng Key:')
                if field in current:
                    raise ValueError(f'Khối {current.get("key", "")!r}: trường {field} bị lặp')
                # Strip one separator space, while preserving meaningful content whitespace.
                value = match[2]
                current[field] = value[1:] if value.startswith(' ') else value
                active = field
            elif active:
                current[active] += '\n' + line
            elif line.strip():
                raise ValueError('Không thể ghép câu trong văn bản tự do. Hãy dùng bảng hoặc khối Key:/English:/Vietnamese:.')
    if current:
        rows.append(current)
    return rows


def _read_docx(path: Path) -> list[dict[str, str]]:
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            if len(entries) > 5000 or sum(entry.file_size for entry in entries) > MAX_ARCHIVE_BYTES:
                raise ValueError('Tài liệu Word quá lớn để nhập an toàn')
            if any(entry.flag_bits & 1 for entry in entries):
                raise ValueError('Tài liệu Word được mã hóa. Hãy lưu bản .docx không có mật khẩu.')
            try:
                document = archive.getinfo('word/document.xml')
            except KeyError as exc:
                raise ValueError('File không phải tài liệu DOCX hợp lệ') from exc
            if document.file_size > MAX_DOCUMENT_BYTES:
                raise ValueError('Nội dung Word quá lớn (tối đa 20 MB văn bản XML)')
            xml = archive.read(document)
        if b'<!DOCTYPE' in xml.upper() or b'<!ENTITY' in xml.upper():
            raise ValueError('Tài liệu chứa cấu trúc XML không được hỗ trợ')
        root = ET.fromstring(xml)
    except (zipfile.BadZipFile, ET.ParseError, RuntimeError, OSError) as exc:
        raise ValueError('Không đọc được Word: file hỏng, được mã hóa hoặc chưa phải DOCX. Hãy lưu lại dạng .docx không có mật khẩu.') from exc
    body = root.find(W + 'body')
    if body is None:
        raise ValueError('Tài liệu Word không có nội dung')
    tables = body.findall(W + 'tbl')
    rows = []
    for number, table in enumerate(tables, 1):
        rows.extend(_table_rows(table, number))
    paragraphs = [_paragraph_text(p) for p in body.findall(W + 'p')]
    meaningful = [text for text in paragraphs if text.strip()]
    if not tables:
        rows.extend(_paragraph_rows(meaningful))
    elif any(re.match(r'^\s*(?:key|mã câu|mã|khóa)\s*[:：]', text, re.I) for text in meaningful):
        # Mixing prose and translation blocks outside tables is ambiguous; use one format.
        raise ValueError('Word đang trộn bảng và khối Key:. Hãy dùng một định dạng ghép câu trong một file.')
    return _validate(rows)


def _convert_doc(source: Path, directory: Path) -> Path:
    target = directory / (source.stem + '.docx')
    textutil = shutil.which('textutil') if sys.platform == 'darwin' else None
    office = shutil.which('soffice') or shutil.which('libreoffice')
    if textutil:
        command = [textutil, '-convert', 'docx', '-output', str(target), str(source.resolve())]
    elif office:
        profile = (directory / 'office-profile').resolve().as_uri()
        command = [office, f'-env:UserInstallation={profile}', '--headless', '--convert-to', 'docx', '--outdir', str(directory), str(source.resolve())]
    else:
        raise ValueError('File .doc đời cũ cần textutil trên Mac hoặc LibreOffice để chuyển đổi. Hãy mở bằng Word và Save As .docx rồi nhập lại.')
    try:
        completed = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError('Không chuyển đổi được .doc. Hãy lưu bằng Word thành .docx rồi nhập lại.') from exc
    if completed.returncode or not target.is_file():
        raise ValueError('Không chuyển đổi được .doc (có thể file hỏng hoặc có mật khẩu). Hãy lưu bản .docx không có mật khẩu.')
    return target


def load_word(path: str | Path) -> list[dict[str, str]]:
    """Return exact structured pairs from .docx, or converted legacy .doc."""
    source = Path(path)
    if source.suffix.casefold() not in ('.doc', '.docx'):
        raise ValueError('Chỉ hỗ trợ tài liệu Word .docx hoặc .doc')
    if not source.is_file():
        raise ValueError('Không tìm thấy file Word đã chọn')
    if source.stat().st_size > MAX_ARCHIVE_BYTES:
        raise ValueError('File Word quá lớn (tối đa 100 MB)')
    if source.suffix.casefold() == '.docx':
        return _read_docx(source)
    with tempfile.TemporaryDirectory(prefix='localqa-doc-') as folder:
        return _read_docx(_convert_doc(source, Path(folder)))
