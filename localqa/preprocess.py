"""Local preprocessing for translation input; no model or source-file writes."""
from collections import Counter

SECTIONS=('introduction','analysis_seven_of_wands_and_tower','analysis_the_fool',
          'core_verdict','romantic_summary','advice')


def recognizes_reading_pair(en,vi):
    return isinstance(en,dict) and isinstance(vi,dict) and 'dialogue' in en and 'drawn_cards' in en and 'interpretation' in vi and 'cards' in vi


def preprocess_rows(rows):
    seen=set();prepared=[];diagnostics=[]
    for row in rows:
        if not isinstance(row,dict):raise ValueError('Mỗi dòng dữ liệu phải là object')
        key=row.get('key')
        if not isinstance(key,str) or not key.strip() or key in seen:raise ValueError('Key rỗng hoặc trùng trong dữ liệu đầu vào')
        seen.add(key)
        clean={'key':key}
        for field in ('english','vietnamese','context'):
            value=row.get(field,'')
            if not isinstance(value,str):raise ValueError(f'{key}: {field} phải là chuỗi')
            clean[field]=value
        if not (clean['english'].strip() or clean['vietnamese'].strip()):
            diagnostics.append({'code':'empty_pair_skipped','key':key,'message':'Bỏ dòng cả hai phía đều trống'})
            continue
        prepared.append(clean)
    return prepared,{'input_rows':len(rows),'output_rows':len(prepared),'diagnostics':diagnostics,
                     'preserves_original_text':True,'model_called':False}


def prepare_reading_pair(en,vi):
    if not recognizes_reading_pair(en,vi):raise ValueError('Chưa hỗ trợ cấu trúc cặp dữ liệu này')
    if en.get('source_url') and vi.get('source_url') and en['source_url']!=vi['source_url']:
        raise ValueError('Hai file không cùng nguồn reading; không tự ghép')
    if not isinstance(en['dialogue'],list) or not isinstance(en['drawn_cards'],list) or not isinstance(vi['cards'],list) or not isinstance(vi['interpretation'],dict):
        raise ValueError('Cấu trúc reading không hợp lệ')
    diagnostics=[];rows=[]
    def add(key,english,vietnamese,context='Tarot reading'):
        if not isinstance(english,str) or not isinstance(vietnamese,str):raise ValueError(f'{key}: nội dung phải là chuỗi')
        rows.append(dict(key=key,english=english,vietnamese=vietnamese,context=context))
        if not vietnamese.strip():diagnostics.append({'code':'missing_vietnamese','key':key,'message':'Chưa có bản Việt tương ứng; có thể dịch mới'})
        if vietnamese.rstrip().endswith(('...','…')):
            diagnostics.append({'code':'possibly_truncated_translation','key':key,'message':'Bản Việt kết thúc bằng dấu ba chấm; cần kiểm tra có bị cắt nội dung'})
    add('/question',en.get('question',''),vi.get('question',''))
    if en.get('reading_title'):add('/reading_title',en['reading_title'],vi.get('reading_title',''))
    targets={}
    for card in vi['cards']:
        if not isinstance(card,dict) or not isinstance(card.get('name_en'),str):raise ValueError('Lá bài Việt cần name_en để ghép chắc chắn')
        identity=card['name_en']
        if identity in targets:raise ValueError('Tên định danh lá bài bị trùng')
        targets[identity]=card
    source_names=[c.get('card_name') if isinstance(c,dict) else None for c in en['drawn_cards']]
    if any(not isinstance(x,str) or not x for x in source_names) or len(source_names)!=len(set(source_names)):raise ValueError('Tên định danh lá bài Anh rỗng hoặc trùng')
    if set(source_names)!=set(targets):raise ValueError('Hai file có danh sách lá bài khác nhau; không tự ghép')
    for card in en['drawn_cards']:
        identity=card['card_name'];target=targets[identity];key='/cards/'+identity.replace('~','~0').replace('/','~1')
        add(key+'/name',identity,target.get('name',''),'Tarot card name')
        add(key+'/orientation',card.get('orientation',''),target.get('orientation',''),'Tarot card orientation: '+identity)
    dialogue=en['dialogue']
    if any(not isinstance(x,dict) or not isinstance(x.get('text'),str) for x in dialogue):raise ValueError('Đoạn hội thoại cần text là chuỗi')
    readers=[x for x in dialogue if x.get('speaker')=='AI Reader']
    if len(readers)!=len(SECTIONS) or set(vi['interpretation'])!=set(SECTIONS):
        raise ValueError('Chưa có mapping tương ứng cho số đoạn/cấu trúc reading này; cần xác nhận mapping')
    # There are no shared IDs. This mapping is surfaced as a warning, not a
    # semantic alignment claim or a machine-approved translation label.
    for section,block in zip(SECTIONS,readers):
        add('/interpretation/'+section,block['text'],vi['interpretation'][section],
            'Tarot reading; ghép theo mapping section và thứ tự 6 đoạn AI Reader, cần xác nhận')
    diagnostics.insert(0,{'code':'section_mapping_needs_confirmation','key':'/interpretation','message':'6 đoạn không có ID chung; xác nhận mapping theo thứ tự trước khi kiểm tra ngôn ngữ'})
    user_blocks=[x for x in dialogue if x.get('speaker')!='AI Reader']
    if any(x.get('speaker')!='User' or x['text']!=en.get('question') for x in user_blocks):
        raise ValueError('Có đoạn hội thoại chưa được mapping; không bỏ qua nội dung chưa xác định')
    prepared,stats=preprocess_rows(rows)
    return prepared,{'format':'reading_dialogue_interpretation','paired_rows':len(prepared),'diagnostics':diagnostics,
                     'diagnostic_counts':dict(Counter(x['code'] for x in diagnostics)),
                     'preprocessing':{**stats,'duplicate_question_blocks_removed':len(user_blocks),
                                      'excluded_metadata':['source_url','speaker','role','card_number','position','name_en','card_name_original'],
                                      'section_mapping':dict(zip(SECTIONS,[i for i,x in enumerate(dialogue) if x.get('speaker')=='AI Reader']))}}
