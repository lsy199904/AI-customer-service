"""Conversation routing and server-approved reply images."""
import json
import re
import urllib.parse
from pathlib import Path

WELCOME = '您好呀，我是 SmartTITU 的智能客服。产品使用、模型接入、费用或调用问题，都可以问我哦～'
REPLIES = {
    'greeting': WELCOME,
    'identity': '我是 SmartTITU 的智能客服，可以帮您了解产品、模型接入、API 密钥和常见问题。您想先了解哪一项呢？',
    'capabilities': '您可以问我产品介绍、账号开通、模型接入、计费和常见故障。我也可以帮您查找相关说明或人工联系方式。您现在遇到什么问题啦？',
    'thanks': '不客气呀，能帮到您就好～还有其他问题，随时问我。',
    'farewell': '好的，有需要随时来找我。祝您使用顺利～',
}


QUICK_QUESTIONS = ['注册流程', '企业认证流程', '服务订购流程', '客户充值流程', '账单支付流程', '在线开票流程']
NO_ANSWER = '你当前的问题我无法回答哦，你可以向我提问：'


def sensitive_topic(question):
    """Local explicit-topic guard, complemented by semantic refusal in SYSTEM.

    These rules are not a claim of comprehensive content moderation. Product safety
    controls are legitimate business questions, rather than requests for adult content.
    """
    compact=re.sub(r'\s+','',question.lower())
    governance=re.search(r'过滤|拦截|防止|检测|内容审核|内容安全|合规',compact)
    if governance and re.search(r'模型|平台|系统|内容安全',compact):return False
    return bool(re.search(r'涉政|政治|政党|选举|国家领导人|涉黄|色情|黄色(?:视频|图片|小说)|成人视频|成人影片|裸聊|porn|sexvideo',compact))


def rejected_recommendations(question,history):
    previous=next((m for m in reversed(history) if m['role']=='assistant'),None)
    if not previous or (previous.get('response') or {}).get('status')!='suggestions':return False
    text=re.sub(r'[\W_]+','',question)
    return bool(re.fullmatch(r'(?:以上|这些问题|这些|推荐的问题|推荐的|当前)?(?:都不是|都不对|都不需要|没有我想问的|没有我想要的|不是我想要的|都不是我想问的|都不是我想要的|都不是想要的|都不是想问的|都不想问)(?:哦|呢|啊|呀)?',text))


def recommended_questions(knowledge,question,evidence=(),sensitive=False,related_titles=()):
    """Suggest curated titles only; do not lower the answer threshold or call models."""
    from .retrieval import lexical_ranking,title_text,topic
    related=[]
    if not sensitive:
        related.extend(row['title'] for row in evidence)
        related.extend(title for title in related_titles if isinstance(title,str))
        try:
            rows=[(0,{**row,'content':''}) for row in knowledge.rows.values()]
            ranking=lexical_ranking(question,rows)
            related.extend(s['row']['title'] for s in sorted(ranking,key=lambda s:s['lexical'],reverse=True)
                           if s['lexical']>0 and s['coverage']>=.2)
        except Exception:pass  # Recommendation failure must still offer the static questions.
    result=[];seen=set()
    for title in related[:3]+QUICK_QUESTIONS:
        text=re.sub(r'^\d+(?:\.\d+)*[.、\s]+','',title_text(title)).strip()
        key=topic(text,question=True)
        if not 2<=len(text)<=120 or not key or key in seen or re.search(r'https?://',text):continue
        seen.add(key);result.append(text)
        if len(result)==6:break
    return result


def intent_of(question):
    compact=re.sub(r'[\s\W_]+','',question.lower())
    if re.fullmatch(r'(你好|您好|哈喽|嗨|hello|hi|早上好|早安|下午好|晚上好|在吗|有人吗|你在吗)+(呀|啊|呢|哦|哇|哟)?',compact):return 'greeting'
    if compact in {'你是谁','你叫什么','你是什么助手','你是什么','介绍一下你自己','你是机器人吗','你是人工吗'}:return 'identity'
    if compact in {'你能做什么','你有什么功能','你可以做什么','你能帮我什么','你会什么','怎么使用你'}:return 'capabilities'
    if re.fullmatch(r'(好的|好|嗯|嗯嗯)?(谢谢|谢谢你|感谢|多谢|谢谢啦|谢谢您)+(啦|了|呀|哦)?',compact):return 'thanks'
    if compact in {'再见','拜拜','下次聊','bye','goodbye','先这样','没问题了'}:return 'farewell'
    if re.search(r'转人工|人工客服|联系人工|联系客服',question):return 'handoff'
    if (re.search(r'(我的|我们|本企业|本公司|当前).{0,15}(余额|订单|认证状态|剩余)|创建.{0,5}工单',question)
            and not re.search(r'如何|怎么|哪里',question)):return 'business'
    if re.search(r'图片|截图|示意图|架构图|产品图|流程图|二维码|logo|标识|来张图|给.*图',question,re.I):return 'image'
    return 'knowledge'


def contextual_query(question,history):
    query=question
    if len(question)<24 and re.search(r'这个|那个|它|上述|刚才|然后|接下来|还有呢',question):
        previous=next((h['content'] for h in reversed(history) if h['role']=='user'), '')
        if previous:query=previous+' '+question
    return query


def retrieval_query(question, history):
    # A new question ending in "怎么办" must not inherit an unrelated billing topic.
    query=contextual_query(question,history)
    if re.search(r'调用失败|调用不了|不能调用|无法调用|鉴权失败|报错|错误码|\b(?:400|401|403|404|429|500|503|504)\b',question,re.I):
        query=question+' 调用报错 错误 排查'
    return query


class MediaCatalog:
    """Only operator-registered images can be returned; model-generated URLs are ignored."""
    def __init__(self, path, static_directory):
        self.rows={};self.assets={}
        source=Path(path)
        if not source.exists():return
        rows=json.loads(source.read_text(encoding='utf-8'))
        if not isinstance(rows,list):raise ValueError('media.json必须为数组')
        types={'.png':'image/png','.jpg':'image/jpeg','.jpeg':'image/jpeg','.webp':'image/webp','.gif':'image/gif'}
        for row in rows:
            key=row.get('id','');url=row.get('url','')
            if not isinstance(key,str) or not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,79}',key) or key in self.rows:
                raise ValueError('图片ID无效或重复')
            if not isinstance(url,str):raise ValueError('图片地址无效')
            if url.startswith('/media/'):
                name=url[7:]
                if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]*',name) or Path(name).suffix.lower() not in types:
                    raise ValueError('本地图片只支持media目录中的PNG/JPEG/WebP/GIF')
                image=Path(static_directory)/name
                if not image.is_file():raise ValueError('图片文件不存在:'+name)
                self.assets[url]=(str(Path('media')/name),types[image.suffix.lower()])
            else:
                parsed=urllib.parse.urlsplit(url)
                if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password:
                    raise ValueError('外部回复图片必须使用可信HTTPS地址')
            for field in ('title','alt'):
                if not isinstance(row.get(field,''),str) or len(row.get(field,''))>200:raise ValueError('图片说明无效')
            if any(not isinstance(row.get(k,[]),list) for k in ('keywords','knowledge_ids')):
                raise ValueError('图片关键词与知识ID必须为数组')
            if any(not isinstance(v,str) for v in row.get('keywords',[])+row.get('knowledge_ids',[])):
                raise ValueError('图片关键词和知识ID必须为字符串')
            self.rows[key]=row

    def candidates(self, question, evidence):
        # Knowledge replies use only this turn's document-owned media. A keyword
        # lookup is reserved for an explicit image request with no bound diagram.
        bound=self.bound(evidence)
        if bound or intent_of(question)!='image':return bound
        q=question.lower()
        return [r for r in self.rows.values()
                if any(k.lower() in q for k in r.get('keywords',[]) if k)][:4]

    def bound(self,evidence):
        # Stable operator IDs come from document metadata, never from generated URLs.
        keys=dict.fromkeys(key for row in evidence for key in row.get('image_ids',[]))
        return [self.rows[key] for key in keys if key in self.rows][:4]

    def public(self, row):
        return {k:row.get(k,'') for k in ('id','url','title','alt')}
