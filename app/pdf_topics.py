"""Evidence-preserving PDF topics; page numbers are provenance, not boundaries."""
import re
import unicodedata
from urllib.parse import urlsplit,parse_qs,urlencode

REVISION='pdf-topics-v1'


def heading(text):
    if re.search(r'[。！？；]',text):return None
    numbered=re.fullmatch(r'(?:第[一二三四五六七八九十\d]+[章节]|[一二三四五六七八九十]+[、.]|\d{1,2}(?:\.\d{1,2})+[、. ]*|\d{1,2}[、. ]+)\s*(.{2,48})',text)
    if numbered:return numbered[1].strip()
    # Plain short labels are used by many exported articles; prose is not a heading.
    if 3<=len(text)<=24 and not re.search(r'[。!?！？,，:：;；/]',text) and re.search(r'(?:介绍|概览|概况|评估|收益|使用须知|操作步骤|适用范围|注意事项)$',text):return text
    return None


def question_for(title,body):
    if re.search(r'适配用户|适用用户|适用场景|适用企业',body):return title+'适合哪些场景，有哪些能力？'
    if re.search(r'操作步骤|第一步|步骤一',body):return '如何'+title+'？'
    if re.search(r'概览|概况|核心价值|应用场景',title):return title+'包括哪些内容？'
    return title+'有哪些具体内容？'


def topics(pages,title,declared_headings=()):
    """Returns topic blocks with page spans and original article link if available."""
    wechat=any('mp.weixin.qq.com/s?' in text for _,text in pages)
    source=None
    for _,text in pages:
        m=re.search(r'https://mp\.weixin\.qq\.com/s\?[^\s]+',text)
        if m:
            query=parse_qs(urlsplit(m[0]).query)
            if all(k in query for k in ('__biz','mid','idx','sn')):
                source='https://mp.weixin.qq.com/s?'+urlencode({k:query[k][0] for k in ('__biz','mid','idx','sn')});break
    short_title=re.split(r'[，,！!]',title,maxsplit=1)[0]
    blocks=[{'text':short_title+'概览','heading':True,'page':None,'locator':'PDF主题'}]
    if source:blocks.append({'text':'来源:公众号原文 '+source,'heading':False,'page':None,'locator':'原文地址'})
    ended=False;seen_content=False
    for number,text in pages:
        lines=text.splitlines()
        if number==1:
            target=re.sub(r'\s+','',unicodedata.normalize('NFKC',title))
            for n in range(1,min(4,len(lines))+1):
                if re.sub(r'\s+','', ''.join(lines[:n]))==target:lines=lines[n:];break
        for raw in lines:
            line=raw.strip()
            if not line:continue
            if wechat:
                if line=='往期推荐':ended=True
                if ended:continue
                # Browser print furniture, not original article facts.
                line=re.split(r'20\d{2}/\d{1,2}/\d{1,2}\s+\d{1,2}:\d{2}',line,maxsplit=1)[0].strip()
                if not line or 'mp.weixin.qq.com/s?' in line or re.fullmatch(r'\d+\s*/\s*\d+',line):continue
                if re.fullmatch(r'(?:\d{1,2}\s*:\s*\d{2})+',line):continue
                if re.search(r'20\d{2}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日.*\d{1,2}\s*:\s*\d{2}',line):continue
                if re.match(r'供稿[:：]|编辑[:：]|观看视频',line):continue
                if line in {'阅读原文','点击 阅读原文','👇 👇 👇','👇👇👇','🎬'}:continue
            compact=re.sub(r'\s+','',line)
            if compact==re.sub(r'\s+','',title):continue
            subject=line if line in declared_headings else heading(line)
            if subject:
                blocks.append({'text':subject,'heading':True,'page':number,'locator':'PDF物理第'+str(number)+'页'})
                if source:blocks.append({'text':'来源:公众号原文 '+source,'heading':False,'page':number,'locator':'原文地址'})
            else:
                seen_content=True
                blocks.append({'text':line,'heading':False,'page':number,'locator':'PDF物理第'+str(number)+'页'})
    if not seen_content:raise ValueError('PDF没有可用正文,扫描件请先OCR')
    return blocks


def enrich(chunks,document_title):
    """Retrieval helpers are verbatim extracts, never additional business facts."""
    for chunk in chunks:
        title=chunk['title'];body=chunk['content']
        chunk['section_title']=title
        chunk['recommended_question']=unicodedata.normalize('NFKC',question_for(title,body))
        chunk['document_title']=document_title
        chunk['source_kind']='wechat' if any('公众号原文 ' in ref for ref in chunk['source_references']) else 'pdf'
        # Repeated document context makes overview and detailed topics discoverable.
        lines=[line for line in body.splitlines() if re.search(r'场景关键词|适配用户|适用场景|核心能力',line)]
        chunk['retrieval_context']='主题:'+title+'\n'+'\n'.join(lines[:4])
    return chunks
