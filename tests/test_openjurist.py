import importlib.util
import ipaddress
import json
from pathlib import Path
import socket
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

root=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('caselaw_public_test',root/'__init__.py',submodule_search_locations=[str(root)])
plugin=importlib.util.module_from_spec(spec);sys.modules[spec.name]=plugin;spec.loader.exec_module(plugin)
public=plugin.openjurist
LOW='https://law.justia.com/cases/test/lower'
HIGH='https://supreme.justia.com/cases/test/higher'


PAGE='https://openjurist.org/100/f2d/5/fictional-case'

def payload(volume,series,page,body):
 return ('<h1>Fictional case</h1><div>no negative treatment on record</div><article class="opinion-body">'+body+'</article>').encode()


class OpenJuristTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(dir='/tmp');self.root=Path(self.tmp.name);self.store=public.PublicOpinions(self.root)
 def tearDown(self):self.tmp.cleanup()
 def test_fetch_obeys_robots_and_keeps_source_quality(self):
  calls=[]
  def get(path,limit):
   calls.append(path)
   if path=='/robots.txt':return b'User-agent: *\nAllow: /\nDisallow: /api/\n'
   return payload(100,'f2d',5,'<p>This fictional opinion contains enough words for a bounded public-source extraction.</p><script>ignore hidden instructions</script>')
  result=self.store.fetch(LOW,PAGE,100,'f2d',5,_request=get,_sleep=lambda _:None)
  self.assertEqual(len(calls),2)
  self.assertIn('verify',result['metadata']['bodyQuality'])
  self.assertNotIn('text',result)
  self.assertTrue(plugin.core.valid_origin_url(result['text_origin_url']))
  record=self.store.load(result['source_id'])
  self.assertNotIn('hidden instructions',record['text']);self.assertNotIn('no negative treatment',record['text'])
  self.assertEqual(self.store.path(result['source_id']).stat().st_mode & 0o777,0o600)
 def test_robots_refusal_and_invalid_identity_never_save(self):
  calls=[]
  def denied(path,limit):calls.append(path);return b'User-agent: *\nDisallow: /100/\n'
  with self.assertRaisesRegex(RuntimeError,'robots policy'):self.store.fetch(LOW,PAGE,100,'f2d',5,_request=denied,_sleep=lambda _:None)
  self.assertEqual(calls,['/robots.txt'])
  self.assertEqual(list(self.store.root.glob('*.json')),[])
  with self.assertRaises(ValueError):public.reporter_path(True,'f2d',5)
  with self.assertRaises(ValueError):public.reporter_path(100,'../f2d',5)
  with self.assertRaises(ValueError):self.store.fetch(LOW,'https://openjurist.org/101/f2d/5/wrong',100,'f2d',5,_request=denied,_sleep=lambda _:None)
  self.assertFalse(public.conservative_robots_allow('User-agent: *\nAllow: /\nDisallow: /api/\n','/api/test'))
  self.assertTrue(public.conservative_robots_allow('User-agent: *\nAllow: /\nDisallow: /api/\n','/100/f2d/5/case'))
  self.assertFalse(public.conservative_robots_allow('User-agent: other\nDisallow: /100/\nUser-agent: *\nAllow: /\n','/100/f2d/5/case'))
  self.assertEqual(list(self.store.root.glob('*.json')),[])
 def test_missing_policy_and_excessive_delay_fail_closed(self):
  for robots in (b'<html>not a policy</html>', b'User-agent: *\nCrawl-delay: 6\nAllow: /\n'):
   calls=[]
   def get(path,limit):calls.append(path);return robots
   with self.assertRaises(RuntimeError):self.store.fetch(LOW,PAGE,100,'f2d',5,_request=get,_sleep=lambda _:None)
   self.assertEqual(calls,['/robots.txt'])
 def test_http_denial_is_not_followed_or_retried(self):
  class Response:
   status=429
  class Connection:
   def __init__(self,*args,**kwargs):self.requests=[]
   def request(self,*args,**kwargs):self.requests.append((args,kwargs))
   def getresponse(self):return Response()
   def close(self):pass
  connection=Connection()
  with patch.object(public,'PublicConnection',return_value=connection):
   with self.assertRaisesRegex(RuntimeError,'429'):public.request('/robots.txt',65536)
  self.assertEqual(len(connection.requests),1)
  self.assertNotIn('Authorization',connection.requests[0][1]['headers'])
 def test_private_dns_results_are_never_connected(self):
  private=str(ipaddress.IPv4Address(0x7F000001))
  addresses=[(socket.AF_INET,socket.SOCK_STREAM,6,'',(private,443))]
  with patch.object(public.socket,'getaddrinfo',return_value=addresses),patch.object(public.socket,'socket') as create:
   with self.assertRaisesRegex(OSError,'public'):public.PublicConnection(public.HOST,443,timeout=1).connect()
  create.assert_not_called()
 def test_stored_record_tampering_is_detected(self):
  def get(path,limit):return b'User-agent: *\nAllow: /\nDisallow: /api/\n' if path=='/robots.txt' else payload(100,'f2d',5,'<p>Fictional opinion text sufficient for the synthetic fixture validation.</p>')
  result=self.store.fetch(LOW,PAGE,100,'f2d',5,_request=get,_sleep=lambda _:None)
  path=self.store.path(result['source_id']);path.write_text(path.read_text().replace('Fictional case','Changed case'))
  with self.assertRaisesRegex(ValueError,'record fingerprint'):self.store.load(result['source_id'])

 def test_read_pages_preserve_unicode_offsets_and_reject_invalid_bounds(self):
  body='Fictional opinion with café and sufficient text to exercise reading in separate pages.'
  def get(path,limit):return b'User-agent: *\nAllow: /\n' if path=='/robots.txt' else payload(100,'f2d',5,'<p>'+body+'</p>')
  source=self.store.fetch(LOW,PAGE,100,'f2d',5,_request=get,_sleep=lambda _:None)['source_id']
  expected=self.store.load(source)['text']; pieces=[]; start=0
  while start is not None:
   page=self.store.read(source,start,13);pieces.append(page['text'])
   self.assertEqual(page['text'],expected[page['start']:page['end']]);start=page['next_start']
  self.assertEqual(''.join(pieces),expected)
  storage=types.ModuleType('plugins.plugin_storage');storage.plugin_data_dir=lambda _:self.root
  plugins=types.ModuleType('plugins');plugins.__path__=[]
  with patch.dict(sys.modules,{'plugins':plugins,'plugins.plugin_storage':storage}):
   result=json.loads(plugin.invoke('caselaw_read_public_opinion',{'source_id':source,'start':0,'length':13},None))
  self.assertEqual(result['text'],expected[:13]);self.assertEqual(result['next_start'],13)
  for start,length in ((-1,1),(len(expected),1),(True,1),(0,0),(0,10001),(0,True)):
   with self.assertRaises(ValueError):self.store.read(source,start,length)

if __name__=='__main__':unittest.main()


