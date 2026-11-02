"""Synchronization barriers prove concurrent planning and bounded final wait."""
import json
import threading
import time
import unittest
from unittest.mock import patch
from tests import test_image_policy as fixture

class ParallelMediaTests(unittest.TestCase):
 setUp=fixture.VisualWorkflowTests.setUp
 tearDown=fixture.VisualWorkflowTests.tearDown
 def test_plan_starts_during_generation_and_metadata_precedes_ready_images(self):
  entered=threading.Event();release=threading.Event();finished=threading.Event();events=[]
  decision={'need_images':True,'reason':'full_procedure','flow_ids':['subscription'],'multiple_flows':False,'image_ids':[],'source_ids':[]}
  class Model:
   def complete(me,messages,on_delta=None):
    payload=json.loads(messages[-1]['content']);self.assertEqual(payload['answer'],'')
    entered.set();release.wait(2);finished.set();return json.dumps(decision)
   def answer(me,q,h,e,c):
    self.assertTrue(entered.wait(1),'plan must start before generation completes')
    c['_on_delta']('打开服务订购，选择套餐并提交。')
    return {'answerable':True,'answer':'打开服务订购，选择套餐并提交。','citation_ids':['subscription'],'image_ids':[]}
  def observer(item):
   events.append(item)
   if item['type']=='metadata':
    self.assertFalse(finished.is_set());self.assertTrue(item['citations']);self.assertTrue(item['media_pending']);release.set()
  self.s.knowledge=fixture.Evidence(self.rows);self.s.model=Model()
  try:result=self.s.chat(fixture.ACTOR,self.sid,{'message':'怎么买套餐','request_id':'parallel-barrier'},observer=observer)
  finally:release.set()
  self.assertEqual([r['id'] for r in result['images']],['business-subscription'])
  self.assertLess(next(i for i,e in enumerate(events) if e['type']=='delta'),next(i for i,e in enumerate(events) if e['type']=='metadata'))
 def test_slow_plan_does_not_hold_completion_or_update_saved_history_later(self):
  entered=threading.Event();release=threading.Event();finished=threading.Event();events=[]
  class Model:
   def complete(me,*a,**k):
    entered.set();release.wait(3);finished.set()
    return json.dumps({'need_images':True,'reason':'full_procedure','flow_ids':['subscription'],'multiple_flows':False,'image_ids':[],'source_ids':[]})
   def answer(me,q,h,e,c):
    self.assertTrue(entered.wait(1));c['_on_delta']('打开服务订购。')
    return {'answerable':True,'answer':'打开服务订购。','citation_ids':['subscription'],'image_ids':[]}
  self.s.knowledge=fixture.Evidence(self.rows);self.s.model=Model()
  try:
   with patch.dict('os.environ',{'MEDIA_FINAL_WAIT_SECONDS':'0.02'}):
    start=time.monotonic();result=self.s.chat(fixture.ACTOR,self.sid,{'message':'怎么买套餐','request_id':'parallel-slow'},observer=events.append)
   self.assertLess(time.monotonic()-start,.8);self.assertFalse(finished.is_set());self.assertEqual(result['images'],[]);self.assertTrue(result['citations'])
   self.assertTrue(any(e['type']=='metadata' and e['citations'] for e in events))
   count=len(events);release.set();self.assertTrue(finished.wait(1))
   self.assertEqual(len(events),count);self.assertEqual(self.s.history(fixture.ACTOR,self.sid)['items'][-1]['response']['images'],[])
   self.assertFalse(self.s._workflow._visual_jobs)
  finally:release.set()
