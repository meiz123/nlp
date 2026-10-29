import tempfile,unittest
from pathlib import Path
from localqa.core import Project,technical,load_csv,fingerprint,export_rows
class Tests(unittest.TestCase):
    def test_placeholders(self):
        self.assertIn('Placeholder không khớp',technical('%1$s %1$s','%1$s'))
        self.assertEqual(technical('Progress 100%% {name}','Tiến độ 100%% {name}'),[])
    def test_portability_and_invalidation(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'test.lqa';p=Project(path)
            rows=[{'key':'a','english':'Save','vietnamese':'Lưu'}];p.import_rows(rows);p.approve('a','Lưu');p.close()
            p=Project(path);self.assertEqual(p.rows()[0]['approved'],'Lưu')
            p.import_rows(rows);self.assertEqual(p.rows()[0]['reviewed'],1)
            rows[0]['english']='Save now';p.import_rows(rows);self.assertEqual(p.rows()[0]['reviewed'],0);self.assertIsNone(p.rows()[0]['approved']);p.close()
    def test_cache_context(self):
        r={'english':'a','vietnamese':'b','context':''}
        self.assertNotEqual(fingerprint(r,'m','a'),fingerprint(r,'m','b'))
    def test_csv_and_export(self):
        with tempfile.TemporaryDirectory() as d:
            csv=Path(d)/'in.csv';csv.write_text('key,english,vietnamese\na,Save,Lưu\na,Again,Lại',encoding='utf-8')
            with self.assertRaises(ValueError):load_csv(csv)
            p=Project(Path(d)/'test.lqa');p.import_rows([{'key':'a','english':'=1+1','vietnamese':'x'}]);export_rows(p,Path(d)/'out.csv')
            self.assertIn("'=1+1",(Path(d)/'out.csv').read_text(encoding='utf-8-sig'));p.close()
if __name__=='__main__':unittest.main()
