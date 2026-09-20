import json
import unittest
from datetime import datetime, timedelta, timezone
import test_post_call
from app.models import db, Task, RecordCorrection, Qualification, CallBrief, OutreachStop
from app.agents.corrections import correct_outcome, correct_qualification
from app.agents.post_call import log_call
from app.agents.qualification import FIELDS
from app.services.workflow_tasks import linked_tasks
from app.services.workflow import task_contexts


class CorrectionTests(unittest.TestCase):
    setUp = test_post_call.PostCallTests.setUp
    tearDown = test_post_call.PostCallTests.tearDown
    setup_meeting = test_post_call.PostCallTests.setup_meeting

    def test_outcome_changes_only_linked_task_and_rejects_stale_edit(self):
        key, meeting = self.setup_meeting()
        meeting.starts_at = datetime.utcnow() - timedelta(hours=1)
        db.session.commit()
        due = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
        log_call(key, 'follow_up', 'Discussed', 'Send proposal', due)
        original = linked_tasks(key, 'follow_up')[0]
        original.description = 'Human renamed this task'
        unrelated = Task(account_id=self.c.account_id, description='Send proposal', owner='human', status='open')
        db.session.add(unrelated)
        db.session.commit()
        correct_outcome(key, 0, 'won', 'Agreement confirmed', '', '', 'Reviewer', 'Corrected outcome')
        self.assertEqual(original.status, 'skipped')
        self.assertEqual(unrelated.status, 'open')
        self.assertEqual(RecordCorrection.query.count(), 1)
        self.assertEqual(json.loads(RecordCorrection.query.one().before)['outcome'], 'follow_up')
        with self.assertRaises(ValueError):
            correct_outcome(key, 0, 'lost', 'Stale', '', '', 'Reviewer', 'Old form')
        self.assertTrue(db.session.get(OutreachStop, self.c.email).active)

    def test_qualification_correction_preserves_brief_and_flags_review(self):
        key, meeting = self.setup_meeting()
        brief = db.session.get(CallBrief, key)
        evidence = {f: 'Corrected evidence' for f in FIELDS}
        revision = db.session.get(Qualification, key).revision
        correct_qualification(key, revision, evidence, True, 'Reviewer', 'New evidence')
        self.assertIs(db.session.get(CallBrief, key), brief)
        self.assertEqual(self.c.pipeline_stage, 'needs_review')
        self.assertEqual(len(linked_tasks(key, 'correction_review')), 1)
        self.assertIn(b'Qualification changed since this brief was saved',
                      self.app.test_client().get(f'/replies/{key}/call-brief').data)
        with self.assertRaises(ValueError):
            correct_qualification(key, revision, evidence, False, 'Reviewer', 'Stale')

    def test_correction_form_and_csrf(self):
        key, meeting = self.setup_meeting()
        client = self.app.test_client()
        url = f'/replies/{key}/correct/qualification'
        self.assertEqual(client.get(url).status_code, 200)
        self.assertEqual(client.post(url).status_code, 400)
        with client.session_transaction() as session:
            token = session['correction_csrf']
        response = client.post(url, data={**{f: 'Updated evidence' for f in FIELDS},
            'csrf_token': token, 'revision': db.session.get(Qualification, key).revision,
            'decision': 'keep', 'reviewer': 'Test reviewer', 'reason': 'Verified change'})
        self.assertEqual(response.status_code, 303)
        self.assertIn(b'Verified change', client.get(url).data)

    def test_task_rename_preserves_source(self):
        key, meeting = self.setup_meeting()
        task = linked_tasks(key, 'meeting')[0]
        task.description = 'A completely different description'
        db.session.commit()
        contexts = task_contexts([task])
        self.assertEqual(contexts[task.id]['url'], f'/replies/{key}/call-brief')

    def test_legacy_backfill_is_explicit_and_idempotent(self):
        from app.models import WorkflowTask
        from app.services.legacy_task_links import candidates, apply_selected
        key, meeting = self.setup_meeting()
        db.session.delete(db.session.get(WorkflowTask, meeting.task_id))
        db.session.commit()
        self.assertEqual(candidates()[meeting.task_id], (key, 'meeting'))
        self.assertIsNone(db.session.get(WorkflowTask, meeting.task_id))
        apply_selected([meeting.task_id])
        apply_selected([meeting.task_id])
        self.assertEqual(len(linked_tasks(key, 'meeting')), 1)

    def test_legacy_ambiguous_tasks_remain_unlinked(self):
        from app.models import WorkflowTask
        from app.services.legacy_task_links import candidates, apply_selected
        key, meeting = self.setup_meeting()
        task = linked_tasks(key, 'brief_review')[0]
        db.session.delete(db.session.get(WorkflowTask, task.id))
        duplicate = Task(account_id=task.account_id, description=task.description, owner='human', status='open')
        db.session.add(duplicate)
        db.session.commit()
        self.assertIsNone(candidates()[task.id])
        with self.assertRaises(ValueError):
            apply_selected([task.id])
        self.assertIsNone(db.session.get(WorkflowTask, task.id))
