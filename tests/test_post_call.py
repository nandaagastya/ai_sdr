import unittest
from datetime import datetime,timedelta,timezone
import test_record_reply
from app.agents.record_reply import record_reply
from app.agents.qualification import save_qualification,FIELDS
from app.agents.call_prep import prepare_call
from app.agents.booking import confirm_meeting,change_meeting
from app.agents.post_call import log_call
from app.models import db,Task,CallOutcome
class PostCallTests(unittest.TestCase):
    setUp=test_record_reply.RecordReplyTests.setUp
    tearDown=test_record_reply.RecordReplyTests.tearDown
    def setup_meeting(self):
        key=record_reply(self.c.email,'I am interested','interested')
        save_qualification(key,0,{f:'Evidence' for f in FIELDS},True);prepare_call(key)
        meeting=confirm_meeting(key,(datetime.now(timezone.utc)+timedelta(days=1)).isoformat(),'Agreed')
        return key,meeting
    def test_completion_retry_and_future_guard(self):
        key,meeting=self.setup_meeting()
        with self.assertRaises(ValueError):log_call(key,'won','Good call','','')
        meeting.starts_at=datetime.utcnow()-timedelta(hours=1);db.session.commit()
        due=(datetime.now(timezone.utc)+timedelta(days=2)).isoformat()
        log_call(key,'follow_up','Discussed proposal','Send reviewed proposal',due)
        total=Task.query.count();log_call(key,'follow_up','Discussed proposal','Send reviewed proposal',due)
        self.assertEqual(Task.query.count(),total);self.assertEqual(CallOutcome.query.count(),1)
        self.assertEqual(db.session.get(Task,meeting.task_id).status,'done');self.assertEqual(self.c.pipeline_stage,'logged')
        with self.assertRaises(ValueError):log_call(key,'lost','Changed','','')
    def test_canceled_call_and_csrf(self):
        key,meeting=self.setup_meeting();change_meeting(key,0,'cancel','','Canceled')
        with self.assertRaises(ValueError):log_call(key,'won','Call','','')
        self.assertEqual(self.app.test_client().post(f'/replies/{key}/call-outcome').status_code,400)
