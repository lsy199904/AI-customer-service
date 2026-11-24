import json
import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
from app.core import Service,Settings,APIError
from app.live_sync import broker

class LiveFAQTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.service=Service(Settings(secret='x'*40,db=str(Path(self.tmp.name)/'chat.db'),retrieval_backend='lexical'))
        self.addCleanup(self.service.close)
        self.actor={'tenant_id':'t','sub':'u'}
        self.sid=self.service.create(self.actor,{})['session_id']
    def test_faq_batch_answer_persistence_and_no_model_or_quota(self):
        batch=self.service.bootstrap()['faq'];self.assertEqual(len(batch['items']),6)
        self.assertEqual(len(self.service.faq.rows),24)
        item=next(row for row in self.service.faq.rows.values() if row.get('source_question')==42)
        with patch.object(self.service,'rate',side_effect=AssertionError('fixed FAQ rate')),patch.object(self.service,'reserve_rag_quota',side_effect=AssertionError('fixed FAQ quota')):
            result=self.service.chat(self.actor,self.sid,dict(message=item['question'],request_id='faq-persist-test',faq_id=item['id']))
        self.assertEqual(result['answer_mode'],'fixed')
        self.assertIn('再次获取完整API Key',result['answer'])
        self.assertNotIn('仅显示一次',result['answer'])
        self.assertEqual(len(self.service.history(self.actor,self.sid)['items']),2)
        cached=self.service.chat(self.actor,self.sid,dict(message=item['question'],request_id='faq-persist-test',faq_id=item['id']))
        self.assertEqual(cached,result)
        self.assertEqual(len(self.service.history(self.actor,self.sid)['items']),2)
    def test_two_subscribers_receive_start_and_committed_finish(self):
        sync=broker(self.service)
        with sync.subscribe(self.actor) as a,sync.subscribe(self.actor) as b:
            result=self.service.chat(self.actor,self.sid,dict(message='你好',request_id='sync-greet-test'))
            for receive in (a,b):
                start=receive();finish=receive()
                self.assertEqual(start['type'],'start');self.assertEqual(finish['type'],'finish')
                self.assertEqual(start['session_id'],self.sid)
                self.assertEqual(finish['request_id'],'sync-greet-test')
                self.assertEqual(len(self.service.history(self.actor,self.sid)['items']),2)
    def test_channel_isolation_and_large_delta_split(self):
        sync=broker(self.service)
        self.assertNotEqual(sync.channel(self.actor),sync.channel({'tenant_id':'other','sub':'u'}))
        self.assertNotEqual(sync.channel(self.actor),sync.channel({'tenant_id':'t','sub':'other'}))
        with sync.subscribe(self.actor) as receive:
            sync.publish(self.actor,dict(type='delta',text='汉'*1600,session_id=self.sid,request_id='test-split'))
            self.assertEqual(''.join(receive()['text'] for _ in range(4)),'汉'*1600)
        self.assertEqual(sync.listeners,{})
    def test_postgres_publish_does_not_create_tables(self):
        self.service.config.database_url='test'
        with patch.object(self.service,'db',Mock()) as db:
            broker(self.service).publish(self.actor,{'type':'finish'})
            self.assertEqual(db.execute.call_args.args[0],'SELECT pg_notify(?,?)')
        self.service.config.database_url=''
    def test_unauthorized_chat_does_not_publish(self):
        sync=broker(self.service)
        with patch.object(sync,'publish') as publish:
            with self.assertRaises(APIError):self.service.chat({'tenant_id':'t','sub':'other'},self.sid,dict(message='你好',request_id='sync-denied-test'))
            publish.assert_not_called()

if __name__=='__main__':logging.disable(logging.CRITICAL);unittest.main()
