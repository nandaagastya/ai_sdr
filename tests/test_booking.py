import unittest
from datetime import datetime,timedelta,timezone
import test_record_reply
from app.agents.record_reply import record_reply
from app.agents.qualification import save_qualification,FIELDS
from app.agents.call_prep import prepare_call
from app.agents.booking import confirm_meeting
from app.models import Meeting,Task
class BookingTests(unittest.TestCase):
    setUp=test_record_reply.RecordReplyTests.setUp
    tearDown=test_record_reply.RecordReplyTests.tearDown
    def test_confirmation_timezone_repeat_and_invalid(self):
        key=record_reply(self.c.email,'I am interested','interested')
        save_qualification(key,0,{f:'Synthetic evidence' for f in FIELDS},True);prepare_call(key)
        for value in ['bad','2030-01-01T12:00','2000-01-01T12:00+00:00']:
            with self.assertRaises(ValueError):confirm_meeting(key,value,'Confirmed')
        when=(datetime.now(timezone.utc)+timedelta(days=2)).isoformat()
        first=confirm_meeting(key,when,'Synthetic agreement')
        self.assertEqual(confirm_meeting(key,when,'Synthetic agreement').task_id,first.task_id)
        self.assertEqual(Meeting.query.count(),1);self.assertEqual(self.c.pipeline_stage,'booked')
        self.assertEqual(Task.query.filter(Task.id==first.task_id).one().due_at,first.starts_at)
        with self.assertRaises(ValueError):confirm_meeting(key,when,'Changed agreement')
        client=self.app.test_client()
        self.assertEqual(client.post(f'/replies/{key}/meeting').status_code,400)
        self.assertIn(b'Meeting recorded',client.get(f'/replies/{key}/call-brief').data)
