"""One live extraction smoke test; isolated from the user's production library."""
from pathlib import Path
import json
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from providers import Providers,local_config
from schemas import EXTRACT
p=Providers();settings={'provider':'codex','timeout':600}
source='社区图书角每天18时至20时开放。借书需登记书名和日期，还书后划掉对应记录。本条是虚构测试素材，不需联网。'
prompt='这是桌面工具的一次简短提炼接口测试，不是代码开发任务。只输出schema JSON，不调用其他工具，不修改任何Skill或文件，不评审、不评分。原文：'+source+'\n提炼生活类重点、最多2条facts，quote必须是原文逐字子串；无新增事实，needs_verification与verified_additions为空，eligible为true。'
r=p.call(prompt,EXTRACT,settings,ROOT/'build/live-codex-smoke')
assert r.get('eligible') is True and r.get('facts')
assert all(x['quote'] in source for x in r['facts'])
report={'ok':True,'provider':'local_codex','configuration':local_config(),'calls':1,'quote_check':True,'scope':'One isolated live extraction; no production materials were processed and no generated images were claimed.'}
(ROOT/'build/live-codex-smoke/report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps(report,ensure_ascii=False))
