import json
import unittest
from unittest.mock import Mock, patch

import requests

import test_outreach
from app.models import Account, Activity, AgentRun, Task


class PersonalizationTests(unittest.TestCase):
    tearDown = test_outreach.OutreachTests.tearDown
    def setUp(self):
        test_outreach.OutreachTests.setUp(self)
        self.app.config.update(OPENAI_API_KEY='test-key', OPENAI_MODEL='test-model')
        self.ai_payload = {**self.payload, 'personalization': 'ai'}

    def provider_response(self, opening='Your consulting team may find our sales preparation offer relevant.'):
        return {'status': 'completed', 'model': 'test-model',
                'output': [{'type': 'message', 'content': [
                    {'type': 'output_text', 'text': json.dumps({'opening': opening})}]}],
                'usage': {'input_tokens': 100, 'output_tokens': 20, 'total_tokens': 120}}

    @patch('app.providers.personalization.requests.post')
    def test_ai_preview_persists_usage_and_refresh_never_calls_provider(self, post):
        post.return_value = Mock(status_code=200)
        post.return_value.json.return_value = self.provider_response('<b>Opening</b>')
        response = self.client.post('/outreach', data=self.ai_payload)
        self.assertEqual(response.status_code, 303)
        activity = Activity.query.one()
        draft = json.loads(activity.summary)
        self.assertIn('<b>Opening</b>', draft['messages'][0]['body'])
        self.assertIn(self.payload['offer'], draft['messages'][0]['body'])
        self.assertNotIn('<b>Opening</b>', draft['messages'][1]['body'])
        self.assertEqual(draft['ai']['usage']['total_tokens'], 120)
        for _ in range(2):
            page = self.client.get(response.location)
            self.assertIn(f'Saved preview #{activity.id}'.encode(), page.data)
            self.assertIn(b'&lt;b&gt;Opening&lt;/b&gt;', page.data)
        post.assert_called_once()
        args = post.call_args.kwargs
        self.assertFalse(args['json']['store'])
        self.assertFalse(args['allow_redirects'])
        self.assertEqual(set(json.loads(args['json']['input'])), {'company', 'industry', 'title', 'offer'})
        self.assertNotIn('alex@firm.example', args['json']['input'])
        self.assertEqual(Account.query.one().stage, 'booked')
        self.assertEqual(Task.query.count(), 0)
        self.assertFalse(draft['sent'])
        self.assertFalse(draft['scheduled'])
        self.assertIn('total_tokens', AgentRun.query.one().detail)
        self.assertNotIn('provider cost 0', AgentRun.query.one().detail)

    @patch('app.providers.personalization.requests.post')
    def test_missing_configuration_and_invalid_mode_make_no_request(self, post):
        for field in ('OPENAI_API_KEY', 'OPENAI_MODEL'):
            with patch.dict(self.app.config, {field: ''}):
                self.assertEqual(self.client.post('/api/outreach/preview', json=self.ai_payload).status_code, 400)
        for mode in (None, True, [], {}, 'unknown'):
            self.assertEqual(self.client.post('/api/outreach/preview', json={**self.payload, 'personalization': mode}).status_code, 400)
        post.assert_not_called()
        self.assertEqual(Activity.query.count(), 0)
        self.assertEqual(AgentRun.query.count(), 0)

    @patch('app.providers.personalization.requests.post')
    def test_explicit_template_works_without_configuration(self, post):
        with patch.dict(self.app.config, {'OPENAI_API_KEY': '', 'OPENAI_MODEL': ''}):
            response = self.client.post('/api/outreach/preview', json={**self.payload, 'personalization': 'template'})
        self.assertEqual(response.status_code, 201)
        self.assertNotIn('ai', response.json)
        post.assert_not_called()

    @patch('app.providers.personalization.requests.post')
    def test_provider_failures_never_save_partial_drafts(self, post):
        refusal = {'status': 'completed', 'output': [{'type': 'message', 'content': [{'type': 'refusal'}]}]}
        cases = [Mock(status_code=429), Mock(status_code=401), Mock(status_code=500),
                 Mock(status_code=200, json=Mock(side_effect=ValueError('bad JSON')))]
        for data in [refusal, {'status': 'incomplete'}, self.provider_response(''),
                     self.provider_response('x' * 501), self.provider_response('line\nbreak'),
                     self.provider_response(123), {'status': 'completed', 'output': []}]:
            cases.append(Mock(status_code=200, json=Mock(return_value=data)))
        self.app.logger.disabled = True
        try:
            for case in cases + [requests.Timeout('secret provider details')]:
                post.side_effect = case if isinstance(case, Exception) else None
                post.return_value = case
                response = self.client.post('/api/outreach/preview', json=self.ai_payload)
                self.assertEqual(response.status_code, 500)
                self.assertNotIn(b'secret provider details', response.data)
                self.assertEqual(Activity.query.count(), 0)
                run = AgentRun.query.order_by(AgentRun.id.desc()).first()
                self.assertEqual(run.status, 'error')
                self.assertIsNotNone(run.finished_at)
            self.assertEqual(Account.query.one().stage, 'booked')
            self.assertEqual(Task.query.count(), 0)
        finally:
            self.app.logger.disabled = False
