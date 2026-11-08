"""Read translation tables locally; never evaluate workbook formulas."""
from pathlib import Path
import zipfile
from .input_word import ALIASES


def load_excel(path):
    source = Path(path)
    if source.suffix.lower() != '.xlsx':
        raise ValueError('Excel cần định dạng .xlsx. Hãy Save As file .xls thành .xlsx rồi nhập lại.')
    if source.stat().st_size > 20 * 1024 * 1024:
        raise ValueError('File Excel vượt quá 20 MB')
    try:
        with zipfile.ZipFile(source) as archive:
            if sum(x.file_size for x in archive.infolist()) > 100 * 1024 * 1024:
                raise ValueError('Nội dung Excel quá lớn')
        from openpyxl import load_workbook
        book = load_workbook(source, read_only=True, data_only=False, keep_links=False)
    except (OSError, zipfile.BadZipFile, KeyError) as exc:
        raise ValueError('Không đọc được Excel. Hãy lưu lại dạng .xlsx không có mật khẩu.') from exc
    rows, seen = [], set()
    try:
        for sheet in book:
            iterator = sheet.iter_rows()
            header = next(iterator, None)
            if not header or not any(c.value is not None for c in header):
                continue
            fields = [ALIASES.get(str(c.value or '').strip().casefold()) for c in header]
            known = [f for f in fields if f]
            if 'english' not in known:
                raise ValueError(f'Sheet {sheet.title}: cần cột english / tiếng Anh')
            if len(known) != len(set(known)):
                raise ValueError(f'Sheet {sheet.title}: tên cột trùng nhau')
            for index, cells in enumerate(iterator, 2):
                if not any(c.value is not None for c in cells):
                    continue
                if len(rows) >= 50000:
                    raise ValueError('Excel vượt quá 50.000 câu')
                row = {'key': f'excel/{sheet.title}/{index}', 'english':'', 'vietnamese':'', 'context':''}
                for field, cell in zip(fields, cells):
                    if not field:
                        continue
                    if cell.data_type == 'f':
                        raise ValueError(f'{sheet.title}, dòng {index}: dùng văn bản thay cho công thức')
                    if cell.value is not None and not isinstance(cell.value, str):
                        raise ValueError(f'{sheet.title}, dòng {index}: cột {field} phải là văn bản')
                    row[field] = cell.value or ''
                if not row['key'].strip() or row['key'] in seen:
                    raise ValueError(f'{sheet.title}, dòng {index}: key rỗng hoặc trùng')
                if not row['english'].strip():
                    raise ValueError(f'{sheet.title}, dòng {index}: tiếng Anh không được trống')
                seen.add(row['key']);rows.append(row)
    finally:
        book.close()
    if not rows:
        raise ValueError('Excel chưa có câu để nhập')
    return rows
