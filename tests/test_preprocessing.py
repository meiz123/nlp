import unittest
from localqa.preprocess import preprocess_rows,prepare_reading_pair,SECTIONS
class PreprocessTests(unittest.TestCase):
    def documents(self):
        en={'source_url':'same','question':'Question?','reading_title':'Title','drawn_cards':[{'card_name':'Star','orientation':'Upright'}],
            'dialogue':[{'speaker':'User','text':'Question?'}]+[{'speaker':'AI Reader','text':'Paragraph '+str(i)} for i in range(6)]}
        vi={'source_url':'same','question':'Câu hỏi?','cards':[{'name_en':'Star','name':'Ngôi Sao','orientation':'Xuôi'}],
            'interpretation':dict.fromkeys(SECTIONS,'Bản dịch...')}
        return en,vi
    def test_exact_text_kept_and_only_empty_pair_removed(self):
        rows,report=preprocess_rows([{'key':'a','english':' Hi {name}\n','vietnamese':' Chào ','extra':'ignore'}, {'key':'b','english':'','vietnamese':''}])
        self.assertEqual(rows[0]['english'],' Hi {name}\n');self.assertNotIn('extra',rows[0]);self.assertEqual(len(rows),1);self.assertEqual(report['output_rows'],1)
    def test_reading_pair_warns_mapping_truncation_and_missing_title(self):
        rows,report=prepare_reading_pair(*self.documents());self.assertEqual(len(rows),10)
        self.assertEqual(report['diagnostic_counts']['possibly_truncated_translation'],6)
        self.assertEqual(report['diagnostics'][0]['code'],'section_mapping_needs_confirmation')
        self.assertEqual(report['preprocessing']['duplicate_question_blocks_removed'],1)
        self.assertEqual([r for r in rows if r['key']=='/question'][0]['english'],'Question?')
    def test_mismatched_source_or_cards_not_guessed(self):
        for change in ('url','card'):
            en,vi=self.documents()
            if change=='url':vi['source_url']='other'
            else:vi['cards'][0]['name_en']='Fool'
            with self.assertRaises(ValueError):prepare_reading_pair(en,vi)
    def test_unknown_extra_content_or_section_not_silently_dropped(self):
        en,vi=self.documents();en['dialogue'].append({'speaker':'User','text':'Another question'})
        with self.assertRaises(ValueError):prepare_reading_pair(en,vi)
        en,vi=self.documents();vi['interpretation']['unknown']='Text'
        with self.assertRaises(ValueError):prepare_reading_pair(en,vi)
    def test_card_order_matches_english_identity(self):
        en,vi=self.documents();en['drawn_cards'].append({'card_name':'Fool','orientation':'Upright'});vi['cards'].insert(0,{'name_en':'Fool','name':'Kẻ Khờ','orientation':'Xuôi'})
        rows,_=prepare_reading_pair(en,vi);self.assertEqual(next(r['vietnamese'] for r in rows if r['key']=='/cards/Fool/name'),'Kẻ Khờ')
    def test_duplicate_key_and_nonstring_rejected(self):
        with self.assertRaises(ValueError):preprocess_rows([{'key':'a','english':1}])
        with self.assertRaises(ValueError):preprocess_rows([{'key':'a','english':'Hi'},{'key':'a','english':'Again'}])
