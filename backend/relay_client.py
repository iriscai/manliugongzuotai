"""Chat transport adapted from FunnyComicTitleGenerator/core.py GPTClient.
Only transport, key rotation and model discovery are reused; no writing prompts.
"""
from __future__ import annotations
from dataclasses import dataclass
import json
from pathlib import Path
import sys
import threading
from urllib.parse import urlsplit

vendor=Path(__file__).resolve().parent/'vendor'
if vendor.is_dir():sys.path.insert(0,str(vendor))
import httpx

REFERENCE_CONFIG=Path('D:/BIGDATA/CODES/PyCharmFiles/大富豪/FunnyComicTitleGenerator/config/system.json')

def normalize_keys(value):
    values=value if isinstance(value,list) else [value or '']
    return tuple(dict.fromkeys(line.strip() for item in values for line in str(item).splitlines() if line.strip()))

def completion_url(base_url):
    url=base_url.strip().rstrip('/')
    return url if url.endswith('/chat/completions') else url+'/chat/completions'

def models_url(base_url):
    url=base_url.strip().rstrip('/')
    for suffix in ['/chat/completions','/responses']:
        if url.endswith(suffix):url=url[:-len(suffix)]
    return url if url.endswith('/models') else url+'/models'

class RelayError(RuntimeError):
    def __init__(self,message,status=None):super().__init__(message);self.status=status
class RelayLimit(RelayError):pass
class RelayRateLimit(RelayLimit):pass

def is_quota_error(value):
    text=(value if isinstance(value,str) else json.dumps(value,ensure_ascii=False)).lower()
    return any(marker in text for marker in ('insufficient_user_quota','insufficient_quota','quota_exceeded','quota_not_enough','billing_hard_limit_reached','insufficient_balance','insufficient credits','insufficient credit','insufficient funds','credit balance is too low','exceeded your current quota','account quota exceeded','余额不足','额度不足','配额不足','余额已用尽','余额耗尽'))

def is_rate_error(value):
    text=(value if isinstance(value,str) else json.dumps(value,ensure_ascii=False)).lower()
    return any(x in text for x in ('gateway_concurrency_limit','rate_limit_error','rate_limit_exceeded','too_many_requests','concurrency limit exceeded'))

@dataclass
class RelayConfig:
    base_url:str
    api_key:str
    model:str
    temperature:float=.7
    read_timeout:int=300
    skip_tls_verify:bool=False
    @property
    def api_keys(self):return normalize_keys(self.api_key)

class RelayClient:
    def __init__(self,config):
        self.config=config;self._key_lock=threading.Lock();self._key_index=0
        self._active_lock=threading.Lock();self._active={};self._local=threading.local()

    @property
    def partial_parts(self):return getattr(self._local,'partial_parts',[])

    @partial_parts.setter
    def partial_parts(self,value):self._local.partial_parts=value

    @property
    def last_usage(self):return getattr(self._local,'usage',{})

    def validate(self,require_model=True):
        parsed=urlsplit(self.config.base_url.strip())
        if parsed.scheme not in ('https','http') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise RelayError('请填写有效API基础地址，不包含用户名、密码或查询参数')
        if not self.config.api_keys:raise RelayError('请先填写API Keys，每行一个')
        if require_model and not self.config.model.strip():raise RelayError('请先填写模型名称')

    def redact(self,text):
        text=str(text)
        for key in sorted(self.config.api_keys,key=len,reverse=True):text=text.replace(key,'[密钥已隐藏]')
        return text

    def _next_api_key(self):
        keys=self.config.api_keys
        if not keys:raise RelayError('API Key不能为空')
        with self._key_lock:
            key=keys[self._key_index%len(keys)];self._key_index+=1
        return key

    def _headers(self,key=None):
        return {'Authorization':'Bearer '+(key or self._next_api_key()),'Content-Type':'application/json','User-Agent':'FunnyComicTitleGenerator/1.0'}

    def _check_status(self,response):
        if response.status_code==200:return
        detail=self.redact(response.read().decode('utf8','replace')[:2000])
        kind=RelayLimit if response.status_code==402 or is_quota_error(detail) else RelayRateLimit if response.status_code==429 else RelayError
        error=kind(f'中转API请求失败 HTTP {response.status_code}：{detail[:700]}',response.status_code)
        try:error.retry_after=min(60,max(0,float(response.headers.get('Retry-After','0'))))
        except ValueError:pass
        raise error

    @staticmethod
    def _content(value):
        if isinstance(value,list):return ''.join(str(item.get('text','')) if isinstance(item,dict) else str(item) for item in value)
        return str(value or '')

    def _json_answer(self,data):
        self._local.usage=data.get('usage') or {}
        if data.get('error'):raise (RelayLimit if is_quota_error(data['error']) else RelayRateLimit if is_rate_error(data['error']) else RelayError)(self.redact(data['error']))
        choice=(data.get('choices') or [{}])[0] or {}
        if choice.get('finish_reason') in ('length','content_filter','error'):raise RelayError('API输出被截断或未正常完成')
        answer=self._content((choice.get('message') or {}).get('content') or choice.get('text')).strip()
        if not answer:raise RelayError('模型没有返回有效文本')
        return answer

    def _read_stream(self,response,stop_event,progress):
        parts=[];received=0;next_notice=500;finished=False
        self.partial_parts=parts
        for line in response.iter_lines():
            if stop_event.is_set():raise RelayError('API任务已停止')
            text=line.decode('utf8','ignore') if isinstance(line,bytes) else line
            text=text.strip()
            if not text.startswith('data:'):continue
            payload=text[5:].strip()
            if payload=='[DONE]':finished=True;break
            try:data=json.loads(payload)
            except json.JSONDecodeError:continue
            if not isinstance(data,dict):continue
            if data.get('usage'):self._local.usage=data['usage']
            if data.get('error'):raise (RelayLimit if is_quota_error(data['error']) else RelayRateLimit if is_rate_error(data['error']) else RelayError)(self.redact(data['error']))
            choices=data.get('choices') or []
            if not choices:continue
            first=choices[0] or {};reason=first.get('finish_reason')
            if reason in ('length','content_filter','error'):raise RelayError('API输出被截断或未正常完成')
            if reason is not None:finished=True
            content=(first.get('delta') or {}).get('content')
            if content is None:content=(first.get('message') or {}).get('content') or first.get('text')
            piece=self._content(content)
            if piece:
                parts.append(piece);received+=len(piece)
                if received>8*1024*1024:raise RelayError('API输出超过单次接收上限')
                if received>=next_notice:progress(f'中转API已接收约{received}字符');next_notice+=500
        answer=''.join(parts).strip()
        if not answer:raise RelayError('模型没有返回有效文本')
        if not finished:raise RelayError('流式响应提前结束，未作为完整结果入库')
        return answer

    def complete(self,prompt,stop_event,progress,system_message):
        self.validate()
        self.partial_parts=[]
        self._local.usage={}
        body={'model':self.config.model,'messages':[{'role':'system','content':system_message},{'role':'user','content':prompt}],'temperature':self.config.temperature,'stream':True}
        timeout=httpx.Timeout(30.0,read=float(self.config.read_timeout),write=90.0,pool=30.0)
        try:
            with httpx.Client(verify=not self.config.skip_tls_verify,timeout=timeout) as client:
                with client.stream('POST',completion_url(self.config.base_url),headers=self._headers(),json=body) as response:
                    with self._active_lock:self._active[id(response)]=response
                    try:
                        self._check_status(response)
                        if 'application/json' in response.headers.get('content-type','').lower():
                            raw=response.read()
                            if len(raw)>8*1024*1024:raise RelayError('API输出超过单次接收上限')
                            return self._json_answer(json.loads(raw))
                        return self._read_stream(response,stop_event,progress)
                    finally:
                        with self._active_lock:self._active.pop(id(response),None)
        except (httpx.RequestError,httpx.TimeoutException) as error:raise RelayError('网络请求失败或等待超时：'+self.redact(error)) from None

    def test(self):
        self.validate()
        body={'model':self.config.model,'messages':[{'role':'user','content':'只回复 OK'}],'temperature':0,'stream':False}
        for index,key in enumerate(self.config.api_keys,1):
            try:
                with httpx.Client(verify=not self.config.skip_tls_verify,timeout=httpx.Timeout(30.0)) as client:
                    response=client.post(completion_url(self.config.base_url),headers=self._headers(key),json=body)
                    self._check_status(response);self._json_answer(response.json())
            except (RelayError,httpx.RequestError,ValueError) as error:return {'ok':False,'message':f'第{index}个Key测试失败：'+self.redact(error)}
        return {'ok':True,'message':f'连接成功：{self.config.model}，已验证{len(self.config.api_keys)}个Key','key_count':len(self.config.api_keys)}

    def models(self):
        self.validate(False);seen=[];errors=[]
        for index,key in enumerate(self.config.api_keys,1):
            try:
                with httpx.Client(verify=not self.config.skip_tls_verify,timeout=30,follow_redirects=True) as client:
                    response=client.get(models_url(self.config.base_url),headers=self._headers(key));self._check_status(response)
                    data=response.json()
                    for item in data.get('data',[]):
                        model=str(item.get('id','')).strip() if isinstance(item,dict) else ''
                        if model and model not in seen:seen.append(model)
            except (RelayError,httpx.RequestError,ValueError) as error:errors.append(f'第{index}个Key：'+self.redact(error))
        if not seen:raise RelayError('拉取模型列表失败：'+'；'.join(errors[:3]))
        return {'models':seen,'errors':errors}

    def terminate(self):
        with self._active_lock:active=list(self._active.values())
        for response in active:
            try:response.close()
            except Exception:pass
