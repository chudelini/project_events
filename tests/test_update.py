from copy import deepcopy
from datetime import datetime,timedelta
import json
from pathlib import Path
import sys
import unittest
from bs4 import BeautifulSoup
from icalendar import Calendar
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import update as u

class CalendarTests(unittest.TestCase):
    def setUp(self):
        self.now=datetime(2026,10,25,12,0,tzinfo=u.TZ)
        self.source={'id':'test','name':'Organizator'}
        self.event=u.record(self.source,'Historia; Kraków, żółć','https://example.org/event',self.now+timedelta(days=2),'Muzeum','Kraków','Krótki opis\nz nową linią.')
    def test_stable_uid_and_sequence_after_reschedule(self):
        old=u.merge([], [deepcopy(self.event)],self.now)
        new=deepcopy(self.event);new['start']=(self.now+timedelta(days=5)).isoformat()
        merged=u.merge(old,[new],self.now+timedelta(days=1))
        self.assertEqual(old[0]['id'],merged[0]['id']);self.assertEqual(merged[0]['sequence'],1)
        unchanged=u.merge(merged,[deepcopy(new)],self.now+timedelta(days=2))
        self.assertEqual(unchanged[0]['sequence'],1)
        self.assertEqual(unchanged[0]['createdAt'],old[0]['createdAt'])
    def test_source_failure_keeps_verification_date(self):
        old=u.merge([],[self.event],self.now)
        self.assertEqual(u.merge(old,[],self.now+timedelta(days=1)),old)
    def test_calendar_unicode_escaping_timezone_and_details(self):
        e=u.merge([],[self.event],self.now)[0];e['parking']=[{'name':'Parking','distanceMeters':120,'mapUrl':'https://maps.example.org','directionsUrl':'https://maps.example.org/directions'}]
        raw=u.make_calendar([e],'Kraków',self.now);cal=Calendar.from_ical(raw);item=cal.walk('VEVENT')[0]
        self.assertEqual(str(item['SUMMARY']),e['title']);self.assertEqual(item.decoded('DTSTART'),u.aware(e['start']))
        for field in ['Strona wydarzenia:','Dojazd:','Parking','120 m']:self.assertIn(field,str(item['DESCRIPTION']))
        self.assertTrue(all(len(line)<=75 for line in raw.split(b'\r\n')))
    def test_unknown_time_is_date_not_midnight(self):
        e=u.merge([],[self.event],self.now)[0];e['timeUnknown']=True
        item=Calendar.from_ical(u.make_calendar([e],'Kraków',self.now)).walk('VEVENT')[0]
        self.assertNotIsInstance(item.decoded('DTSTART'),datetime)
        self.assertEqual((item.decoded('DTEND')-item.decoded('DTSTART')).days,1)
    def test_cancellation_propagates(self):
        e=u.merge([],[self.event],self.now)[0];e['status']='cancelled'
        item=Calendar.from_ical(u.make_calendar([e],'Kraków',self.now)).walk('VEVENT')[0]
        self.assertEqual(str(item['STATUS']),'CANCELLED')
    def test_parking_change_updates_calendar_revision_once(self):
        old=u.merge([],[deepcopy(self.event)],self.now)
        new=deepcopy(old);new[0]['parking']=[{'name':'Nowy parking'}]
        later=self.now+timedelta(days=1)
        u.refresh_parking_revisions(old,new,later)
        self.assertEqual(new[0]['sequence'],1)
        self.assertEqual(new[0]['modifiedAt'],later.isoformat())
        u.refresh_parking_revisions(old,new,later)
        self.assertEqual(new[0]['sequence'],1)
    def test_dst_in_warsaw(self):
        self.assertEqual(u.aware('2026-10-24T18:00:00').utcoffset(),timedelta(hours=2))
        self.assertEqual(u.aware('2026-10-25T18:00:00').utcoffset(),timedelta(hours=1))

class ParserTests(unittest.TestCase):
    def test_nck_opening_hours_do_not_become_separate_sessions(self):
        blocks=json.loads((Path(__file__).parent/'fixtures/nck-wpp.json').read_text())
        rows=u.parse_nck_schedule(blocks[0])
        self.assertEqual(len(rows),24)
        self.assertEqual(len(set(rows)),24)
        self.assertTrue(all((end-start)==timedelta(hours=8) for start,end,venue in rows))
        self.assertTrue(all(start.hour==11 and end.hour==19 for start,end,venue in rows))
    def test_nck_single_concert(self):
        blocks=json.loads((Path(__file__).parent/'fixtures/nck-detail.json').read_text())
        rows=u.parse_nck_schedule(blocks[0]);self.assertEqual(len(rows),1)
        self.assertEqual(rows[0][0].isoformat(),'2026-11-07T19:00:00+01:00');self.assertIsNone(rows[0][1])
    def test_nck_two_performances_and_overnight_range(self):
        rows=u.parse_nck_schedule('07.11.2026, Scena NCK godz. 16:00 i 19:00')
        self.assertEqual(len(rows),2);self.assertEqual(rows[1][0].hour,19)
        rows=u.parse_nck_schedule('07.11.2026, Scena NCK godz. 20:00 - 02:00')
        self.assertEqual(rows[0][1].day,8)
    def test_nested_talk_is_not_a_second_conference(self):
        obj={'@type':'Event','name':'Konferencja','startDate':'2026-11-12T18:00:00+01:00','url':'https://example.org/2','location':{'name':'Hevre','address':'Meiselsa 18, Kraków'},'subEvent':[{'@type':'Event','@id':'talk-1','name':'Talk','startDate':'2026-11-12T18:00:00+01:00','location':{'name':'Hevre','address':'Kraków'}}]}
        s=BeautifulSoup('<script type="application/ld+json">'+json.dumps(obj)+'</script>','html.parser')
        self.assertEqual(len(u.structured({'id':'ai','name':'AI'},s,'https://example.org')),1)
    def test_short_stay_and_private_parking_are_excluded(self):
        for tags in [{'name':'Kiss & Ride'},{'parking':'drop_off'},{'access':'customers'},{'maxstay':'10'}]:
            self.assertFalse(u.event_parking(tags))
        self.assertTrue(u.event_parking({'name':'Parking publiczny','fee':'yes'}))
    def test_parking_nearest_order_private_already_filtered_at_fetch(self):
        event={'coordinates':[50.05,19.94]}
        lots=[{'id':'node/1','name':'dalszy','coordinates':[50.055,19.94]},{'id':'node/2','name':'bliski','coordinates':[50.051,19.94]},{'id':'node/3','name':'daleko','coordinates':[50.15,19.94]}]
        u.attach_parking([event],{'lots':lots});self.assertEqual([p['name'] for p in event['parking']],['bliski','dalszy'])

if __name__=='__main__':unittest.main()
