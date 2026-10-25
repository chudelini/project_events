"""Fail publication on malformed dates, duplicate sessions, broken maps or invalid ICS."""
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse,parse_qs
import json
from icalendar import Calendar

root=Path(__file__).resolve().parents[1]/'site'
data=json.loads((root/'data/events.json').read_text())
ids=set();sessions=set()
for e in data['events']:
    assert e['id'] not in ids, 'Powtórzony UID';ids.add(e['id'])
    session=(e['url'].rstrip('/'),e['start'],e['venue'])
    assert session not in sessions, 'Powtórzony termin: '+str(session);sessions.add(session)
    for key in ['title','description','venue','address','url','checkedAt','modifiedAt']:assert e[key],(e['id'],key)
    start=datetime.fromisoformat(e['start']);assert start.tzinfo
    if e.get('end'):assert datetime.fromisoformat(e['end'])>start
    assert e['category'] in ['historia','ai','kultura']
    for key in ['mapUrl','directionsUrl','parkingSearchUrl']:
        url=urlparse(e[key]);assert url.hostname=='www.google.com' and parse_qs(url.query)['api']==['1']
    for p in e.get('parking',[]):assert 0<=p['distanceMeters']<=1800
for filename in ['wydarzenia','historia','ai','kultura']:
    raw=(root/(filename+'.ics')).read_bytes();cal=Calendar.from_ical(raw)
    assert all(len(line)<=75 for line in raw.split(b'\r\n')), 'Niepoprawne łamanie linii ICS'
    events=cal.walk('VEVENT');uids=[str(e['UID']) for e in events];assert len(uids)==len(set(uids))
    for item in events:
        assert item.get('DTSTART') and item.get('DTSTAMP') and item.get('LOCATION') and item.get('DESCRIPTION')
        assert 'Dojazd:' in str(item['DESCRIPTION'])
print(f"OK: {len(ids)} unikalnych wydarzeń, 4 poprawne subskrypcje ICS")
