from unittest.mock import patch
import unittest
import test_delivery
from app.models import db, Contact, DeliverySimulation
from app.agents.review import review_preview
from app.agents.delivery import simulate_delivery
from app.services.eligibility import blocked_reason, set_stop

class EligibilityTests(unittest.TestCase):
    setUp = test_delivery.DeliveryTests.setUp
    tearDown = test_delivery.DeliveryTests.tearDown
    def test_stops_and_progress_block_before_provider(self):
        review_preview(self.id,{'action':'approve','revision':1})
        with patch('app.agents.delivery.FakeDeliveryProvider.deliver') as provider:
            for stage in ['outreach','replied','qualified','call_prepped','booked','called','logged','needs_review']:
                self.c.pipeline_stage=stage;db.session.commit()
                with self.assertRaises(ValueError):simulate_delivery(self.id,2)
            self.c.pipeline_stage='not_contacted';db.session.commit()
            for reason in ['paused','unsubscribe','bounced']:
                set_stop(self.c.email,reason);db.session.commit()
                with self.assertRaises(ValueError):simulate_delivery(self.id,2)
            provider.assert_not_called()
        self.assertEqual(DeliverySimulation.query.count(),0)
    def test_address_change_and_cross_contact_stop(self):
        self.c.email='changed@example.com';db.session.commit()
        self.assertIn('Recipient changed',blocked_reason(self.draft))
        self.c.email=self.draft['recipient'];db.session.commit()
        set_stop(self.c.email.upper(),'unsubscribe');db.session.commit()
        set_stop(self.c.email,'paused');db.session.commit()
        self.assertIn('unsubscribe',blocked_reason(self.draft))
        second=Contact(account_id=self.c.account_id,email=self.c.email);db.session.add(second);db.session.commit()
        self.assertIn('unsubscribe',blocked_reason({**self.draft,'contact_id':second.id}))
    def test_pause_form_blocks_new_simulation(self):
        review_preview(self.id,{'action':'approve','revision':1})
        client=self.app.test_client();client.get(f'/outreach?preview_id={self.id}')
        with client.session_transaction() as session:token=session['review_csrf']
        url=f'/outreach/{self.id}/pause'
        self.assertEqual(client.post(url).status_code,400)
        self.assertEqual(client.post(url,data={'csrf_token':token}).status_code,303)
        self.assertIn(b'Outreach stopped: paused',client.get(f'/outreach?preview_id={self.id}').data)
        self.assertEqual(client.post(f'/outreach/{self.id}/simulate',data={'csrf_token':token,'revision':2}).status_code,409)
        self.assertEqual(DeliverySimulation.query.count(),0)

    def test_resume_only_lifts_manual_pause(self):
        client=self.app.test_client();client.get(f'/outreach?preview_id={self.id}')
        with client.session_transaction() as session:token=session['review_csrf']
        set_stop(self.c.email,'paused');db.session.commit()
        client.post(f'/outreach/{self.id}/resume',data={'csrf_token':token})
        self.assertIsNone(blocked_reason(self.draft))
        set_stop(self.c.email,'unsubscribe');db.session.commit()
        client.post(f'/outreach/{self.id}/resume',data={'csrf_token':token})
        self.assertIn('unsubscribe',blocked_reason(self.draft))
