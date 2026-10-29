import csv, hashlib, json, re, sqlite3
from collections import Counter
from pathlib import Path

PROMPT_VERSION = '2'
TOKEN = re.compile(r'%(?:\d+\$)?[-#+ 0,(]*\d*(?:\.\d+)?[a-zA-Z]|\{[a-zA-Z_][\w.]*\}|\{\d+\}')

def technical(en, vi):
    issues = []
    if not vi.strip(): issues.append('Thiếu bản dịch tiếng Việt')
    if Counter(TOKEN.findall(en.replace('%%', ''))) != Counter(TOKEN.findall(vi.replace('%%', ''))):
        issues.append('Placeholder không khớp')
    if vi != vi.strip(): issues.append('Khoảng trắng thừa ở đầu/cuối')
    if en.count('\n') != vi.count('\n'): issues.append('Số dòng khác câu nguồn; cần kiểm tra bố cục')
    return issues

def load_csv(path):
    from .data import load_paired_csv
    return load_paired_csv(path)

class Project:
    def __init__(self, path):
        self.path = str(path)
        self.db = sqlite3.connect(path)
        self.db.executescript('''CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT);
        CREATE TABLE IF NOT EXISTS rows(key TEXT PRIMARY KEY,english TEXT,vietnamese TEXT,context TEXT DEFAULT '',result TEXT,approved TEXT,reviewed INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS cache(hash TEXT PRIMARY KEY,result TEXT);''')
        self.db.execute("INSERT OR IGNORE INTO meta VALUES('schema','1')")
        version = self.db.execute("SELECT value FROM meta WHERE key='schema'").fetchone()[0]
        if version not in ('1', '2'):
            self.db.close()
            raise ValueError('Phiên bản project chưa được hỗ trợ')
        # Additive migration keeps existing approved translations and review flags.
        with self.db:
            columns = {row[1] for row in self.db.execute('PRAGMA table_info(rows)')}
            if 'notes' not in columns:
                self.db.execute("ALTER TABLE rows ADD COLUMN notes TEXT NOT NULL DEFAULT ''")
            self.db.execute('''CREATE TABLE IF NOT EXISTS backend_results(
                key TEXT NOT NULL, backend TEXT NOT NULL, result TEXT NOT NULL,
                PRIMARY KEY(key, backend), FOREIGN KEY(key) REFERENCES rows(key))''')
            self.db.execute("UPDATE meta SET value='2' WHERE key='schema'")
    def close(self): self.db.close()
    def setting(self,k,default=''):
        row=self.db.execute('SELECT value FROM meta WHERE key=?',(k,)).fetchone()
        return row[0] if row else default
    def set_setting(self,k,v):
        self.db.execute('INSERT OR REPLACE INTO meta VALUES(?,?)',(k,v)); self.db.commit()
    def import_rows(self,rows):
        with self.db:
            for r in rows:
                old=self.db.execute('SELECT english,vietnamese,context FROM rows WHERE key=?',(r['key'],)).fetchone()
                vals=(r['english'],r['vietnamese'],r.get('context','') or '')
                if old is None: self.db.execute('INSERT INTO rows(key,english,vietnamese,context) VALUES(?,?,?,?)',(r['key'],*vals))
                elif tuple(old)!=vals:
                    self.db.execute("UPDATE rows SET english=?,vietnamese=?,context=?,result=NULL,approved=NULL,reviewed=0,notes='' WHERE key=?",(*vals,r['key']))
                    self.db.execute('DELETE FROM backend_results WHERE key=?',(r['key'],))
    def rows(self):
        self.db.row_factory=sqlite3.Row
        result=[dict(r) for r in self.db.execute('SELECT * FROM rows ORDER BY rowid')]
        self.db.row_factory=None
        return result
    def save_result(self,key,result):
        self.db.execute('UPDATE rows SET result=?,reviewed=0 WHERE key=?',(json.dumps(result,ensure_ascii=False),key)); self.db.commit()
    def _require_key(self, key):
        if self.db.execute('SELECT 1 FROM rows WHERE key=?', (key,)).fetchone() is None:
            raise KeyError(key)
    def set_reviewed(self, key, reviewed):
        self._require_key(key)
        self.db.execute('UPDATE rows SET reviewed=? WHERE key=?', (int(bool(reviewed)), key))
        self.db.commit()
    def save_notes(self, key, text):
        self._require_key(key)
        if not isinstance(text, str): raise TypeError('Ghi chú phải là chuỗi')
        self.db.execute('UPDATE rows SET notes=? WHERE key=?', (text, key))
        self.db.commit()
    def save_feedback(self, key, reviewed, notes, approved_text=None):
        """None keeps the approved target; an empty string explicitly clears it."""
        self._require_key(key)
        if not isinstance(notes, str): raise TypeError('Ghi chú phải là chuỗi')
        if approved_text is not None and not isinstance(approved_text, str):
            raise TypeError('Bản sửa phải là chuỗi')
        with self.db:
            self.db.execute('UPDATE rows SET reviewed=?,notes=? WHERE key=?',
                            (int(bool(reviewed)), notes, key))
            if approved_text is not None:
                self.db.execute('UPDATE rows SET approved=? WHERE key=?', (approved_text, key))
    def approve(self,key,text):
        self._require_key(key)
        if not isinstance(text, str) or not text.strip():
            raise ValueError('Bản sửa đã duyệt không được trống')
        self.db.execute('UPDATE rows SET approved=?,reviewed=1 WHERE key=?',(text,key));self.db.commit()
    def save_backend_result(self, key, backend, result):
        self._require_key(key)
        if backend not in ('local', 'gemini', 'comparison'): raise ValueError('Backend không được hỗ trợ')
        if not isinstance(result, dict): raise TypeError('Kết quả phải là object')
        self.db.execute('INSERT OR REPLACE INTO backend_results VALUES(?,?,?)',
                        (key, backend, json.dumps(result, ensure_ascii=False)))
        self.db.commit()
    def backend_results(self, key):
        self._require_key(key)
        return {backend: json.loads(value) for backend, value in self.db.execute(
            'SELECT backend,result FROM backend_results WHERE key=?', (key,))}
    def save_comparison(self, key, result):
        self.save_backend_result(key, 'comparison', result)
    def get_comparison(self, key):
        return self.backend_results(key).get('comparison')
    def cached(self,h):
        r=self.db.execute('SELECT result FROM cache WHERE hash=?',(h,)).fetchone()
        return json.loads(r[0]) if r else None
    def cache(self,h,result):
        self.db.execute('INSERT OR REPLACE INTO cache VALUES(?,?)',(h,json.dumps(result,ensure_ascii=False)));self.db.commit()

def fingerprint(row,model,context):
    return hashlib.sha256(json.dumps([PROMPT_VERSION,model,context,row['english'],row['vietnamese'],row['context']],ensure_ascii=False).encode()).hexdigest()

def export_rows(project,path):
    fields=['key','english','vietnamese','context','status','issues','reason','suggestion','approved_translation','reviewed','notes']
    rows=[]
    for r in project.rows():
        result=json.loads(r['result']) if r['result'] else {}
        rows.append([r['key'],r['english'],r['vietnamese'],r['context'],result.get('status','Chưa kiểm tra'),' | '.join(result.get('issues',[])),result.get('reason',''),result.get('suggestion',''),r['approved'] or '',bool(r['reviewed']),r['notes']])
    if Path(path).suffix.lower()=='.xlsx':
        from openpyxl import Workbook
        w=Workbook();s=w.active;s.title='Localization QA';s.append(fields)
        for row in rows:
            s.append(row)
            for c in s[s.max_row]:
                if isinstance(c.value,str): c.data_type='s'
        s.freeze_panes='A2';s.auto_filter.ref=s.dimensions;w.save(path)
    else:
        with open(path,'w',encoding='utf-8-sig',newline='') as f:
            writer=csv.writer(f);writer.writerow(fields)
            for row in rows:
                writer.writerow(["'"+v if isinstance(v,str) and v.startswith(('=','+','-','@')) else v for v in row])


def export_training(project, path):
    """Export approved feedback, never suggestions/notes as the answer. No training runs."""
    records = []
    for row in project.rows():
        target = row['approved']
        if not row['reviewed'] or not isinstance(target, str) or not target.strip():
            continue
        errors = technical(row['english'], target)
        if 'Placeholder không khớp' in errors:
            raise ValueError(f"{row['key']}: placeholder trong bản sửa đã duyệt không khớp")
        records.append({
            'input': {'english': row['english'], 'vietnamese_current': row['vietnamese'],
                      'context': row['context']},
            'output': {'vietnamese': target},
            'metadata': {'key': row['key'], 'review_notes': row['notes'],
                         'human_approved': True},
        })
    destination = Path(path)
    if destination.resolve() == Path(project.path).resolve():
        raise ValueError('Không được ghi đè file project bằng dữ liệu huấn luyện')
    # Validate all candidates before opening the destination, so failure does not
    # truncate an existing training dataset.
    with destination.open('w', encoding='utf-8', newline='') as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False) + '\n')
    return len(records)
