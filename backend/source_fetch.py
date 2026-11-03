import html
from html.parser import HTMLParser
import ipaddress
import json
import re
import socket
import urllib.request
from urllib.parse import urlsplit


def public_url(url):
    p=urlsplit(url)
    if p.scheme not in ('http','https') or not p.hostname or p.username or p.password: raise ValueError('只读取公开HTTP/HTTPS原文链接')
    for info in socket.getaddrinfo(p.hostname,p.port or (443 if p.scheme=='https' else 80),type=socket.SOCK_STREAM):
        if not ipaddress.ip_address(info[4][0]).is_global: raise ValueError('原文链接不能指向本机或内网')
    return url


class Redirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        public_url(newurl)
        return super().redirect_request(req,fp,code,msg,headers,newurl)


class Text(HTMLParser):
    def __init__(self): super().__init__();self.parts=[];self.skip=0;self.active=0;self.stack=[];self.fragment=False
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        void=tag in ('br','img','input','meta','link','hr','source','wbr','area','base','embed','param','track','col')
        skip=tag in ('script','style','nav','noscript','footer')
        chosen=tag=='article' or attrs.get('id')=='js_content' or any(x in attrs.get('class','').split() for x in ['article-content','article_content','rich_media_content','content-body'])
        if skip:self.skip+=1
        if chosen:self.active+=1
        if not void:self.stack.append((tag,skip,chosen))
        if self.active and tag in ('p','div','br','h1','h2','li'): self.parts.append('\n')
    def handle_endtag(self,tag):
        if self.active and tag in ('p','div','br','h1','h2','li'): self.parts.append('\n')
        found=next((i for i in range(len(self.stack)-1,-1,-1) if self.stack[i][0]==tag),None)
        if found is not None:
            removed=self.stack[found:];self.stack=self.stack[:found]
            self.skip=max(0,self.skip-sum(s for _,s,_ in removed))
            self.active=max(0,self.active-sum(a for _,_,a in removed))
    def handle_data(self,data):
        if self.active and not self.skip: self.parts.append(data)


def clean(markup):
    parser=Text();parser.active=1;parser.feed(markup)
    return '\n'.join(x.strip() for x in ''.join(parser.parts).splitlines() if x.strip())


def fetch_source(url):
    public_url(url)
    req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0','Accept':'text/html,application/xhtml+xml'})
    with urllib.request.build_opener(Redirect()).open(req,timeout=25) as r:
        raw=r.read(5*1024*1024+1)
        if len(raw)>5*1024*1024: raise ValueError('网页过大，请手动补充正文')
        text=raw.decode(r.headers.get_content_charset() or 'utf8','replace')
    candidates=[]
    def collect(o,depth=0):
        if depth>16:return
        if isinstance(o,dict):
            for k,v in o.items():
                if k.lower() in ('content','articlecontent','article_content','body') and isinstance(v,str) and ('<p' in v or len(v)>150): candidates.append(clean(v))
                elif isinstance(v,(dict,list)):collect(v,depth+1)
        elif isinstance(o,list):
            for v in o[:1000]:collect(v,depth+1)
    for m in re.finditer(r'(?:window\.)?(?:__INITIAL_STATE__|__ROUTER_DATA__|__NEXT_DATA__)\s*=\s*',text):
        try: collect(json.JSONDecoder().raw_decode(text[m.end():])[0])
        except ValueError: pass
    for m in re.finditer(r'<script[^>]*type=["\']application/(?:ld\+)?json["\'][^>]*>(.*?)</script>',text,re.S|re.I):
        try: collect(json.loads(html.unescape(m.group(1))))
        except ValueError: pass
    parser=Text();parser.feed(text)
    rendered='\n'.join(x.strip() for x in ''.join(parser.parts).splitlines() if x.strip())
    if rendered: candidates.append(rendered)
    candidates=[c for c in candidates if len(c)>=60]
    if not candidates: raise ValueError('网页没有可直接提取的正文，请打开原文后粘贴；未用标题代替全文')
    return max(candidates,key=len)[:100000]
