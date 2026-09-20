import unittest
from datetime import datetime,timedelta,timezone
import test_record_reply
from app.agents.record_reply import record_reply
from app.agents.qualification import save_qualification,FIELDS
from app.agents.call_prep import prepare_call
from app.agents.booking import confirm_meeting,change_meeting
from app.models import db,Task,MeetingChange,OutreachStop
class MeetingChangeTests(unittest.TestCase):
    setUp=test_record_reply.RecordReplyTests.setUp
    tearDown=test_record_reply.RecordReplyTests.tearDown
    def test_reschedule_cancel_stale_and_task(self):
        key=record_reply(self.c.email,'I am interested','interested')
        save_qualification(key,0,{f:'Evidence' for f in FIELDS},True);prepare_call(key)
        first=(datetime.now(timezone.utc)+timedelta(days=2)).isoformat()
        second=(datetime.now(timezone.utc)+timedelta(days=3)).isoformat()
        meeting=confirm_meeting(key,first,'Confirmed')
        task_id=meeting.task_id
        change_meeting(key,0,'reschedule',second,'New agreement')
        self.assertEqual(meeting.task_id,task_id)
        self.assertEqual(db.session.get(Task,task_id).due_at,datetime.fromisoformat(second).replace(tzinfo=None))
        with self.assertRaises(ValueError):change_meeting(key,0,'cancel','','Old tab')
        change_meeting(key,1,'cancel','','Prospect canceled')
        self.assertEqual(db.session.get(Task,task_id).status,'skipped')
        self.assertEqual(self.c.pipeline_stage,'needs_review')
        self.assertTrue(db.session.get(OutreachStop,self.c.email).active)
        self.assertEqual(MeetingChange.query.count(),2)
        with self.assertRaises(ValueError):change_meeting(key,2,'reschedule',second,'Retry')
        self.assertEqual(self.app.test_client().post(f'/replies/{key}/meeting/change').status_code,400)
