import tempfile,unittest
from pathlib import Path
from openpyxl import Workbook
from localqa.input_excel import load_excel
class ExcelTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'data.xlsx'
    def tearDown(self):self.tmp.cleanup()
    def write(self,rows):
        w=Workbook();s=w.active
        for r in rows:s.append(r)
        w.save(self.path);w.close()
    def test_english_only_preserves_tokens_and_newlines(self):
        self.write([['english','context'],['Hello {name}\nAgain','Greeting']]);r=load_excel(self.path)[0]
        self.assertEqual(r['english'],'Hello {name}\nAgain');self.assertEqual(r['vietnamese'],'');self.assertTrue(r['key'])
    def test_bilingual_vietnamese_headers(self):
        self.write([['Mã câu','Tiếng Anh','Tiếng Việt'],['a','Save',' Lưu ']])
        self.assertEqual(load_excel(self.path)[0]['vietnamese'],' Lưu ')
    def test_rejects_duplicate_formula_numbers_and_blank_source(self):
        for rows in [
            [['key','english'],['a','Save'],['a','Cancel']],
            [['english'],['=HYPERLINK("https://example.com")']],
            [['english'],[12]], [['english','context'],['','context']],
            [['english','english'],['Save','Cancel']]]:
            self.write(rows)
            with self.assertRaises(ValueError):load_excel(self.path)
    def test_multi_sheet_keys_are_unique(self):
        w=Workbook();w.active.append(['english']);w.active.append(['Save']);s=w.create_sheet('Other');s.append(['english']);s.append(['Cancel']);w.save(self.path);w.close()
        rows=load_excel(self.path);self.assertEqual(len(rows),2);self.assertNotEqual(rows[0]['key'],rows[1]['key'])
    def test_legacy_xls_has_actionable_message(self):
        with self.assertRaisesRegex(ValueError,'Save As'):load_excel(self.path.with_suffix('.xls'))
