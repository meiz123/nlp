import json,tempfile,unittest
from pathlib import Path
from localqa.input_json import load_json,resolve_json_pair,SingleLanguageJSONError
class ReadingImportFlowTests(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def files(self):
        en=self.root/'tarot_reading_exact_en.json';vi=self.root/'gemini-code-123.json'
        en.write_text(json.dumps({'dialogue':[],'drawn_cards':[]}));vi.write_text(json.dumps({'interpretation':{},'cards':[]}));return en,vi
    def test_single_english_routes_to_counterpart_instead_of_invalid_record(self):
        en,_=self.files()
        with self.assertRaises(SingleLanguageJSONError):load_json(en)
    def test_schema_pair_resolves_arbitrary_target_filename_and_reverse_selection(self):
        en,vi=self.files();self.assertEqual(resolve_json_pair([vi,en]),(en,vi));self.assertEqual(resolve_json_pair([en,vi]),(en,vi))
