#!/usr/bin/env python3
"""Fetch public organizer data, preserve history, create JSON and subscribable ICS."""
from __future__ import annotations
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import html
import json
import math
from pathlib import Path
import re
import time
from urllib.parse import urljoin, urlencode, urlparse
from zoneinfo import ZoneInfo
import requests
from bs4 import BeautifulSoup
from icalendar import Calendar, Event

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'site/data'
TZ = ZoneInfo('Europe/Warsaw')
HTTP = requests.Session()
HTTP.headers['User-Agent'] = 'KrakowPoGodzinach/1.0 (public Krakow event calendar; source links retained)'
MONTHS = {w:i+1 for i,w in enumerate('stycznia lutego marca kwietnia maja czerwca lipca sierpnia września października listopada grudnia'.split())}


def clean(value):
    return re.sub(r'\s+', ' ', BeautifulSoup(html.unescape(str(value or '')), 'html.parser').get_text(' ', strip=True)).strip()


def short(value, limit=170):
    value = clean(value)
    return value if len(value) <= limit else value[:limit].rsplit(' ', 1)[0].rstrip('.,;:') + '…'


def read_json(path, default):
    return json.loads(path.read_text()) if path.exists() else default


def save_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n')
    tmp.replace(path)


def get(url, **kwargs):
    # Only fixed public organizer endpoints or same-host links discovered on them.
    r = HTTP.get(url, timeout=35, **kwargs)
    r.raise_for_status()
    return r


def soup(url):
    return BeautifulSoup(get(url).content, 'html.parser')


def text(node, selector):
    el = node.select_one(selector)
    return clean(el.get_text(' ', strip=True)) if el else ''


def aware(value):
    dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    return dt.replace(tzinfo=TZ) if dt.tzinfo is None else dt.astimezone(TZ)


def polish_datetime(value):
    value = clean(value).lower()
    m = re.search(r'(\d{1,2})\.(\d{1,2})\.(\d{4})(?:.*?(\d{1,2})[:.](\d{2}))?', value)
    if not m:
        return None
    d, mo, y, h, mi = m.groups()
    return datetime(int(y), int(mo), int(d), int(h or 0), int(mi or 0), tzinfo=TZ)


def map_links(address):
    return {
        'mapUrl': 'https://www.google.com/maps/search/?' + urlencode({'api':1,'query':address}),
        'directionsUrl': 'https://www.google.com/maps/dir/?' + urlencode({'api':1,'destination':address}),
        'parkingSearchUrl': 'https://www.google.com/maps/search/?' + urlencode({'api':1,'query':'parking near '+address})
    }


def category(title, default='kultura'):
    if re.search(r'\bAI\b|sztuczn|machine learning|LLM', title, re.I): return 'ai'
    if re.search(r'histor|archeo|zabyt|przeszło|fort |Twardows|PRL|archiw|niepodleg|sanator|Hotel.? Forum|hotele z importu|kopcem Kraka|getta', title, re.I): return 'historia'
    return default


def record(source, title, url, start, venue, address, description='', end=None, **extra):
    key = extra.pop('key', url.rstrip('/'))
    uid = hashlib.sha256((source['id']+'|'+str(key)).encode()).hexdigest()[:24]+'@krakow-po-godzinach'
    return dict(id=uid, sourceId=source['id'], sourceName=source['name'], title=clean(title), url=url,
                start=start.isoformat(), end=end.isoformat() if end else None,
                venue=clean(venue), address=clean(address), description=short(description) or 'Program spotkania i zasady udziału znajdziesz na stronie organizatora.',
                category=category(title, source.get('category','kultura')), language='do sprawdzenia',
                price='Sprawdź u organizatora', free=None, status='confirmed', **map_links(clean(venue)+' '+clean(address)), **extra)


def jsonld_nodes(s):
    def walk(obj):
        if isinstance(obj,dict):
            yield obj
            for v in obj.values(): yield from walk(v)
        elif isinstance(obj,list):
            for v in obj: yield from walk(v)
    for script in s.select('script[type="application/ld+json"]'):
        try: yield from walk(json.loads(script.string or script.get_text()))
        except (ValueError,TypeError): continue


def structured(source, s, page_url):
    out=[]
    nodes=list(jsonld_nodes(s))
    nested={child.get('@id',child.get('name')) for node in nodes if node.get('@type')=='Event' for child in node.get('subEvent',[]) if isinstance(child,dict)}
    for obj in nodes:
        if obj.get('@id',obj.get('name')) in nested:continue
        types = obj.get('@type',[])
        if obj.get('superEvent') or obj.get('isPartOf'): continue
        if isinstance(types,str): types=[types]
        if not any(t in ['Event','MusicEvent','EducationEvent','BusinessEvent','TheaterEvent'] for t in types): continue
        if not obj.get('startDate') or not obj.get('name'): continue
        loc=obj.get('location',{})
        if isinstance(loc,list): loc=loc[0] if loc else {}
        if not isinstance(loc,dict) or 'VirtualLocation'==loc.get('@type'): continue
        address=loc.get('address',{})
        if isinstance(address,dict): address=', '.join(str(address.get(k,'')) for k in ['streetAddress','postalCode','addressLocality'] if address.get(k))
        if 'krak' not in (str(address)+' '+str(loc)).lower(): continue
        start=aware(obj['startDate']); end=aware(obj['endDate']) if obj.get('endDate') else None
        url=urljoin(page_url,obj.get('url',page_url))
        if urlparse(url).scheme not in ['http','https']: continue
        e=record(source,obj['name'],url,start,loc.get('name',''),address,obj.get('description',''),end)
        e['category']=source.get('category',e['category'])
        e['timeUnknown']='T' not in str(obj['startDate'])
        e['language']=obj.get('inLanguage','do sprawdzenia')
        if isinstance(e['language'],list): e['language']=' / '.join(e['language'])
        offers=obj.get('offers',{})
        if isinstance(offers,list): offers=offers[0] if offers else {}
        if isinstance(offers,dict) and offers.get('price') is not None:
            p=str(offers['price']); e['free']=float(p.replace(',','.'))==0
            e['price']='Bezpłatne' if e['free'] else p+' '+str(offers.get('priceCurrency','PLN'))
        if 'Cancelled' in obj.get('eventStatus',''): e['status']='cancelled'
        geo=loc.get('geo',{})
        if geo.get('latitude') and geo.get('longitude'): e['coordinates']=[float(geo['latitude']),float(geo['longitude'])]
        out.append(e)
    return out


def museum(source, now, until):
    out=[]; count=0
    for page in range(1,13):
        s=soup(source['url']+'?'+urlencode({'page':page,'dateFrom':now.date().isoformat()}))
        cards=s.select('a.calendar-day'); count+=len(cards)
        if not cards: break
        beyond=False
        for card in cards:
            date_text=text(card,'.calendar-day__date'); start=polish_datetime(date_text)
            if not start: continue
            if start>=until: beyond=True; continue
            if start.date()<now.date(): continue
            url=urljoin(source['url'],card['href']); detail=soup(url)
            title=text(detail,'h1') or text(card,'.calendar-day__name')
            venue=text(card,'.calendar-day__place > span')
            # The actual event text has priority over page footer / related branch opening hours.
            body=text(detail,'.page-content__section.user-text')
            branch=detail.select_one('.page-content__section__branch')
            address=text(branch,'.info-text__text') if branch else ''
            address=re.split(r'tel\.?|e-mail',address,flags=re.I)[0].strip(' ,')
            # Meeting points explicitly stated in the event override its related museum branch.
            meeting=re.search(r'Miejsce (?:zbiórki|spotkania)\s*:?\s*(.{8,180})',body,re.I)
            if meeting:
                address=re.split(r'(?<=[.!])\s|Prowadze|Informacje|Cena',meeting.group(1))[0]
            if not address and re.search(r'ul\.|Rynek|plac|pl\.',venue,re.I): address=venue
            if not address:
                address=venue+', Kraków' if venue else ''
            if not venue or not address: continue  # Never invent a meeting place.
            if ', ul.' in venue:
                venue=venue.split(', ul.')[0]
            if 'Miejsce zbiórki:' in venue:venue=venue.replace('Miejsce zbiórki:','').strip()
            e=record(source,title,url,start,venue,address,body)
            e['category']=category(title+' '+body)
            if re.search(r'odwołan',title,re.I):e['status']='cancelled'
            e['timeUnknown']=not bool(re.search(r'\d{1,2}:\d{2}',date_text))
            info=' '.join(clean(x.get_text(' ',strip=True)) for x in detail.select('.right-contact__text'))
            if re.search(r'bezpłatn|wstęp wolny',info,re.I): e.update(free=True,price='Bezpłatne')
            else:
                price=re.search(r'(\d+(?:[,.]\d+)?\s*zł)',info)
                if price:e.update(free=False,price=price.group(1))
            out.append(e)
            time.sleep(.15)
        if beyond:break
        # Stop if there is no next-page link; avoid repeated page-one responses.
        if not any('page='+str(page+1) in a.get('href','') for a in s.select('a[href]')):break
    if count==0: raise ValueError('Zmieniona struktura kalendarium: brak kart wydarzeń')
    return out


def tribe(source, now, until):
    out=[]
    for page in range(1,11):
        d=get('https://ma.krakow.pl/wp-json/tribe/events/v1/events',params={'start_date':now.date().isoformat(),'end_date':until.date().isoformat(),'per_page':50,'page':page}).json()
        if 'events' not in d:raise ValueError('Brak events w API')
        for obj in d['events']:
            v=obj.get('venue',{})
            if not isinstance(v,dict) or 'krak' not in str(v).lower():continue
            address=', '.join(str(v.get(k,'')) for k in ['address','city'] if v.get(k))
            e=record(source,obj['title'],obj['url'],aware(obj['start_date']),v.get('venue','Muzeum Archeologiczne'),address,obj.get('excerpt') or obj.get('description',''),aware(obj['end_date']))
            e['category']='historia';e['timeUnknown']=bool(obj.get('all_day'))
            if obj.get('cost'):
                e['price']=clean(obj['cost']);e['free']=bool(re.search(r'^0(?:\D|$)|free|bezpłat',e['price'],re.I))
            if v.get('geo_lat') and v.get('geo_lng'):e['coordinates']=[float(v['geo_lat']),float(v['geo_lng'])]
            out.append(e)
        if page>=int(d.get('total_pages',1)):break
    return out


def parse_nck_schedule(when):
    rows=[]
    pattern=r'(\d{1,2}\.\d{1,2}\.\d{4})\s*,?\s*(.{0,120}?)\s*godz\.\s*(\d{1,2}:\d{2})(?:\s*([-–]|i|,)\s*(\d{1,2}:\d{2}))?'
    for m in re.finditer(pattern,when,re.I):
        date,venue,start,sep,end=m.groups()
        # Never treat a range's closing time as a second session.
        dt=polish_datetime(date+' '+start)
        finish=polish_datetime(date+' '+end) if end and sep in ['-','–'] else None
        if finish and finish<=dt:finish+=timedelta(days=1)
        venue=venue.strip(' ,') or 'Nowohuckie Centrum Kultury'
        rows.append((dt,finish,venue))
        if end and sep in ['i',',']:rows.append((polish_datetime(date+' '+end),None,venue))
    return list(dict.fromkeys(rows))


def nck(source, now, until):
    # Discover from the live event listing; never anchor updates to a particular year or season.
    urls=set()
    for page in range(1,9):
        s=soup('https://nck.krakow.pl/wydarzenia/'+('page/'+str(page)+'/' if page>1 else ''))
        for a in s.select('article a[href], .nck-news a[href], .nck-event a[href], .nck-news-title a[href], h2 a[href], h3 a[href]'):
            u=urljoin(source['url'],a['href'])
            if urlparse(u).netloc=='nck.krakow.pl' and not re.search(r'/category/|/tag/|/page/|/wydarzenia/?$',u):urls.add(u)
    if not urls:raise ValueError('Zmieniona lista wydarzeń NCK')
    out=[]
    for url in sorted(urls)[:160]:
        s=soup(url); article=s.select_one('article.nck-news-single')
        if not article: continue
        body=article.select_one('.nck-news-content')
        if not body:continue
        blocks=[clean(b.get_text(' ',strip=True)) for b in body.select('.blockquote-inner')]
        when=next((b for b in blocks if re.search(r'godz\.|g\.',b) and re.search(r'\d{1,2}\.\d{1,2}\.\d{4}',b)), '')
        rows=parse_nck_schedule(when)
        title=text(article,'h1')
        desc=text(body,'p')
        price_block=next((b for b in blocks if re.search(r'\bzł\b|wstęp wolny',b,re.I)), '')
        for index,(start,end,venue) in enumerate(rows):
            if (end or start)<now or start>=until:continue
            # A one-date event keeps its identity if rescheduled. Recurring listings keep each date distinct.
            key=url.rstrip('/')+('|date-'+start.date().isoformat() if len({r[0].date() for r in rows})>1 else '|slot-0')
            if sum(r[0].date()==start.date() for r in rows)>1:key+='|time-'+start.strftime('%H%M')
            e=record(source,title,url,start,venue,'al. Jana Pawła II 232, Kraków',desc,end,key=key)
            e['category']='kultura'
            if 'wstęp wolny' in price_block.lower():e.update(free=True,price='Bezpłatne')
            elif price_block:
                # Keep the price context (group admission, discounts, ranges), not an isolated last number.
                e['price']=short(price_block,110);e['free']=False
            if re.search(r'ODWOŁAN|CANCELLED',title,re.I):e['status']='cancelled'
            out.append(e)
        time.sleep(.1)
    return out


def sii(source, now, until):
    s=soup(source['url'])
    urls={urljoin(source['url'],a['href']) for a in s.select('a[href]') if re.search(r'/wydarzenia/[^/]+/?$',a['href'])}
    out=[]
    for url in sorted(urls)[:30]:
        s=soup(url); title=(text(s,'h1') or (s.select_one('meta[property="og:title"]') or {}).get('content','')).removesuffix(' | Sii Polska')
        if not re.search(r'\bAI\b|sztuczn',title,re.I):continue
        content=s.select_one('main') or s
        body=clean(content.get_text(' ',strip=True))
        # Match the venue/date/time block; no online or other-city events.
        m=re.search(r'(?:Biuro Sii Polska|Miejsce)\s*(.{3,100}?Kraków)\s*(\d{2}\.\d{2}\.\d{4})\s*(\d{1,2}:\d{2})\s*[-–]\s*(\d{1,2}:\d{2})',body,re.I)
        if not m:continue
        address,d,t,end=m.groups();start=polish_datetime(d+' '+t)
        if not now.date()<=start.date()<until.date():continue
        finish=polish_datetime(d+' '+end)
        meta=s.select_one('meta[name="description"]')
        e=record(source,title,url,start,'Biuro Sii Polska',address,meta['content'] if meta else '',finish)
        e['category']='ai'
        language=re.search(r'Język\s+(pl|en)\b',body,re.I)
        if language:e['language']=language.group(1).lower()
        if re.search(r'bezpłatn|bezplatn|free',body,re.I):e.update(price='Bezpłatne',free=True)
        out.append(e)
    return out


def distance(a,b):
    p1,p2=map(math.radians,[a[0],b[0]]); dp=p2-p1;dl=math.radians(b[1]-a[1])
    return 6371000*2*math.atan2(math.sqrt(math.sin(dp/2)**2+math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2),math.sqrt(1-(math.sin(dp/2)**2+math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2)))


def geocode(events, cache):
    last=0
    for e in events:
        if e.get('coordinates'):continue
        q=e['address']
        if q not in cache:
            time.sleep(max(0,1.1-(time.monotonic()-last)))
            try:
                queries=[q, e['venue']+', Kraków']
                street=re.search(r'(?:ul\.\s*|al\.\s*)([^,]+)',q)
                if street:
                    part=street.group(1).strip()
                    queries.insert(1,part+', Kraków')
                    words=part.split()
                    if len(words)>=3:queries.append(' '.join(words[-2:])+', Kraków')
                for query in dict.fromkeys(queries):
                    time.sleep(max(0,1.1-(time.monotonic()-last)))
                    d=get('https://nominatim.openstreetmap.org/search',params={'q':query,'format':'jsonv2','limit':1,'countrycodes':'pl','viewbox':'19.75,50.2,20.25,49.9','bounded':1}).json()
                    last=time.monotonic()
                    if d:
                        cache[q]={'coordinates':[float(d[0]['lat']),float(d[0]['lon'])],'label':d[0]['display_name']}
                        break
            except Exception as ex:print('Geokodowanie:',type(ex).__name__)
            last=time.monotonic()
        if q in cache:e['coordinates']=cache[q]['coordinates']
    return cache


def event_parking(tags):
    if tags.get('access') in ['private','no','customers','permit','residents']:return False
    if tags.get('parking') in ['street_side','drop_off','kiss_and_ride']:return False
    if re.search(r'kiss.?(&|and|i)?.?ride|kiss.?n.?ride|tylko.*(?:dostaw|klient)',tags.get('name',''),re.I):return False
    stay=tags.get('maxstay','')
    if re.fullmatch(r'\d+',stay) and int(stay)<=30:return False
    return True


def fetch_parking(previous):
    query='[out:json][timeout:40];nwr["amenity"="parking"]["access"!~"private|no"]["parking"!="street_side"](49.95,19.75,50.2,20.25);out center tags;'
    for endpoint in ['https://overpass-api.de/api/interpreter','https://overpass.kumi.systems/api/interpreter']:
        try:
            r=HTTP.post(endpoint,data={'data':query},timeout=55);r.raise_for_status();d=r.json()
            if 'elements' not in d or d.get('remark'):raise ValueError('Niepełna odpowiedź Overpass')
            lots=[]
            for obj in d['elements']:
                tags=obj.get('tags',{}); c=obj.get('center',obj)
                if not c.get('lat') or not c.get('lon'):continue
                if not event_parking(tags):continue
                name=tags.get('name') or ('Parking przy '+tags['addr:street'] if tags.get('addr:street') else 'Parking z mapy OpenStreetMap')
                lots.append({'id':str(obj['type'])+'/'+str(obj['id']),'name':name,'coordinates':[c['lat'],c['lon']],'fee':tags.get('fee','unknown'),'access':tags.get('access','unknown')})
            if not lots:raise ValueError('Pusta baza parkingów')
            return {'checkedAt':datetime.now(TZ).isoformat(),'lots':lots,'warning':None}
        except Exception as ex:print('Parkingi:',endpoint,type(ex).__name__)
    return {**previous,'warning':'Nie udało się odświeżyć parkingów; pokazujemy ostatnią dostępną bazę.'}


def attach_parking(events, parking):
    for e in events:
        e['parking']=[]
        if not e.get('coordinates'):continue
        options=[]
        for lot in parking.get('lots',[]):
            meters=round(distance(e['coordinates'],lot['coordinates']))
            if meters>1800:continue
            pos=','.join(map(str,lot['coordinates']))
            options.append({**lot,'distanceMeters':meters,'mapUrl':'https://www.google.com/maps/search/?'+urlencode({'api':1,'query':pos}),'directionsUrl':'https://www.google.com/maps/dir/?'+urlencode({'api':1,'destination':pos}),'osmUrl':'https://www.openstreetmap.org/'+lot['id']})
        e['parking']=sorted(options,key=lambda x:x['distanceMeters'])[:2]


def merge(previous, fresh, now):
    result={e['id']:e for e in previous}
    for e in fresh:
        old=result.get(e['id'])
        changed=not old or any(e.get(k)!=old.get(k) for k in ['title','start','end','venue','address','description','price','status','language'])
        e['createdAt']=old['createdAt'] if old else now.isoformat()
        e['modifiedAt']=now.isoformat() if changed else old['modifiedAt']
        e['sequence']=(old.get('sequence',0)+1 if old else 0) if changed else old.get('sequence',0)
        e['checkedAt']=now.isoformat()
        result[e['id']]=e
    # Missing list entries are not proof of cancellation. Retain with original checkedAt.
    return [e for e in result.values() if aware(e.get('end') or e['start'])>=now-timedelta(days=90)]


def refresh_parking_revisions(previous, events, now):
    old={e['id']:e for e in previous}
    for e in events:
        before=old.get(e['id'])
        if before and e.get('parking',[])!=before.get('parking',[]) and e['modifiedAt']!=now.isoformat():
            e['modifiedAt']=now.isoformat()
            e['sequence']+=1


def make_calendar(events, title, now):
    cal=Calendar();cal.add('prodid','-//Krakow po godzinach//PL');cal.add('version','2.0');cal.add('calscale','GREGORIAN');cal.add('method','PUBLISH')
    cal.add('x-wr-calname',title);cal.add('x-wr-timezone','Europe/Warsaw');cal.add('x-published-ttl','PT12H');cal.add('refresh-interval',timedelta(hours=12))
    for e in events:
        item=Event();item.add('uid',e['id']);item.add('summary',e['title']);item.add('dtstamp',aware(e['modifiedAt']).astimezone(timezone.utc));item.add('created',aware(e['createdAt']).astimezone(timezone.utc));item.add('last-modified',aware(e['modifiedAt']).astimezone(timezone.utc));item.add('sequence',e['sequence'])
        start=aware(e['start']);end=aware(e['end']) if e.get('end') else None
        if e.get('timeUnknown'):
            item.add('dtstart',start.date());item.add('dtend',(end.date()+timedelta(days=1)) if end else start.date()+timedelta(days=1))
        else:
            item.add('dtstart',start.astimezone(timezone.utc))
            if end and end>start:item.add('dtend',end.astimezone(timezone.utc))
        item.add('location',e['venue']+', '+e['address']);item.add('url',e['url']);item.add('status','CANCELLED' if e['status']=='cancelled' else 'CONFIRMED');item.add('categories',[e['category']]);item.add('transp','TRANSPARENT')
        desc=[e['description'],'','Strona wydarzenia: '+e['url'],'Miejsce: '+e['venue']+', '+e['address'],'Wstęp: '+e['price'],'Język: '+str(e['language']),'Google Maps: '+e['mapUrl'],'Dojazd: '+e['directionsUrl']]
        if e.get('timeUnknown'):desc.append('Godzina nie została podana; sprawdź program organizatora.')
        if e.get('parking'):
            desc.extend(['','Najbliższe parkingi w bazie OSM (odległość w linii prostej):'])
            for p in e['parking']:desc.append(f"{p['name']} — {p['distanceMeters']} m\nMapa: {p['mapUrl']}\nDojazd: {p['directionsUrl']}")
        else:desc.append('Parkingi w okolicy: '+e['parkingSearchUrl'])
        desc+=['','Sprawdź oznakowanie i dostępność parkingu na miejscu.','Dane sprawdzono: '+e['checkedAt']]
        item.add('description','\n'.join(desc));cal.add_component(item)
    return cal.to_ical()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--offline',action='store_true');args=parser.parse_args()
    config=read_json(ROOT/'config.json',{});now=datetime.now(TZ);until=datetime.combine(now.date()+timedelta(days=config['days']),datetime.min.time(),TZ)
    old=read_json(DATA/'history.json',[]);oldmeta=read_json(DATA/'events.json',{});fresh=[];statuses=[]
    if not args.offline:
        for source in config['sources']:
            previous=next((s for s in oldmeta.get('sources',[]) if s['id']==source['id']),{})
            try:
                if source['parser']=='jsonld':items=structured(source,soup(source['url']),source['url'])
                else:items=globals()[source['parser']](source,now,until)
                items=list({e['id']:e for e in items if (aware(e.get('end') or e['start'])>=now or (e.get('timeUnknown') and aware(e['start']).date()>=now.date())) and aware(e['start'])<until}.values())
                fresh.extend(items);statuses.append({**source,'status':'ok','count':len(items),'checkedAt':now.isoformat()});print(source['name'],len(items))
            except Exception as ex:
                statuses.append({**source,'status':'error','checkedAt':previous.get('checkedAt'),'error':type(ex).__name__});print(source['name'],'ERROR',str(ex)[:150])
        merged=merge(old,fresh,now)
        if not any(s['status']=='ok' for s in statuses):raise SystemExit('Żadne źródło nie odpowiedziało poprawnie. Zachowano poprzednią publikację.')
        cache=geocode(merged,read_json(DATA/'geocodes.json',{}));save_json(DATA/'geocodes.json',cache)
        parking=fetch_parking(read_json(DATA/'parking.json',{'lots':[]}))
        attach_parking(merged,parking)
        refresh_parking_revisions(old,merged,now)
        used={p['id'] for e in merged for p in e.get('parking',[])}
        parking['lots']=[p for p in parking.get('lots',[]) if p['id'] in used]
        save_json(DATA/'parking.json',parking)
    else:
        merged=old;statuses=oldmeta.get('sources',[]);parking=read_json(DATA/'parking.json',{})
    active=sorted([e for e in merged if (aware(e.get('end') or e['start'])>=now or (e.get('timeUnknown') and aware(e['start']).date()>=now.date())) and aware(e['start'])<until],key=lambda e:e['start'])
    # Preserve checkedAt per event when a source fails. generatedAt is never a claim of verification.
    result={'title':config['title'],'generatedAt':now.isoformat(),'windowDays':config['days'],'from':now.date().isoformat(),'until':until.date().isoformat(),'siteUrl':config.get('site_url',''),'sources':statuses,'parkingCheckedAt':parking.get('checkedAt'),'parkingWarning':parking.get('warning'),'events':active}
    save_json(DATA/'history.json',merged);save_json(DATA/'events.json',result)
    for cat in [None,'historia','ai','kultura']:
        subset=[e for e in merged if cat is None or e['category']==cat]
        filename='wydarzenia' if cat is None else cat
        (ROOT/'site'/f'{filename}.ics').write_bytes(make_calendar(subset,config['title']+((' · '+cat) if cat else ''),now))
    print(f'Opublikowano dane: {len(active)} wydarzeń; historia: {len(merged)}')

if __name__=='__main__':main()
