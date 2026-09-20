import unittest
from unittest.mock import patch
from app import create_app
from app.models import db, Account, Contact, Activity
from app.agents.outreach import preview_outreach
from app.agents.review import review_preview, get_preview

class RecipientWordingTests(unittest.TestCase):
    def test_named_shared_and_unknown_use_appropriate_facts(self):
        app=create_app({'TESTING':True,'SQLALCHEMY_DATABASE_URI':'sqlite://'})
        with app.app_context():
            a=Account(name='Example');db.session.add(a);db.session.flush()
            for email,name,title,expected in [('alex@example.com','Alex','CEO','named contact'),('info@example.com','Alex','CEO','shared inbox'),('someone@example.com',None,'Public website contact','unnamed contact')]:
                c=Contact(account_id=a.id,email=email,first_name=name,title=title);db.session.add(c);db.session.commit()
                draft=preview_outreach({'contact_id':c.id,'sender_name':'Nanda','offer':'CRM support'})
                self.assertEqual(draft['recipient_type'],expected)
                self.assertIn('Hi Alex,' if expected=='named contact' else 'Hi team,',draft['messages'][0]['body'])
                self.assertEqual(draft['personalization_facts']['title'],'CEO' if expected=='named contact' else '')
                self.assertNotIn('Public website contact',draft['messages'][0]['body'])

    @patch('app.agents.outreach.generate_opening',side_effect=RuntimeError('provider unavailable'))
    def test_failed_ai_attempt_preserves_approved_revision(self,provider):
        app=create_app({'TESTING':True,'SQLALCHEMY_DATABASE_URI':'sqlite://','OPENAI_API_KEY':'test','OPENAI_MODEL':'test'})
        with app.app_context():
            a=Account(name='Example');db.session.add(a);db.session.flush()
            c=Contact(account_id=a.id,email='info@example.com',title='Public website contact');db.session.add(c);db.session.commit()
            payload={'contact_id':c.id,'sender_name':'Nanda','offer':'CRM support'}
            draft=preview_outreach(payload)
            review_preview(draft['activity_id'],{'action':'approve','revision':1})
            before=Activity.query.one().summary
            with self.assertRaises(RuntimeError): preview_outreach({**payload,'personalization':'ai'})
            provider.assert_called_once()
            self.assertEqual(provider.call_args.args[0]['title'],'')
            self.assertEqual(Activity.query.one().summary,before)
            self.assertEqual(get_preview(draft['activity_id'])['review_status'],'approved')
