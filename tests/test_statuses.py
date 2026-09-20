import unittest
from sqlalchemy import create_engine, text
from app import create_app
from app.models import db, Account, Contact, Activity
from app.services.status_migration import upgrade
from app.services.statuses import advance_contact
from app.agents.outreach import preview_outreach
from app.agents.review import review_preview


class StatusTests(unittest.TestCase):
    def test_legacy_migration_preserves_history_and_is_repeatable(self):
        engine = create_engine('sqlite://')
        with engine.begin() as c:
            c.execute(text('CREATE TABLE accounts(id INTEGER PRIMARY KEY, stage TEXT, icp_fit_score INTEGER, icp_fit_reasons TEXT)'))
            c.execute(text('CREATE TABLE contacts(id INTEGER PRIMARY KEY, account_id INTEGER)'))
            c.execute(text("INSERT INTO accounts VALUES (1,'qualified',90,'match'),(2,'booked',100,'match')"))
            c.execute(text('INSERT INTO contacts VALUES (1,1),(2,2),(3,2)'))
        upgrade(engine)
        upgrade(engine)
        with engine.connect() as c:
            self.assertEqual(c.execute(text('SELECT stage,legacy_stage,fit_status FROM accounts ORDER BY id')).all(), [('new','qualified','strong_fit'),('booked','booked','strong_fit')])
            self.assertEqual(c.execute(text('SELECT pipeline_stage FROM contacts ORDER BY id')).scalars().all(), ['not_contacted','needs_review','needs_review'])
            self.assertEqual(c.execute(text('SELECT count(*) FROM schema_versions')).scalar(),1)

    def test_approval_does_not_advance_and_transitions_require_expected_state(self):
        app=create_app({'TESTING':True,'SQLALCHEMY_DATABASE_URI':'sqlite://'})
        with app.app_context():
            a=Account(name='Example',fit_status='strong_fit');db.session.add(a);db.session.flush()
            c=Contact(account_id=a.id,email='person@example.com');db.session.add(c);db.session.commit()
            draft=preview_outreach({'contact_id':c.id,'sender_name':'Sender','offer':'CRM support'})
            review_preview(draft['activity_id'],{'action':'approve','revision':1})
            self.assertEqual(c.pipeline_stage,'not_contacted')
            self.assertEqual(a.fit_status,'strong_fit')
            with self.assertRaises(ValueError): advance_contact(c.id,'not_contacted','qualified','event:1')
            with self.assertRaises(ValueError): advance_contact(c.id,'not_contacted','outreach','')
            advance_contact(c.id,'not_contacted','outreach','test-provider-event:1');db.session.commit()
            with self.assertRaises(ValueError): advance_contact(c.id,'not_contacted','outreach','test-provider-event:1')
            self.assertEqual(Activity.query.filter_by(activity_type='progress_changed').count(),1)
            html=app.test_client().get('/').get_data(as_text=True)
            self.assertIn('Strong fit',html);self.assertIn('Contact progress:',html)
