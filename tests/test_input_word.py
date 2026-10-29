import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as ET

from localqa.input_word import W, load_word


def paragraph(text):
    p = ET.Element(W + 'p')
    for index, line in enumerate(text.split('\n')):
        run = ET.SubElement(p, W + 'r')
        if index:
            ET.SubElement(run, W + 'br')
        ET.SubElement(run, W + 't').text = line
    return p


def document(path, paragraphs=(), table=None):
    root = ET.Element(W + 'document');body = ET.SubElement(root, W + 'body')
    for text in paragraphs:body.append(paragraph(text))
    if table is not None:
        t = ET.SubElement(body, W + 'tbl')
        for row in table:
            tr = ET.SubElement(t, W + 'tr')
            for value in row:
                cell = ET.SubElement(tr, W + 'tc');cell.append(paragraph(value))
    with zipfile.ZipFile(path, 'w') as z:z.writestr('word/document.xml', ET.tostring(root, encoding='utf-8'))


class WordInputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory();self.path = Path(self.temp.name) / 'pairs.docx'
    def tearDown(self):self.temp.cleanup()
    def test_table_exact_text_and_empty_translation(self):
        document(self.path, table=[['key','english','vietnamese','context'],['a','Hello %1$s\nAgain',' Chào %1$s\nLại ','Greeting'],['b','Save','','']])
        rows = load_word(self.path)
        self.assertEqual(rows[0],dict(key='a',english='Hello %1$s\nAgain',vietnamese=' Chào %1$s\nLại ',context='Greeting'))
        self.assertEqual(rows[1]['vietnamese'],'')
    def test_vietnamese_headers(self):
        document(self.path, table=[['Mã câu','Tiếng Anh','Tiếng Việt','Ngữ cảnh'],['a','Save','Lưu','Nút']])
        self.assertEqual(load_word(self.path)[0]['context'],'Nút')
    def test_labeled_paragraphs_and_continuations(self):
        document(self.path, paragraphs=['Key: a','EN: Hello %s\nAgain','VI: Chào %s','Dòng tiếp theo','Context: Greeting','Key: b','English: Save','Vietnamese: Lưu'])
        rows=load_word(self.path)
        self.assertEqual(rows[0]['english'],'Hello %s\nAgain')
        self.assertEqual(rows[0]['vietnamese'],'Chào %s\nDòng tiếp theo')
        self.assertEqual(rows[1]['key'],'b')
    def test_rejects_narrative_and_missing_fields(self):
        for paragraphs in [['Save means Lưu.'],['Key: a','English: Save']]:
            document(self.path, paragraphs=paragraphs)
            with self.assertRaises(ValueError):load_word(self.path)
    def test_duplicate_and_bad_table(self):
        cases=[
            [['key','english','vietnamese'],['a','Save','Lưu'],['a','Again','Lại']],
            [['key','english','vietnamese'],['a','Save']],
            [['key','english','vietnamese'],['a','','Lưu']],
            [['key','english','english','vietnamese'],['a','Save','Save','Lưu']],
        ]
        for table in cases:
            document(self.path,table=table)
            with self.assertRaises(ValueError):load_word(self.path)
    def test_corrupt_or_unsafe_xml(self):
        self.path.write_bytes(b'not a zip')
        with self.assertRaises(ValueError):load_word(self.path)
        with zipfile.ZipFile(self.path,'w') as z:z.writestr('word/document.xml','<!DOCTYPE a [<!ENTITY x "x">]><a/>')
        with self.assertRaises(ValueError):load_word(self.path)
    def test_legacy_without_converter_is_actionable(self):
        path=self.path.with_suffix('.doc');path.write_bytes(b'legacy')
        with patch('localqa.input_word.shutil.which',return_value=None):
            with self.assertRaisesRegex(ValueError,'Save As .docx'):load_word(path)
    def test_legacy_conversion_does_not_modify_source(self):
        path=self.path.with_suffix('.doc');path.write_bytes(b'legacy')
        def fake_run(command,**kwargs):
            self.assertFalse(kwargs.get('shell',False));self.assertEqual(kwargs['timeout'],60)
            target=Path(command[command.index('-output')+1])
            document(target,table=[['key','english','vietnamese'],['a','Save','Lưu']])
            return type('Done',(),{'returncode':0})()
        with patch('localqa.input_word.sys.platform','darwin'),patch('localqa.input_word.shutil.which',side_effect=lambda name:'/usr/bin/textutil' if name=='textutil' else None),patch('localqa.input_word.subprocess.run',side_effect=fake_run):
            self.assertEqual(load_word(path)[0]['english'],'Save')
        self.assertEqual(path.read_bytes(),b'legacy')
    def test_large_member_guard(self):
        document(self.path,table=[['key','english','vietnamese'],['a','Save','Lưu']])
        with patch('localqa.input_word.MAX_DOCUMENT_BYTES',1):
            with self.assertRaisesRegex(ValueError,'quá lớn'):load_word(self.path)

if __name__=='__main__':unittest.main()
