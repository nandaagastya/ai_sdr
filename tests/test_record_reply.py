import unittest
from unittest.mock import patch
from app import create_app
from app.models import db,Account,Contact,Activity,Task,OutreachStop,RecordedReply
from app.agents.record_reply import record_reply

class RecordReplyTests(unittest.TestCase):
    def setUp(self):
        self.app=create_app({'TESTING':True,'SQLALCHEMY_DATABASE_URI':'sqlite://','SECRET_KEY':'test'})
        self.ctx=self.app.app_context();self.ctx.push()
        a=Account(name='Example',stage='booked');db.session.add(a);db.session.flush()
        self.c=Contact(account_id=a.id,email='alex@example.com',pipeline_stage='outreach');db.session.add(self.c);db.session.commit()
    def tearDown(self):db.session.remove();self.ctx.pop()
    def test_interest_duplicate_and_changed_outcome(self):
        with patch('requests.sessions.Session.request',side_effect=AssertionError('network')):
            first=record_reply('ALEX@example.com','I am interested','interested')
            self.assertEqual(record_reply('alex@example.com','I am interested','interested'),first)
        self.assertEqual(Activity.query.count(),1);self.assertEqual(Task.query.count(),1)
        self.assertEqual(self.c.pipeline_stage,'replied');self.assertEqual(self.c.account.stage,'booked')
        self.assertTrue(db.session.get(OutreachStop,self.c.email).active)
        with self.assertRaises(ValueError):record_reply(self.c.email,'I am interested','unsubscribe')
    def test_unsubscribe_blocks_and_preserves_advanced_contact(self):
        self.c.pipeline_stage='booked';db.session.commit()
        record_reply(self.c.email,'Remove me','unsubscribe')
        self.assertEqual(db.session.get(OutreachStop,self.c.email).reason,'unsubscribe')
        self.assertEqual(self.c.pipeline_stage,'booked');self.assertEqual(Task.query.count(),0)
    def test_ambiguous_sender_and_rollback(self):
        with self.assertRaises(ValueError):record_reply('missing@example.com','hello','needs_review')
        with patch('app.agents.record_reply.set_stop',side_effect=RuntimeError('failure')):
            with self.assertRaises(RuntimeError):record_reply(self.c.email,'hello','needs_review')
        self.assertEqual(RecordedReply.query.count(),0);self.assertEqual(Activity.query.count(),0)
        db.session.add(Contact(account_id=self.c.account_id,email=self.c.email));db.session.commit()
        with self.assertRaises(ValueError):record_reply(self.c.email,'hello','needs_review')
    def test_form_csrf_and_receipt(self):
        client=self.app.test_client();client.get('/replies/review')
        data={'action':'record','reply':'unsubscribe','sender':self.c.email,'outcome':'unsubscribe'}
        self.assertEqual(client.post('/replies/review',data=data).status_code,400)
        with client.session_transaction() as session:data['csrf_token']=session['reply_csrf']
        response=client.post('/replies/review',data=data)
        self.assertIn(b'Reply recorded as activity #',response.data)
        self.assertEqual(response.status_code,200)
