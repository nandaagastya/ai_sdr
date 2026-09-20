import unittest
from datetime import datetime,timedelta,timezone
import test_record_reply
from app.models import db,Task,Activity
from app.agents.record_reply import record_reply
from app.agents.qualification import save_qualification,FIELDS
from app.agents.call_prep import prepare_call
from app.agents.booking import confirm_meeting
from app.agents.post_call import log_call
from app.services.workflow import next_actions,task_context
class WorkflowTests(unittest.TestCase):
    setUp=test_record_reply.RecordReplyTests.setUp
    tearDown=test_record_reply.RecordReplyTests.tearDown
    def test_full_manual_flow_and_resolved_steps(self):
        key=record_reply(self.c.email,'I am interested','interested')
        task=Task.query.one()
        self.assertEqual(next_actions()[0]['label'],'Complete qualification')
        save_qualification(key,0,{f:'Evidence' for f in FIELDS},True)
        self.assertTrue(task_context(task)['resolved'])
        self.assertEqual(next_actions()[0]['label'],'Prepare call brief')
        prepare_call(key);self.assertEqual(next_actions()[0]['label'],'Record agreed meeting')
        meeting=confirm_meeting(key,(datetime.now(timezone.utc)+timedelta(days=1)).isoformat(),'Agreed')
        self.assertEqual(next_actions()[0]['label'],'Review upcoming call')
        meeting.starts_at=datetime.utcnow()-timedelta(hours=1);db.session.commit()
        self.assertEqual(next_actions()[0]['label'],'Log call outcome')
        log_call(key,'follow_up','Notes','Review proposal',(datetime.now(timezone.utc)+timedelta(days=2)).isoformat())
        self.assertEqual(next_actions()[0]['label'],'Review post-call follow-up')
        follow=Task.query.filter_by(description='Review proposal').one();follow.status='done';db.session.commit()
        self.assertEqual(next_actions(),[])
        count=Activity.query.count()
        client=self.app.test_client()
        for path in ['/','/tasks','/workflow']:self.assertEqual(client.get(path).status_code,200)
        self.assertEqual(Activity.query.count(),count)
    def test_stop_overrides_and_latest_reply_only(self):
        record_reply(self.c.email,'Interested','interested')
        record_reply(self.c.email,'Remove me','unsubscribe')
        actions=next_actions()
        self.assertEqual(len(actions),1)
        self.assertEqual(actions[0]['label'],'Review contact restriction')
