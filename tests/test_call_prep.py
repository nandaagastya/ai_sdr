import unittest
from unittest.mock import patch
import test_record_reply
from app.agents.record_reply import record_reply
from app.agents.qualification import save_qualification,FIELDS
from app.agents.call_prep import prepare_call
from app.models import db,CallBrief,Task,OutreachStop

class CallPrepTests(unittest.TestCase):
    setUp=test_record_reply.RecordReplyTests.setUp
    tearDown=test_record_reply.RecordReplyTests.tearDown
    def test_qualified_snapshot_repeat_and_source(self):
        key=record_reply(self.c.email,'I am interested','interested')
        with self.assertRaises(ValueError):prepare_call(key)
        save_qualification(key,0,{f:'Example evidence '+f for f in FIELDS},True)
        with patch('requests.sessions.Session.request',side_effect=AssertionError('network')):
            brief=prepare_call(key);before=brief.snapshot
            self.assertEqual(prepare_call(key).snapshot,before)
        self.assertEqual(CallBrief.query.count(),1);self.assertEqual(Task.query.count(),2)
        self.assertEqual(self.c.pipeline_stage,'call_prepped')
        self.assertTrue(db.session.get(OutreachStop,self.c.email).active)
        self.assertIn(b'Example evidence budget',self.app.test_client().get(f'/replies/{key}/call-brief').data)
    def test_failure_rolls_back(self):
        key=record_reply(self.c.email,'I am interested','interested')
        save_qualification(key,0,{f:'Evidence' for f in FIELDS},True)
        with patch('app.agents.call_prep.advance_contact',side_effect=ValueError('conflict')):
            with self.assertRaises(ValueError):prepare_call(key)
        self.assertEqual(CallBrief.query.count(),0)
        self.assertEqual(self.c.pipeline_stage,'qualified')
        self.assertEqual(self.app.test_client().post(f'/replies/{key}/call-brief').status_code,400)
