"""Read-only trial: public Product Radar, Habr Product Radar feed, Show HN."""
import csv
import hashlib
import json
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
STAMP = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
OUT = ROOT / 'AI-system-materials/outputs/DZ-05' / ('trial-' + STAMP)
ROWS, STATUS = [], []

def now():
    return datetime.now(timezone.utc).isoformat()

class Node:
    def __init__(self, tag='', attrs=None):
        self.tag, self.attrs, self.children = tag, dict(attrs or []), []
    def walk(self):
        yield self
        for c in self.children:
            if isinstance(c, Node):
                yield from c.walk()
    def text(self):
        if self.tag in ('script','style','svg'):
            return ''
        return ' '.join(c.text() if isinstance(c, Node) else c for c in self.children)
    def has(self, cls):
        return cls in self.attrs.get('class','').split()
    def first(self, cls):
        return next((n for n in self.walk() if n.has(cls)), None)

class Tree(HTMLParser):
    voids = {'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}
    def __init__(self, value):
        super().__init__(convert_charrefs=True)
        self.root=Node('root'); self.stack=[self.root]; self.feed(value)
    def handle_starttag(self, tag, attrs):
        n=Node(tag,attrs); self.stack[-1].children.append(n)
        if tag not in self.voids: self.stack.append(n)
    def handle_startendtag(self,tag,attrs):
        self.handle_starttag(tag,attrs)
        if tag not in self.voids: self.handle_endtag(tag)
    def handle_endtag(self,tag):
        for i in range(len(self.stack)-1,0,-1):
            if self.stack[i].tag==tag:
                self.stack=self.stack[:i]; break
    def handle_data(self,data): self.stack[-1].children.append(data)

def clean(value):
    return re.sub(r'\s+', ' ', unescape(value)).strip()

def fetch(url):
    request=Request(url,headers={'User-Agent':'AI-PM-Study-Trial/0.1 (read-only educational collection)','Accept':'application/json, application/rss+xml, text/html;q=0.9, */*;q=0.5'})
    with urlopen(request,timeout=30) as r:
        data=r.read(4_000_001)
        if len(data)>4_000_000: raise ValueError('Response exceeds 4 MB trial limit')
        return data, {'url':url,'final_url':r.url,'status':r.status,'fetched_at':now(),'sha256':hashlib.sha256(data).hexdigest()}

def base(source,kind,title,url,meta):
    return {'source':source,'record_type':kind,'title':title,'source_url':url,'collection_url':meta['url'],'fetched_at':meta['fetched_at'],'published_at':None,'period':None,'product_url':None,'description':None,'categories':[],'metric_name':None,'metric_value':None,'comments_count':None,'evidence':{},'response_sha256':meta['sha256']}

def radar():
    raw,meta=fetch('https://productradar.ru/')
    tree=Tree(raw.decode('utf-8')).root
    period=None; count=0; found=0
    for n in tree.walk():
        if n.tag=='time' and n.has('products__period'):
            if count: break
            period=n.attrs.get('datetime')
        if n.tag!='article' or not n.has('products__item'): continue
        found+=1
        title=n.first('card__title'); vote=n.first('upvote'); desc=n.first('card__description'); comm=n.first('card__comments')
        if title is None or vote is None: raise ValueError('Radar card shape changed: no title/upvote')
        link=next((a for a in title.walk() if a.tag=='a' and '/product/' in a.attrs.get('href','')),None)
        if link is None: raise ValueError('Missing Radar product URL')
        v=vote.attrs.get('data-votes')
        if v is None or not v.isdigit(): raise ValueError('Missing/non-numeric data-votes')
        row=base('Product Radar','product_listing',clean(title.text()),urljoin(meta['final_url'],link.attrs['href']),meta)
        row.update(source_id=vote.attrs.get('data-id'),period=period,description=clean(desc.text()) if desc else None,metric_name='Product Radar votes (data-votes)',metric_value=int(v),comments_count=int(clean(comm.text())) if comm and clean(comm.text()).isdigit() else None)
        cats=n.first('card__categories')
        row['categories']=[clean(a.text()) for a in cats.walk() if a.tag=='a'] if cats else []
        row['evidence']={'title':clean(title.text()),'data_votes':v,'comments_text':clean(comm.text()) if comm else None,'period_datetime':period}
        ROWS.append(row); count+=1
        if count==10: break
    if not count: raise ValueError('No Radar product cards parsed')
    STATUS.append({'source':'Product Radar','result':'ok','records':count,'selection':'first up to 10 cards of the first visible period, source order; not a full catalogue','metadata':meta})

def habr():
    raw,page_meta=fetch('https://habr.com/ru/companies/productradar/articles/')
    tree=Tree(raw.decode('utf-8')).root
    links=[n for n in tree.walk() if n.tag=='link' and n.attrs.get('type') in ('application/rss+xml','application/atom+xml')]
    if not links: raise ValueError('No advertised RSS/Atom link on Habr company page')
    feed_url=urljoin(page_meta['final_url'],links[0].attrs['href'])
    if urlparse(feed_url).hostname!='habr.com': raise ValueError('Unexpected feed host')
    raw,meta=fetch(feed_url)
    doc=ET.fromstring(raw)
    items=doc.findall('./channel/item')
    if not items: raise ValueError('No RSS items parsed')
    for item in items[:5]:
        title=clean(item.findtext('title') or '')
        url=clean(item.findtext('link') or '')
        if not title or not url.startswith('https://habr.com/'): raise ValueError('Invalid Habr RSS title/link')
        row=base('Habr / Product Radar','article',title,url,meta)
        date=item.findtext('pubDate')
        row['published_at']=parsedate_to_datetime(date).isoformat() if date else None
        row['source_id']=item.findtext('guid') or url
        row['categories']=[clean(c.text or '') for c in item.findall('category')]
        creator=item.find('{http://purl.org/dc/elements/1.1/}creator')
        row['author']=clean(creator.text or '') if creator is not None else None
        row['evidence']={'rss_title':title,'rss_link':url,'pubDate':date}
        ROWS.append(row)
    STATUS.append({'source':'Habr / Product Radar','result':'ok','records':min(5,len(items)),'selection':'first up to 5 items of RSS advertised by company page; articles, not individual new products','feed_discovery':page_meta,'metadata':meta})

def hn():
    raw,meta=fetch('https://hacker-news.firebaseio.com/v0/showstories.json')
    ids=json.loads(raw)
    count=0
    for ident in ids[:10]:
        time.sleep(.15)
        raw,item_meta=fetch(f'https://hacker-news.firebaseio.com/v0/item/{int(ident)}.json')
        item=json.loads(raw)
        if not item or item.get('deleted') or item.get('dead') or item.get('type')!='story': continue
        if not item.get('title','').startswith('Show HN:'): continue
        row=base('Show HN','project_post',clean(item['title']),f'https://news.ycombinator.com/item?id={ident}',item_meta)
        row.update(source_id=str(ident),collection_url=meta['url'],product_url=item.get('url'),published_at=datetime.fromtimestamp(item['time'],timezone.utc).isoformat() if item.get('time') else None,metric_name='Hacker News score',metric_value=item.get('score'),comments_count=item.get('descendants'),evidence={k:item.get(k) for k in ('id','title','time','url','score','descendants')})
        ROWS.append(row);count+=1
    if not count: raise ValueError('No usable Show HN records')
    STATUS.append({'source':'Show HN','result':'ok','records':count,'selection':'first 10 IDs from showstories, skipping dead/deleted; source order, not all launches or a custom ranking','metadata':meta})

