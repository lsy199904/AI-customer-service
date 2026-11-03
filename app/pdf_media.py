"""Local, evidence-based PDF asset cleaning. Unknown assets stay review-only.

No decoded QR address is fetched. Assets are immutable and content-addressed so
old conversation references remain readable after a document is updated.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import threading
import unicodedata
import uuid
from urllib.parse import urlsplit

VERSION='pdf-media-v2'
_ENGINE=None
_LOCK=threading.Lock()
_PDFIUM_LOCK=threading.Lock()
PURPOSE_TITLES={'trial':'试用申请二维码','website':'官网访问二维码','follow':'公众号关注二维码','contact':'咨询联系二维码'}
PURPOSE_PATTERNS={'trial':r'试用|POC|体验申请|申请体验|先体验|先测试',
                  'website':r'官网|官方网站|网站入口|访问网站',
                  'follow':r'关注公众号|公众号关注', 'contact':r'微信咨询|微信客服|联系二维码'}


def purpose_of(text):
    compact=re.sub(r'\s+','',unicodedata.normalize('NFKC',text))
    return next((k for k,v in PURPOSE_PATTERNS.items() if re.search(v,compact,re.I)),None)


def atomic_json(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        temp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8');os.chmod(temp,0o600);os.replace(temp,path)
    finally:temp.unlink(missing_ok=True)


def atomic_asset(path,data):
    path=Path(path)
    if path.exists():return
    temp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        temp.write_bytes(data);os.chmod(temp,0o600);os.replace(temp,path)
    finally:temp.unlink(missing_ok=True)


def asset_id(data):return 'pdf-'+hashlib.sha256(data).hexdigest()[:32]


def ocr_image(image):
    global _ENGINE
    from rapidocr_onnxruntime import RapidOCR
    with _LOCK:
        if _ENGINE is None:_ENGINE=RapidOCR(intra_op_num_threads=1,inter_op_num_threads=1)
        result,_=_ENGINE(image)
    return [{'text':r[1],'confidence':round(float(r[2]),4),'box':r[0]} for r in result or [] if float(r[2])>=.75]


def safe_qr_url(text):
    try:
        parsed=urlsplit(text)
        return parsed.scheme in ('https','http') and bool(parsed.hostname) and not parsed.username and not parsed.password
    except ValueError:return False


def classify(text,width,height,caption='',rectangles=0):
    """Conservative role assignment from readable content, not document names."""
    compact=re.sub(r'\s+','',text)
    if width<80 or height<60:return 'decoration','excluded','small_resource'
    if re.search(r'观看视频|视频播放',caption) and 1.5<width/height<2.0:return 'video_cover','excluded','near_video_caption'
    if re.search(r'证书|评估证明|CERTIFICATE',compact,re.I):return 'certificate','retained','explicit_certificate_text'
    if re.search(r'企业需求|适配用户|服务价值',compact) and len(compact)>50:return 'infographic','retained','labeled_information_graphic'
    if rectangles>=4 and len(compact)>40 and re.search(r'架构|框架|模块|运营管理|统一接入|计量计费|流程',compact):return 'diagram','retained','structured_diagram_with_text'
    return 'unknown','review','insufficient_role_evidence'


def _png(image):
    import cv2
    ok,data=cv2.imencode('.png',image)
    if not ok:raise ValueError('PDF图片编码失败')
    return data.tobytes()


def analyze_image(image,caption=''):
    import cv2
    import zxingcpp
    height,width=image.shape[:2]
    if width*height>20_000_000:raise ValueError('PDF图片超过像素上限')
    ocr=ocr_image(image) if width>=80 and height>=60 else []
    text='\n'.join(r['text'] for r in ocr)
    gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
    contours,_=cv2.findContours(cv2.Canny(gray,80,180),cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
    rectangles=sum(1 for c in contours if cv2.contourArea(c)>width*height*.003 and len(cv2.approxPolyDP(c,.03*cv2.arcLength(c,True),True))==4)
    kind,status,reason=classify(text,width,height,caption,rectangles)
    output=[{'kind':kind,'status':status,'reason':reason,'ocr':ocr,'data':_png(image),'purpose':None,'width':width,'height':height}]
    codes=zxingcpp.read_barcodes(image,formats=zxingcpp.BarcodeFormat.QRCode)
    for code in codes:
        points=[code.position.top_left,code.position.top_right,code.position.bottom_right,code.position.bottom_left]
        left=max(0,min(p.x for p in points));right=min(width,max(p.x for p in points))
        top=max(0,min(p.y for p in points));bottom=min(height,max(p.y for p in points))
        margin=max(12,int(max(right-left,bottom-top)*.10))
        crop=image[max(0,top-margin):min(height,bottom+margin),max(0,left-margin):min(width,right+margin)]
        # A label near a code is stronger evidence than unrelated text at the top of a poster.
        nearby=[r['text'] for r in ocr if abs(sum(p[1] for p in r['box'])/4-(top+bottom)/2)<max(bottom-top,100)*1.3]
        labels='\n'.join(nearby)
        hits={k for k,v in PURPOSE_PATTERNS.items() if re.search(v,re.sub(r'\s+','',labels),re.I)}
        if not hits and len(codes)==1:hits={k for k,v in PURPOSE_PATTERNS.items() if re.search(v,re.sub(r'\s+','',caption),re.I)}
        purpose=next(iter(hits)) if len(hits)==1 else None
        valid=bool(code.valid and safe_qr_url(code.text))
        output.append({'kind':'qr','status':'retained' if valid and purpose else 'review',
            'reason':'decoded_qr_with_purpose' if valid and purpose else 'unknown_qr_purpose_or_unsafe_payload',
            'purpose':purpose,'purpose_evidence':nearby or [caption], 'decoded_url':code.text if valid else None,
            'data':_png(crop),'width':crop.shape[1],'height':crop.shape[0],'ocr':[], 'qr_box':[left,top,right,bottom]})
        # A QR-only graphic is represented by its cropped code, not duplicated as an unknown poster.
        if (right-left)*(bottom-top)>width*height*.45:output[0].update(status='excluded',reason='qr_parent_replaced_by_crop')
    return output


def _binding(chunks,page,caption,ocr):
    from .retrieval import terms
    on_page=[(i,c) for i,c in enumerate(chunks) if page in c.get('source_pages',[])]
    if not on_page:return None
    query=set(terms(caption+' '+ocr))
    ranked=sorted(((len(query & set(terms(c['title']+' '+c['content']))),i) for i,c in on_page),reverse=True)
    # Never spread an image over every topic on the same page.
    if ranked[0][0]<2 or len(ranked)>1 and ranked[0][0]==ranked[1][0]:return None
    return ranked[0][1]


def pdf_images(raw,article):
    """PDFium calls stay serialized; yielded pixels no longer share native memory."""
    import cv2
    import pypdfium2 as pdfium
    with _PDFIUM_LOCK,pdfium.PdfDocument(raw) as document:
        appendix=False;count=0;pixels=0
        for number,page in enumerate(document,1):
            text=page.get_textpage();height=page.get_height();cutoff=float('inf')
            if article:
                search=text.search('往期推荐');hit=search.get_next()
                if hit and text.count_rects(*hit):cutoff=height-text.get_rect(0)[3]
                search.close()
            objects=list(page.get_objects(filter=[pdfium.raw.FPDF_PAGEOBJ_IMAGE]))
            for obj in objects:
                count+=1
                if count>150:yield {'limit':'image_count_limit'};return
                width_px,height_px=obj.get_px_size()
                if width_px*height_px>20_000_000:yield {'limit':'image_pixel_limit'};continue
                pixels+=width_px*height_px
                if pixels>80_000_000:yield {'limit':'document_image_pixel_budget'};return
                left,bottom,right,top=obj.get_bounds();rect=[left,height-top,right,height-bottom]
                caption=text.get_text_bounded(left=0,bottom=max(0,bottom-90),right=page.get_width(),top=min(height,top+90))[:1200]
                bitmap=obj.get_bitmap(render=True);image=bitmap.to_numpy().copy();bitmap.close()
                if image.ndim==2:image=cv2.cvtColor(image,cv2.COLOR_GRAY2BGR)
                elif image.shape[2]==4:
                    alpha=image[:,:,3:4]/255.;image=(image[:,:,:3]*alpha+255*(1-alpha)).astype('uint8')
                yield {'image':image,'page':number,'box':rect,'caption':caption,'excluded':appendix or rect[1]>=cutoff}
            if cutoff<float('inf'):appendix=True
            if not objects and next(page.get_objects(filter=[pdfium.raw.FPDF_PAGEOBJ_PATH]),None) is not None:
                yield {'limit':'page_'+str(number)+'_vector_content_requires_review'}
            text.close();page.close()


def extract(path,parsed,root):
    """Analyze once per original revision; attach assets without editing source text."""
    import cv2
    root=Path(root)
    topic_signature=hashlib.sha256(json.dumps([(c['title'],c['content'],c.get('source_pages',[])) for c in parsed.chunks],ensure_ascii=False).encode()).hexdigest()[:16]
    report_path=root/'reports'/(parsed.sha256+'-'+VERSION+'-'+topic_signature+'.json')
    if report_path.exists():
        report=json.loads(report_path.read_text())
        if all((root/'assets'/(r['id']+'.png')).is_file() for r in report['assets']):return attach(parsed,report),report
    root.joinpath('assets').mkdir(parents=True,exist_ok=True)
    report={'version':VERSION,'source_file':path.name,'source_sha256':parsed.sha256,'assets':[],'limits':[],
            'policy':'local_ocr_and_geometry; unknown_or_ambiguous_assets_are_not_served'}
    seen={}
    article=any(c.get('source_kind')=='wechat' for c in parsed.chunks)
    for item in pdf_images(parsed.raw,article):
        if 'limit' in item:report['limits'].append(item['limit']);continue
        image=item['image'];number=item['page'];rect=item['box'];caption=item['caption']
        raw_id=asset_id(_png(image))
        if raw_id in seen:
            for row in seen[raw_id]:
                row['placements'].append({'page':number,'box':rect})
                if row['kind']!='qr':
                    index=_binding(parsed.chunks,number,caption,'\n'.join(r['text'] for r in row['ocr']))
                    if index is not None:row['topic_indices']=sorted(set(row.get('topic_indices',[])+[index]))
            continue
        cache=root/'cache'/(raw_id+'-'+hashlib.sha256(caption.encode()).hexdigest()[:12]+'-'+VERSION+'.json')
        if item['excluded']:
            data=_png(image);key=asset_id(data);destination=root/'assets'/(key+'.png')
            atomic_asset(destination,data)
            rows=[{'id':key,'kind':'related_content','status':'excluded','reason':'after_article_recommendations','purpose':None,'ocr':[],'width':image.shape[1],'height':image.shape[0]}]
        elif cache.exists():rows=json.loads(cache.read_text())
        else:
            rows=[]
            try:analysis=analyze_image(image,caption)
            except Exception as error:
                analysis=[{'kind':'unknown','status':'review','reason':'analysis_failed_'+type(error).__name__,'ocr':[],'data':_png(image),'purpose':None,'width':image.shape[1],'height':image.shape[0]}]
            for result in analysis:
                data=result.pop('data');key=asset_id(data);destination=root/'assets'/(key+'.png')
                atomic_asset(destination,data)
                rows.append({**result,'id':key})
            atomic_json(cache,rows)
        rows=[dict(r) for r in rows]
        for row in rows:
            row['placements']=[{'page':number,'box':rect}]
            row['caption']=caption;row['source_file']=path.name
            row['topic_index']=_binding(parsed.chunks,number,caption,'\n'.join(r['text'] for r in row['ocr'])) if row['kind']!='qr' else None
            if row['status']=='retained' and row['kind']!='qr' and row['topic_index'] is None:row.update(status='review',reason='ambiguous_topic_binding')
            row['topic_indices']=[row['topic_index']] if row['topic_index'] is not None else []
            row['title']=PURPOSE_TITLES.get(row.get('purpose')) if row['kind']=='qr' else (parsed.chunks[row['topic_index']]['title']+'配图' if row['topic_index'] is not None else '待确认图片')
            row['title']=row['title'] or '待确认二维码'
            row['url']='/media/'+row['id']+'.png';row['alt']=row['title'];row['generated']=True
            row['keywords']=[];row['flow_ids']=[]
        report['assets'].extend(rows);seen[raw_id]=rows
    # Deduplicate exact crops, preserving all source placements.
    unique={}
    for row in report['assets']:
        if row['id'] in unique:
            prior=unique[row['id']];placements=prior['placements']+row['placements']
            rank={'retained':3,'review':2,'excluded':1}
            if rank[row['status']]>rank[prior['status']] or row['kind']=='qr' and rank[row['status']]==rank[prior['status']]:unique[row['id']]=row
            unique[row['id']]['placements']=placements
            unique[row['id']]['topic_indices']=sorted(set(prior.get('topic_indices',[])+row.get('topic_indices',[])))
        else:unique[row['id']]=row
    report['assets']=list(unique.values());atomic_json(report_path,report)
    return attach(parsed,report),report


def attach(parsed,report):
    from dataclasses import replace
    chunks=[{**c,'image_ids':list(c.get('image_ids',[]))} for c in parsed.chunks]
    for row in report['assets']:
        if row['status']!='retained':continue
        index=row.get('topic_index')
        if row['kind']=='qr':
            purpose=row.get('purpose')
            # A task entry is grounded in the original CTA/QR label, not the containing business flow.
            evidence='\n'.join(row.get('purpose_evidence',[])).strip()
            matching=[i for i,c in enumerate(chunks) if c.get('media_action')==purpose]
            if matching:index=matching[0]
            elif purpose:
                chunks.append({'title':PURPOSE_TITLES[purpose],'section_title':PURPOSE_TITLES[purpose],
                    'recommended_question':{'trial':'如何申请试用？','website':'如何访问官网？','follow':'如何关注公众号？','contact':'如何扫码咨询？'}[purpose],
                    'content':evidence,'source_pages':sorted({p['page'] for p in row['placements']}),
                    'source_locator':'PDF二维码及附近原文','source_references':[], 'image_ids':[],
                    'source_kind':chunks[0].get('source_kind','pdf'),'document_title':parsed.title,'media_action':purpose})
                index=len(chunks)-1
        indices=[index] if row['kind']=='qr' and index is not None else row.get('topic_indices',[])
        for index in indices:
            if not 0<=index<len(chunks):continue
            if row['kind']!='qr':
                image_text='\n'.join(r['text'] for r in row.get('ocr',[]))[:1800]
                chunks[index]['image_evidence']=chunks[index].get('image_evidence','')+'\n'+image_text
                chunks[index]['retrieval_context']=chunks[index].get('retrieval_context','')+'\n配图文字:'+image_text
            chunks[index]['image_ids']=list(dict.fromkeys(chunks[index]['image_ids']+[row['id']]))
    signature=hashlib.sha256(json.dumps(chunks,ensure_ascii=False,sort_keys=True).encode()).hexdigest()[:16]
    return replace(parsed,chunks=chunks,parser_revision=parsed.parser_revision+'+'+VERSION+'-'+signature)


def catalog(root):
    root=Path(root);rows={}
    for path in sorted(root.glob('reports/*.json')):
        try:report=json.loads(path.read_text())
        except (ValueError,OSError):continue
        for row in report.get('assets',[]):
            key=row.get('id','')
            if row.get('status')!='retained' or not re.fullmatch(r'pdf-[a-f0-9]{32}',key):continue
            asset=root/'assets'/(key+'.png')
            if asset.is_symlink() or not asset.is_file():continue
            purposes=set(rows.get(key,{}).get('purposes',[]))|({row['purpose']} if row.get('purpose') else set())
            rows[key]={**row,'url':'/media/'+key+'.png','generated':True,'purposes':sorted(purposes),'asset_path':str(asset.resolve())}
    return list(rows.values())


def reserved_qr(question,candidates):
    purpose=purpose_of(question)
    if purpose=='trial' and not re.search(r'申请|入口|链接|二维码|扫码|先体验|先测试',question,re.I):return None
    row=next((r for r in candidates if r.get('kind')=='qr' and (r.get('purpose')==purpose or purpose in r.get('purposes',[])) and r.get('status')=='retained'),None)
    return {**row,'purpose':purpose,'title':PURPOSE_TITLES[purpose]} if row else None


def generation_evidence(evidence,qr_available):
    if qr_available:return evidence
    # Do not feed unavailable scan instructions into the streaming generator.
    result=[]
    for row in evidence:
        item=dict(row)
        for field in ('content','image_evidence'):
            if field in item:item[field]='\n'.join(line for line in item[field].splitlines() if not re.search(r'扫描.{0,6}二维码|扫码|识别.{0,6}二维码',line))
        result.append(item)
    return result
