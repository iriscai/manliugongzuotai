"""Bounded transport retries; quota, invalid credentials and content errors stay distinct."""
import random

def transient(error):
    status=getattr(error,'status',None)
    if status in (408,425,429) or isinstance(status,int) and 500<=status<=599:return True
    text=str(error).lower()
    return any(x in text for x in ('overloaded','upstream_error','server_error','service_unavailable','bad_gateway','gateway_timeout','stream was interrupted','server disconnected',
       'incomplete chunked read','unexpected_eof','eof occurred in violation','handshake operation timed out',
       'read operation timed out','网络请求失败或等待超时','流式响应提前结束','gateway_concurrency_limit',
       'concurrency limit exceeded','temporarily unavailable','connection reset'))

def delay_for(attempt,error):
    delay=(5,15,45)[min(2,max(0,attempt-1))]+random.uniform(0,.8)
    retry_after=getattr(error,'retry_after',None)
    if isinstance(retry_after,(int,float)):delay=max(delay,retry_after)
    return min(60,delay)
