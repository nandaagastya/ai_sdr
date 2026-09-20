import unittest
import test_record_reply
from app.agents.record_reply import record_reply
from app.agents.qualification import save_qualification,FIELDS
from app.models import db,Qualification,OutreachStop

class QualificationTests(unittest.TestCase):
    setUp=test_record_reply.RecordReplyTests.setUp
    tearDown=test_record_reply.RecordReplyTests.tearDown
    def test_partial_then_explicit_qualification_and_stale_revision(self):
        key=record_reply(self.c.email,'I am interested','interested')
        evidence={field:'' for field in FIELDS};evidence['need']='Reply says CRM help requested'
        save_qualification(key,0,evidence)
        self.assertEqual(self.c.pipeline_stage,'replied')
        with self.assertRaises(ValueError):save_qualification(key,1,evidence,True)
        with self.assertRaises(ValueError):save_qualification(key,0,evidence)
        evidence={field:'User supplied supporting note for '+field for field in FIELDS}
        save_qualification(key,1,evidence,True)
        self.assertEqual(self.c.pipeline_stage,'qualified')
        self.assertTrue(db.session.get(OutreachStop,self.c.email).active)
        self.assertTrue(db.session.get(Qualification,key).qualified)
        with self.assertRaises(ValueError):save_qualification(key,2,evidence,True)
    def test_opt_out_blocks_and_form_csrf(self):
        key=record_reply(self.c.email,'unsubscribe','unsubscribe')
        with self.assertRaises(ValueError):save_qualification(key,0,{field:'Evidence' for field in FIELDS},True)
        client=self.app.test_client()
        self.assertEqual(client.get(f'/replies/{key}').status_code,200)
        self.assertEqual(client.post(f'/replies/{key}/qualification').status_code,400)
