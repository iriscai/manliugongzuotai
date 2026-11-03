"""Check the paragraph/image contract without spending model requests."""
import sys,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
from article_flow import normalize_article
from writing_prompts import COMMON_RULE
for count in [8,9,12,15]:
    lines=[f'孩子讲到第{i}句。' for i in range(1,count+1)]
    for separator in ['\n','\r\n','\n\n']:
        result,length,images=normalize_article({'category':'生活','title':'讲故事','article':separator.join(lines)},'生活')
        assert result['article']=='\n\n'.join(lines) and result['paragraph_count']==count
        assert result['planned_image_count']==count and result['actual_images']==images==0
for count in [1,7,16]:
    try:normalize_article({'category':'生活','title':'标题','article':'\n\n'.join(['完整短句。']*count)},'生活');raise AssertionError('Wrong paragraph count accepted')
    except ValueError as exc:assert '8至15' in str(exc)
for heading in ['【事情起因】','## 起因','第一段：起因']:
    try:normalize_article({'category':'生活','title':'标题','article':'\n\n'.join([heading]+['完整短句。']*7)},'生活');raise AssertionError('Section heading accepted')
    except ValueError as exc:assert '小标题' in str(exc)
body='\n\n'.join(['完整短句。']*8)
for title in ['字'*64,'字'*31+' '+'字'*32,'🙂'*64]:
    result,_,_=normalize_article({'category':'生活','title':title,'article':body},'生活');assert result['title']==title
for title in ['字'*65,'字'*32+' '+'字'*32,'🙂'*65]:
    try:normalize_article({'category':'生活','title':title,'article':body},'生活');raise AssertionError('Overlong title accepted')
    except ValueError as exc:assert '64字符上限' in str(exc)
assert '全文默认3至5' not in COMMON_RULE and '改成10张以内漫画' not in COMMON_RULE
assert '正文必须写成8至15个自然段' in COMMON_RULE
print(json.dumps({'ok':True,'paragraph_range':[8,15],'headings_rejected':True,'single_and_double_line_breaks_normalized':True,'planned_images_match_paragraphs':True,'actual_images_generated':0,'model_calls':0},ensure_ascii=False))
