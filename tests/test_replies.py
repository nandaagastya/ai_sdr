import unittest
from unittest.mock import patch
from app import create_app
from app.models import db,Activity,AgentRun
from app.agents.replies import classify_reply

class ReplyTests(unittest.TestCase):
    def test_common_intents_and_unknown_qualification(self):
        for text,expected in [('Please unsubscribe me','unsubscribe'),('No thanks','not_interested'),('I am out of office','out_of_office'),('Please contact Jane','referral'),("I am interested. Let's talk",'interested'),('Thank you','needs_review')]:
            result=classify_reply(text)
            self.assertEqual(result['category'],expected)
            self.assertTrue(result['needs_review'])
            self.assertEqual(set(result['qualification'].values()),{'Unknown'})
    def test_mixed_negated_conditional_and_quoted_intent(self):
        for text in ["I am not interested but let's talk", "If I am interested I will reply", "I am interested\nPlease unsubscribe me","> I am interested\nNo update yet"]:
            self.assertEqual(classify_reply(text)['category'],'needs_review')
        result=classify_reply('No thanks\nOn Tuesday Alex wrote:\nI am interested')
        self.assertEqual(result['category'],'not_interested')
        self.assertTrue(result['history_removed'])
    def test_page_is_local_read_only_and_escapes_text(self):
        app=create_app({'TESTING':True,'SQLALCHEMY_DATABASE_URI':'sqlite://'})
        with app.app_context(), patch('requests.sessions.Session.request',side_effect=AssertionError('network')):
            client=app.test_client()
            response=client.post('/replies/review',data={'reply':'<script>alert(1)</script> I am interested'})
            self.assertEqual(response.status_code,200)
            self.assertNotIn(b'<script>',response.data)
            self.assertEqual(Activity.query.count(),0);self.assertEqual(AgentRun.query.count(),0)
            self.assertEqual(client.post('/replies/review',data={'reply':''}).status_code,400)
            self.assertEqual(client.post('/replies/review',data={'reply':'x'*10001}).status_code,400)
