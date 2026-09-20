import json
import unittest
from unittest.mock import patch
from app import create_app
from app.models import db, Account, Contact, DeliverySimulation
from app.agents.outreach import preview_outreach
from app.agents.review import review_preview
from app.agents.delivery import simulate_delivery

class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.app=create_app({'TESTING':True,'SQLALCHEMY_DATABASE_URI':'sqlite://','SECRET_KEY':'test'})
        self.ctx=self.app.app_context();self.ctx.push()
        a=Account(name='Example');db.session.add(a);db.session.flush()
        self.c=Contact(account_id=a.id,email='hello@example.com');db.session.add(self.c);db.session.commit()
        self.draft=preview_outreach({'contact_id':self.c.id,'sender_name':'Nanda','offer':'CRM support'})
        self.id=self.draft['activity_id']
    def tearDown(self):
        db.session.remove();self.ctx.pop()
    def test_approval_duplicate_and_snapshot(self):
        with self.assertRaises(ValueError):simulate_delivery(self.id,1)
        review_preview(self.id,{'action':'approve','revision':1})
        with patch('requests.sessions.Session.request',side_effect=AssertionError('No network')):
            first=simulate_delivery(self.id,2)
            self.assertEqual(simulate_delivery(self.id,2),first)
        self.assertEqual(DeliverySimulation.query.count(),1)
        receipt=DeliverySimulation.query.one()
        self.assertEqual(json.loads(receipt.snapshot)['message'],self.draft['messages'][0])
        self.assertEqual(self.c.pipeline_stage,'not_contacted')
        review_preview(self.id,{'action':'reopen','revision':2})
        with self.assertRaises(ValueError):simulate_delivery(self.id,2)
        self.assertEqual(DeliverySimulation.query.count(),1)
    def test_failure_rolls_back_and_form_requires_csrf(self):
        review_preview(self.id,{'action':'approve','revision':1})
        with patch('app.agents.delivery.FakeDeliveryProvider.deliver',side_effect=RuntimeError('fake failure')):
            with self.assertRaises(RuntimeError):simulate_delivery(self.id,2)
        self.assertEqual(DeliverySimulation.query.count(),0)
        self.assertIsInstance(simulate_delivery(self.id,2),int)
        client=self.app.test_client()
        self.assertEqual(client.post(f'/outreach/{self.id}/simulate',data={'revision':2}).status_code,400)
        client.get(f'/outreach?preview_id={self.id}')
        with client.session_transaction() as session:token=session['review_csrf']
        self.assertEqual(client.post(f'/outreach/{self.id}/simulate',data={'revision':2,'csrf_token':token}).status_code,303)
        self.assertEqual(DeliverySimulation.query.count(),1)
