"""Bounded local cache of published network thermal-design evidence."""
import hashlib,json,time,urllib.request
from pathlib import Path
import pymupdf
ROOT=Path(__file__).parent
OUT=ROOT/'.local'/'network';OUT.mkdir(parents=True,exist_ok=True)
sources=json.loads((ROOT/'network_sources.json').read_text())['sources']
terms=['thermal resistivity','soil temperature','moisture','drying','dry out','backfill','burial','ground temperature','thermal conductivity']
results=[]
for src in sources:
    p=OUT/(src['id']+'.pdf')
    try:
        cached=p.exists()
        if not cached:
            request=urllib.request.Request(src['url'],headers={'User-Agent':'SoilResearch/1.0 bounded public-document study'})
            with urllib.request.urlopen(request,timeout=35) as r:body=r.read(15*1024*1024+1)
            if len(body)>15*1024*1024:raise ValueError('15MB cap exceeded')
            if not body.startswith(b'%PDF'):raise ValueError('Not a PDF; no challenge bypass')
            p.write_bytes(body)
        body=p.read_bytes();pages=[]
        with pymupdf.open(stream=body,filetype='pdf') as doc:
            if len(doc)>1000:raise ValueError('Page cap exceeded')
            for i,page in enumerate(doc):
                text=page.get_text();normal=' '.join(text.lower().split());hits=[t for t in terms if t in normal]
                if hits:pages.append({'page':i+1,'terms':hits,'text':text,'review_status':'candidate_not_interpreted'})
            total=len(doc)
        result={**src,'sha256':hashlib.sha256(body).hexdigest(),'cached':cached,'bytes':len(body),'pages':total,'candidate_pages':len(pages),'analysed_at':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())}
        (OUT/(src['id']+'.passages.json')).write_text(json.dumps({'source':result,'pages':pages},indent=2),encoding='utf8')
        results.append(result)
    except Exception as e:results.append({'id':src['id'],'error':str(e)})
    time.sleep(.5)
(OUT/'summary.json').write_text(json.dumps(results,indent=2),encoding='utf8')
print(json.dumps([{k:v for k,v in r.items() if k in ['id','pages','candidate_pages','bytes','error']} for r in results]))
