import copy
import json
import unittest
from unittest.mock import patch

import test_outreach
from app.models import db, Activity, Account, AgentRun, Task


class ReviewTests(unittest.TestCase):
    tearDown = test_outreach.OutreachTests.tearDown

    def setUp(self):
        test_outreach.OutreachTests.setUp(self)
        self.draft = self.client.post('/api/outreach/preview', json=self.payload).json
        self.preview_id = self.draft['activity_id']
        self.url = f'/api/outreach/previews/{self.preview_id}/review'
        self.messages = [{key: m[key] for key in ('subject', 'body')} for m in self.draft['messages']]

    def post(self, action, revision, **extra):
        return self.client.post(self.url, json={'action': action, 'revision': revision, **extra})

    @patch('requests.sessions.Session.request', side_effect=AssertionError('Unexpected network'))
    def test_approval_edit_reapproval_and_reopen_preserve_history_without_delivery(self, network):
        approved = self.post('approve', 1)
        self.assertEqual(approved.status_code, 200)
        self.assertEqual(approved.json['review_status'], 'approved')
        self.assertTrue(approved.json['approved_at'])
        self.messages[0]['subject'] = 'A revised subject'
        self.messages[0]['body'] = '<script>escaped</script>\nA factual offer.'
        edited = self.post('save', 2, messages=self.messages)
        self.assertEqual(edited.status_code, 200)
        self.assertEqual(edited.json['review_status'], 'draft')
        self.assertIsNone(edited.json['approved_at'])
        self.assertEqual(edited.json['revision'], 3)
        self.assertEqual(edited.json['review_history'][0]['messages'], self.draft['messages'])
        self.assertEqual(edited.json['review_history'][1]['review_status'], 'approved')
        self.assertEqual([m['suggested_day'] for m in edited.json['messages']], [0, 4, 9])
        self.assertEqual(edited.json['recipient'], self.draft['recipient'])
        self.assertEqual(edited.json['generation'], self.draft['generation'])
        self.assertEqual(self.post('approve', 3).json['revision'], 4)
        reopened = self.post('reopen', 4).json
        self.assertEqual(reopened['review_status'], 'draft')
        self.assertEqual(reopened['revision'], 5)
        for _ in range(2):
            page = self.client.get(f'/outreach?preview_id={self.preview_id}')
            self.assertIn(b'&lt;script&gt;', page.data)
            self.assertNotIn(b'<script>', page.data)
            self.assertIn(b'Revision history (4)', page.data)
        self.assertEqual(Activity.query.count(), 1)
        self.assertEqual(AgentRun.query.count(), 1)
        self.assertEqual(Account.query.one().stage, 'booked')
        self.assertEqual(Task.query.count(), 0)
        self.assertFalse(reopened['sent'])
        self.assertFalse(reopened['scheduled'])
        network.assert_not_called()

    def test_stale_tab_cannot_approve_or_overwrite_new_text(self):
        self.messages[0]['subject'] = 'New text'
        self.assertEqual(self.post('save', 1, messages=self.messages).status_code, 200)
        for action in ('save', 'approve', 'reopen'):
            response = self.post(action, 1, **({'messages': self.messages} if action == 'save' else {}))
            self.assertEqual(response.status_code, 409)
        stored = json.loads(db.session.get(Activity, self.preview_id).summary)
        self.assertEqual(stored['review_status'], 'draft')
        self.assertEqual(stored['revision'], 2)
        self.assertEqual(stored['messages'][0]['subject'], 'New text')

    def test_invalid_edits_and_unknown_fields_never_write(self):
        original = db.session.get(Activity, self.preview_id).summary
        invalid = [None, [], {}, {'action': 'send', 'revision': 1},
                   {'action': 'approve', 'revision': True},
                   {'action': 'approve', 'revision': 1, 'sent': True},
                   {'action': 'save', 'revision': 1, 'messages': []}]
        for key, value in [('subject', ''), ('subject', 'x' * 201), ('subject', 'header\ninjection'),
                           ('body', ' '), ('body', 'x' * 5001), ('body', '\x00bad'), ('body', 4)]:
            messages = copy.deepcopy(self.messages)
            messages[0][key] = value
            invalid.append({'action': 'save', 'revision': 1, 'messages': messages})
        messages = copy.deepcopy(self.messages)
        messages[0]['suggested_day'] = 1
        invalid.append({'action': 'save', 'revision': 1, 'messages': messages})
        for payload in invalid:
            with self.subTest(payload=payload):
                self.assertEqual(self.client.post(self.url, json=payload).status_code, 400)
                self.assertEqual(db.session.get(Activity, self.preview_id).summary, original)

    def test_legacy_preview_and_missing_or_wrong_activity(self):
        activity = db.session.get(Activity, self.preview_id)
        data = json.loads(activity.summary)
        for key in ('revision', 'review_status', 'review_history'):
            data.pop(key)
        activity.summary = json.dumps(data)
        db.session.commit()
        self.assertIn('Draft — needs review'.encode(), self.client.get(f'/outreach?preview_id={activity.id}').data)
        self.assertEqual(self.post('approve', 1).status_code, 200)
        activity.activity_type = 'note'
        db.session.commit()
        self.assertEqual(self.post('approve', 2).status_code, 404)
        self.assertEqual(self.client.post('/api/outreach/previews/999/review', json={'action': 'approve', 'revision': 1}).status_code, 404)

    def test_repeated_actions_and_unchanged_edits_do_not_grow_history(self):
        self.assertEqual(self.post('reopen', 1).json['revision'], 1)
        self.assertEqual(self.post('save', 1, messages=self.messages).json['revision'], 1)
        self.assertEqual(self.post('approve', 1).json['revision'], 2)
        self.assertEqual(self.post('approve', 2).json['revision'], 2)
        self.assertEqual(self.post('save', 2, messages=self.messages).json['review_status'], 'approved')

    def test_form_csrf_redirect_validation_and_conflict_preserve_edits(self):
        url = f'/outreach/{self.preview_id}/review'
        self.assertEqual(self.client.post(url, data={'action': 'approve', 'revision': '1'}).status_code, 400)
        self.client.get(f'/outreach?preview_id={self.preview_id}')
        with self.client.session_transaction() as session:
            token = session['review_csrf']
        data = {'action': 'save', 'revision': '1', 'csrf_token': token}
        for index, message in enumerate(self.messages, 1):
            data[f'subject_{index}'] = message['subject']
            data[f'body_{index}'] = message['body']
        data['subject_1'] = ''
        data['body_1'] = 'Keep my unsaved text'
        bad = self.client.post(url, data=data)
        self.assertEqual(bad.status_code, 400)
        self.assertIn(b'Keep my unsaved text', bad.data)
        data['subject_1'] = 'Changed'
        saved = self.client.post(url, data=data)
        self.assertEqual(saved.status_code, 303)
        self.assertIn(b'Changed', self.client.get(saved.location).data)
        stale = self.client.post(url, data=data)
        self.assertEqual(stale.status_code, 409)
        self.assertIn(b'Keep my unsaved text', stale.data)
        self.assertIn(b'Copy your edits', stale.data)
        approved = self.client.post(url, data={'action': 'approve', 'revision': '2', 'csrf_token': token})
        self.assertEqual(approved.status_code, 303)
        self.assertIn(b'Approved for review workflow', self.client.get(approved.location).data)

    def test_commit_failure_rolls_back_edit(self):
        original = db.session.get(Activity, self.preview_id).summary
        self.app.logger.disabled = True
        try:
            with patch.object(db.session, 'commit', side_effect=RuntimeError('disk error')):
                self.assertEqual(self.post('approve', 1).status_code, 500)
            self.assertEqual(db.session.get(Activity, self.preview_id).summary, original)
        finally:
            self.app.logger.disabled = False
