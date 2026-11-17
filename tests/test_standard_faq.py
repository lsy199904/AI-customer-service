"""Standard FAQ uses trusted IDs, saves isolated history, and never invokes paid RAG."""
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch,Mock
from fastapi.testclient import TestClient
from app.core import Settings
from app.server import create_app
from app.faq import FAQCatalog

ROOT=Path(__file__).resolve().parent.parent

class StandardFAQTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        config=Settings(secret='faq-test-secret-'+('a'*40),db=str(Path(self.temp.name)/'chat.db'),
                        retrieval_backend='lexical',mode='extractive',anonymous_widget_enabled=True)
        self.app=create_app(config);self.client=TestClient(self.app,base_url='https://assistant.example.com')
        self.client.__enter__();self.addCleanup(self.client.__exit__,None,None,None)
        self.service=self.app.state.service
        token=self.client.post('/smart-bot/widget/anonymous-auth',json={}).json()['token']
        self.headers={'Authorization':'Bearer '+token}
        self.sid=self.client.post('/smart-bot/v1/sessions',json={},headers=self.headers).json()['session_id']
    def click(self,faq_id='faq-05',rid='faq-request-test-01',headers=None,sid=None,**extra):
        return self.client.post(f'/smart-bot/v1/sessions/{sid or self.sid}/faq',headers=headers or self.headers,
                                json={'faq_id':faq_id,'request_id':rid,**extra})

    def test_24_questions_random_six_and_swap_excludes_previous_batch(self):
        boot=self.client.get('/smart-bot/v1/bootstrap',headers=self.headers).json()
        self.assertEqual(boot['faq']['total'],24);first=boot['faq']['items']
        self.assertEqual(len({r['id'] for r in first}),6)
        self.assertNotIn('answer',first[0])
        second=self.client.get('/smart-bot/v1/faq',params={'exclude':','.join(r['id'] for r in first)},headers=self.headers).json()['items']
        self.assertEqual(len(second),6)
        self.assertFalse({r['id'] for r in first}&{r['id'] for r in second})
        self.assertIn('注册流程',boot['quick_questions'])

    def test_direct_answer_has_no_workflow_retrieval_or_model_and_keeps_history(self):
        self.service.model=Mock();self.service.model.answer.side_effect=AssertionError('model called')
        self.service.knowledge=Mock();self.service.knowledge.assess.side_effect=AssertionError('retrieval called')
        with patch.object(self.service,'rate',side_effect=AssertionError('paid RAG quota consumed')):
            r=self.click()
        self.assertEqual(r.status_code,200,r.text)
        data=r.json();self.assertEqual(data['answer_mode'],'fixed');self.assertEqual(data['reason'],'standard_faq')
        self.assertEqual(data['retrieval']['method'],'not_used')
        self.assertEqual(data['answer'],self.service.faq.rows['faq-05']['answer'])
        self.assertIsNone(self.service._workflow)
        self.service.model.answer.assert_not_called();self.service.knowledge.assess.assert_not_called()
        self.assertEqual(self.service.db.execute('SELECT COUNT(*) FROM workflow_runs').fetchone()[0],0)
        history=self.client.get(f'/smart-bot/v1/sessions/{self.sid}/messages',headers=self.headers).json()['items']
        self.assertEqual(len(history),2)
        self.assertEqual(history[0]['content'],'如何注册账号？')
        self.assertEqual(history[1]['response']['faq_id'],'faq-05')
        self.assertTrue(all(i['url'].startswith('/smart-bot/') for i in data['images']))

    def test_retries_do_not_duplicate_and_request_id_cannot_change_question(self):
        a=self.click();b=self.click()
        self.assertEqual(a.json(),b.json())
        self.assertEqual(self.service.db.execute('SELECT COUNT(*) FROM messages').fetchone()[0],2)
        self.assertEqual(self.click(faq_id='faq-06').status_code,409)

    def test_authentication_and_ownership_are_required(self):
        self.assertEqual(self.client.get('/smart-bot/v1/faq').status_code,401)
        self.assertEqual(self.client.post(f'/smart-bot/v1/sessions/{self.sid}/faq',json={'faq_id':'faq-05','request_id':'request-auth-123'}).status_code,401)
        with TestClient(self.app,base_url='https://assistant.example.com') as other:
            token=other.post('/smart-bot/widget/anonymous-auth',json={}).json()['token']
            r=other.post(f'/smart-bot/v1/sessions/{self.sid}/faq',headers={'Authorization':'Bearer '+token},json={'faq_id':'faq-05','request_id':'request-owner-123'})
            self.assertEqual(r.status_code,404)

    def test_unknown_id_and_client_supplied_answer_cannot_fall_back_to_rag(self):
        self.assertEqual(self.click(faq_id='faq-missing').status_code,404)
        self.assertEqual(self.click(answer='fake answer').status_code,400)
        self.assertIsNone(self.service._workflow)

    def test_typed_question_still_uses_normal_workflow_even_if_equal_to_faq(self):
        with patch('app.workflow.SupportWorkflow') as workflow:
            instance=workflow.return_value
            instance.invoke.return_value=({'success':True,'reason':'knowledge','answer':'RAG reply','intent':'knowledge',
                'images':[],'selected':[],'retrieval':{'matched':True}},'normal-request')
            response=self.client.post(f'/smart-bot/v1/sessions/{self.sid}/messages',headers=self.headers,
                                     json={'message':'如何注册账号？','request_id':'normal-typed-request'})
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(response.json()['answer'],'RAG reply')
            instance.invoke.assert_called_once()

    def test_compact_log_retains_fixed_answer_marker(self):
        from app.observability import compact_steps
        step={'事件':'faq_answered','级别':'INFO','详情':{'faq_id':'faq-05','faq_version':'20261117-01'}}
        self.assertEqual(compact_steps([step]),[step])

    def test_all_fixed_answers_have_sources_and_valid_static_images(self):
        catalog=FAQCatalog(ROOT/'data/faq.json')
        registered={r['id'] for r in json.loads((ROOT/'data/media.json').read_text())}
        self.assertEqual(len(catalog.rows),24)
        for row in catalog.rows.values():
            self.assertTrue(row['source_question']);self.assertTrue(row['source_title'])
            self.assertNotIn('raw.githubusercontent.com',row['answer'])
            self.assertNotIn('图片URL',row['answer'])
            self.assertTrue(set(row['image_ids'])<=registered)

if __name__=='__main__':unittest.main()
