"""Customer-facing links, independent of retrieval and retained source metadata."""
import os
import html
import re
from urllib.parse import urlsplit

DEFAULT_HOSTS=('www.smarttitu.cn','smarttitu.cn','console.smarttitu.cn','doc.smarttitu.cn')
TECHNICAL_HOSTS=('api.smarttitu.cn',)
END=re.compile(r'[\s<>"，。；！？、（）【】`\\]')

class PublicLinks:
    def __init__(self,hosts=None):
        self.hosts=tuple(hosts if hosts is not None else (v.strip().lower() for v in os.getenv('CUSTOMER_LINK_HOSTS',','.join(DEFAULT_HOSTS)).split(',') if v.strip()))
        if any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?',h) or '..' in h for h in self.hosts):
            raise ValueError('CUSTOMER_LINK_HOSTS只接受准确域名，不接受路径、端口或通配符')
    def kind(self,url):
        try:
            p=urlsplit(url)
            if p.scheme!='https' or not p.hostname or p.username or p.password or p.port not in (None,443):return None
            return 'official' if p.hostname.lower() in self.hosts else 'technical' if p.hostname.lower() in TECHNICAL_HOSTS else None
        except ValueError:return None
    def stream(self):return LinkStream(self)
    def clean(self,text):
        stream=self.stream();return stream.feed(str(text))+stream.finish()
    def evidence(self,rows):
        result=[]
        for row in rows:
            value=dict(row)
            for field in ('content','image_evidence'):
                if field in value:
                    text='\n'.join(line for line in value[field].splitlines() if not re.match(r'^\s*(?:原文链接|图片\s*URL|来源)\s*[:：]',line))
                    value[field]=self.clean(text)
            result.append(value)
        return result
    @staticmethod
    def image(url):return isinstance(url,str) and bool(re.fullmatch(r'/media/[a-zA-Z0-9][a-zA-Z0-9_.-]*\.(?:png|jpg|jpeg|webp|gif)',url))
    def response(self,result):
        result=dict(result);result['answer']=self.clean(result.get('answer',''))
        result['images']=[dict(r) for r in result.get('images',[]) if self.image(r.get('url'))]
        return result

class LinkStream:
    """Only unfinished link tokens are held; ordinary text is emitted immediately."""
    def __init__(self,policy):self.policy=policy;self.pending='';self.code=None;self.blocked=0
    def feed(self,text,final=False):
        self.pending+=text;out=[]
        while self.pending:
            s=self.pending
            if s[0]=='`':
                if not final and s in ('`','``'):break
                marker='```' if s.startswith('```') else '`'
                if self.code==marker:self.code=None
                elif not self.code:self.code=marker
                out.append(marker);self.pending=s[len(marker):];continue
            if self.code:
                end=s.find('`');end=len(s) if end<0 else end
                out.append(s[:end]);self.pending=s[end:];continue
            if re.match(r'<(?:a\s|img\s)',s,re.I):
                image=bool(re.match(r'<img\s',s,re.I))
                end=s.find('>')+1 if image else s.lower().find('</a>')+4
                found=end>0 if image else end>=4
                if not found:
                    if not final and len(s)<4096:break
                    self.pending='';self.blocked+=1;continue
                tag=s[:end];target=re.search(r'href\s*=\s*[\"\']([^\"\']+)',tag,re.I)
                label=html.unescape(re.sub(r'<[^>]*>','',tag));address=html.unescape(target[1]) if target else ''
                out.append('' if image else '['+label+']('+address+')' if self.policy.kind(address)=='official' else self.policy.clean(label))
                self.pending=s[end:];self.blocked+=1;continue
            if s.startswith('[') or s.startswith('!['):
                image=s.startswith('![');start=2 if image else 1;close=s.find(']',start)
                if close<0:
                    if not final and len(s)<512:break
                elif close+1==len(s) and not final:break
                elif s[close+1:close+2]=='(':
                    level=1;end=close+2
                    while end<len(s) and level:
                        if s[end]=='(':level+=1
                        elif s[end]==')':level-=1
                        end+=1
                    if level:
                        if not final and len(s)<4096:break
                        # Incomplete link must not release a raw target at end of stream.
                        out.append(s[start:close] if not image else '');self.pending='';self.blocked+=1;continue
                    address=s[close+2:end-1].strip();label=self.policy.clean(s[start:close])
                    kind=self.policy.kind(address)
                    out.append('' if image else s[:end] if kind=='official' else label+('（'+address+'）' if kind=='technical' else ''))
                    self.blocked+=not bool(kind);self.pending=s[end:];continue
            if s.lower().startswith(('http://','https://')):
                match=END.search(s);end=match.start() if match else len(s)
                if end==len(s) and not final and len(s)<4096:break
                token=s[:end];address=token.rstrip('.,;:!?)]');suffix=token[len(address):]
                kind=self.policy.kind(address)
                out.append((address if kind else '')+suffix);self.blocked+=not bool(kind);self.pending=s[end:];continue
            if not final and any(prefix.startswith(s.lower()) for prefix in ('http://','https://','![','<a ','<img ')):break
            out.append(s[0]);self.pending=s[1:]
        return ''.join(out)
    def finish(self):return self.feed('',final=True)
