"""Retrieval-only text cleaning, title signals, BM25 and rank fusion."""
from collections import Counter
import math
import re
import unicodedata

TEXT_VERSION='retrieval-text-v2'
URL=re.compile(r"https?://[^\s<>，。；）)\]\"']+")


def title_text(value):
    value=unicodedata.normalize('NFKC',str(value)).strip()
    value=re.sub(r'^问题\s*\d+\s*','',value)
    return re.sub(r'^第\s*\d+\s*页\s*','',value).strip()


def clean_content(value):
    lines=[]
    for line in str(value).splitlines():
        if re.match(r'^\s*(?:图片\s*URL|原文链接|来源|链接)\s*[:：]',line,re.I):continue
        line=URL.sub('',line).strip()
        if line:lines.append(line)
    return '\n'.join(lines)


def retrieval_text(record):
    return title_text(record['title'])+'\n'+clean_content(record['content'])


def topic(value,question=False):
    text=title_text(value).lower()
    if question:
        text=re.sub(r'^(?:请问|请|麻烦|我想了解|我想知道|介绍一下|介绍下|给我看一下|给我|看一下)+','',text)
        text=re.sub(r'[？?！!。.,，\s]+$','',text)
        for _ in range(2):
            text=re.sub(r'(?:是什么|是干什么的|是做什么的|是怎样的|是怎么样的|有哪些|介绍一下|介绍下|的介绍|介绍|呢|吗)[？?！!。.,，\s]*$','',text)
        text=re.sub(r'(流程|架构)(?:示意图|图)$',r'\1',text)
    text=re.sub(r'是什么[？?！!。.,，\s]*$','',text)
    text=re.sub(r'[^a-z0-9\u3400-\u9fff]+','',text).replace('的','')
    return re.sub(r'(?:概况|概述|简介|介绍)$','',text)


def terms(value):
    text=unicodedata.normalize('NFKC',value).lower()
    # Product identifiers remain one token, including "TITU Hub" / "tituhub".
    text=re.sub(r'\btitu\s+(hub|edge|work)\b',r'titu\1',text)
    text=re.sub(r'请问|是什么|怎么|如何|一下|哪些|什么|可以|能否|有没有',' ',text)
    result=re.findall(r'[a-z0-9_]+',text)
    for run in re.findall(r'[\u3400-\u9fff]+',text):
        result.extend(run[i:i+2] for i in range(len(run)-1))
    return result


def title_matches(question, titles):
    """Resolve a named procedure to its chapter without widening to shared keywords.

    Exact subjects outrank expanded headings (e.g. a report about that subject).
    Generic '流程' by itself must never anchor an arbitrary chapter.
    """
    subject=topic(question,question=True)
    procedure=re.sub(r'(?:流程|步骤|操作方法|使用方法)$','',subject)
    procedural=procedure!=subject and len(procedure)>=4
    scores=[]
    for title in titles:
        target=topic(title)
        score=3 if len(subject)>=4 and subject==target else 0
        if procedural and not score:
            if procedure==target:score=2
            elif target.startswith(procedure):score=1
        scores.append(score)
    best=max(scores,default=0)
    return [best>0 and score==best for score in scores]


def lexical_ranking(question,rows):
    query=set(terms(question))
    matches=title_matches(question,[row['title'] for _,row in rows])
    counts=[Counter(terms(title_text(row['title']))*3+terms(clean_content(row['content']))) for _,row in rows]
    df=Counter(t for counter in counts for t in counter)
    avg=sum(sum(counter.values()) for counter in counts)/max(len(counts),1) or 1
    result=[]
    for (dense,row),counter,matched in zip(rows,counts,matches):
        overlap=query & counter.keys();coverage=len(overlap)/max(len(query),1)
        length=sum(counter.values())
        score=sum(math.log(1+(len(rows)-df[t]+.5)/(df[t]+.5))*counter[t]*2.2/
                  (counter[t]+1.2*(.25+.75*length/avg)) for t in overlap)
        # Partial lexical similarity complements vectors; it is not a keyword gate.
        eligible=matched or (coverage>=.6 and len(overlap)>=2)
        result.append({'row':row,'dense':dense,'lexical':score,'coverage':coverage,
                       'title_match':matched,'lexical_eligible':eligible})
    return result


def fuse(question,ranked,minimum,top_k):
    signals=lexical_ranking(question,ranked)
    dense=[s for s in signals if s['dense']>=minimum][:top_k]
    lexical=sorted([s for s in signals if s['lexical_eligible']],key=lambda s:(s['title_match'],s['lexical']),reverse=True)[:top_k]
    pool={}
    for ranking in (dense,lexical):
        for rank,signal in enumerate(ranking,1):
            key=signal['row']['id']
            if key not in pool:pool[key]={**signal,'rrf':0.0}
            pool[key]['rrf']+=1/(60+rank)
    return sorted(pool.values(),key=lambda s:(s['title_match'],s['rrf'],s['dense']),reverse=True)[:top_k*2]
