import json
import unittest
from unittest.mock import patch

import test_outreach
from app.models import db, Activity, AgentRun
from app.agents.queue import list_previews


class QueueTests(unittest.TestCase):
    tearDown = test_outreach.OutreachTests.tearDown

    def setUp(self):
        test_outreach.OutreachTests.setUp(self)

    def preview(self):
        return self.client.post('/api/outreach/preview', json=self.payload).json

    @patch('requests.sessions.Session.request', side_effect=AssertionError('Unexpected network'))
    def test_filter_search_and_approval_changes_are_read_only(self, network):
        first, second = self.preview(), self.preview()
        self.client.post(f"/api/outreach/previews/{second['activity_id']}/review",
                         json={'action': 'approve', 'revision': 1})
        before = [(a.id, a.summary) for a in Activity.query.all()]
        runs = AgentRun.query.count()
        queue = list_previews()
        self.assertEqual(queue['counts'], {'all': 2, 'draft': 1, 'approved': 1})
        self.assertEqual([p['id'] for p in queue['previews']], [second['activity_id'], first['activity_id']])
        self.assertEqual(list_previews('draft')['previews'][0]['id'], first['activity_id'])
        self.assertEqual(list_previews('approved')['previews'][0]['id'], second['activity_id'])
        for term in ('EXAMPLE CONSULTING', 'alex@firm.example', 'A question for'):
            self.assertEqual(list_previews(query=term)['total'], 2)
        self.assertEqual(list_previews(query='no-such-company')['total'], 0)
        for suffix in ('', '?status=draft', '?status=approved', '?q=alex', '?q=missing'):
            self.assertEqual(self.client.get('/outreach/queue' + suffix).status_code, 200)
        self.assertEqual([(a.id, a.summary) for a in Activity.query.all()], before)
        self.assertEqual(AgentRun.query.count(), runs)
        self.client.post(f"/api/outreach/previews/{second['activity_id']}/review",
                         json={'action': 'reopen', 'revision': 2})
        self.assertEqual(list_previews()['counts'], {'all': 2, 'draft': 2, 'approved': 0})
        network.assert_not_called()

    def test_pagination_and_invalid_query_parameters(self):
        sample = self.preview()
        stored = db.session.get(Activity, sample['activity_id'])
        for _ in range(22):
            db.session.add(Activity(account_id=stored.account_id, contact_id=stored.contact_id,
                                    activity_type='outreach_preview', summary=stored.summary))
        db.session.commit()
        one = list_previews(query='Example', page=1)
        two = list_previews(query='Example', page=2)
        self.assertEqual(len(one['previews']), 20)
        self.assertEqual(len(two['previews']), 3)
        self.assertFalse({p['id'] for p in one['previews']} & {p['id'] for p in two['previews']})
        self.assertEqual(list_previews(page=999)['page'], 2)
        self.assertIn(b'Next', self.client.get('/outreach/queue?q=Example').data)
        for suffix in ('?page=0', '?page=-1', '?page=no', '?status=sent', '?q=' + 'x'*201):
            self.assertEqual(self.client.get('/outreach/queue' + suffix).status_code, 400)

    def test_legacy_defaults_escaping_and_non_preview_exclusion(self):
        sample = self.preview()
        activity = db.session.get(Activity, sample['activity_id'])
        data = json.loads(activity.summary)
        for key in ('revision', 'review_status', 'review_history'):
            data.pop(key)
        data['company'] = '<script>Company</script>'
        activity.summary = json.dumps(data)
        db.session.add(Activity(account_id=activity.account_id, activity_type='note', summary='not json'))
        db.session.commit()
        queue = list_previews('draft')
        self.assertEqual(queue['total'], 1)
        self.assertEqual(queue['previews'][0]['revision'], 1)
        page = self.client.get('/outreach/queue')
        self.assertIn(b'&lt;script&gt;Company&lt;/script&gt;', page.data)
        self.assertNotIn(b'<script>', page.data)
        self.assertIn(f"/outreach?preview_id={activity.id}".encode(), page.data)
        self.assertIn(b'/outreach/queue', self.client.get('/').data)
        self.assertIn(b'/outreach/queue', self.client.get(f'/outreach?preview_id={activity.id}').data)

    def test_empty_queue_and_no_matches_explain_next_step(self):
        self.assertIn(b'No saved previews yet', self.client.get('/outreach/queue').data)
        self.assertIn(b'No approved previews yet', self.client.get('/outreach/queue?status=approved').data)
        self.assertIn(b'No previews need review', self.client.get('/outreach/queue?status=draft').data)
        self.assertIn(b'No matching previews', self.client.get('/outreach/queue?q=missing').data)
