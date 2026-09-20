import os
import unittest
from unittest.mock import patch, Mock
from app import create_app
from app.models import db, Account
from app.services.lead_quality import assess, apply_quality

class LeadQualityTests(unittest.TestCase):
    def test_target_generic_and_unknown_are_distinct(self):
        self.assertEqual(assess(industry='Salesforce consulting',employees=120,location='US',domain='firm.example')[::2],(100,'strong_fit'))
        score,reasons,status=assess(name='Salesforce Consulting',industry='Management consulting',employees=120,location='US',domain='firm.example')
        self.assertEqual(score,70);self.assertNotEqual(status,'strong_fit')
        self.assertIn('Industry does not establish Salesforce services (+0)',reasons)
        score,reasons,status=assess(domain='firm.example')
        self.assertEqual((score,status),(10,'unassessed'))
        self.assertIn('Location unknown (+0)',reasons)
        self.assertEqual(assess(industry='Salesforce consulting',employees=120,domain='firm.example')[0],80)

    def test_bad_employee_values_and_domains_do_not_crash_or_earn_points(self):
        for value in [True,'many',-1,1.5,{},None]:
            self.assertEqual(assess(employees=value)[0],0)
        self.assertEqual(assess(domain='https://[')[0],0)
        self.assertEqual(assess(employees=800)[2],'low_fit')

    @patch.dict(os.environ,{'APOLLO_API_KEY':'test'})
    @patch('app.agents.prospecting.requests.post')
    def test_partial_apollo_preserves_facts_and_progress(self,post):
        app=create_app({'TESTING':True,'SQLALCHEMY_DATABASE_URI':'sqlite://'})
        with app.app_context():
            a=Account(name='Saved company',domain='firm.example',industry='Salesforce consulting',employee_count=120,location='US',stage='booked',source='import')
            db.session.add(a);db.session.commit()
            post.return_value=Mock(status_code=200,json=lambda:{'organizations':[{'primary_domain':'firm.example','name':'','industry':None,'estimated_num_employees':'invalid'}]})
            response=app.test_client().post('/api/prospect/run',json={})
            self.assertEqual(response.status_code,200)
            self.assertEqual((a.name,a.employee_count,a.location,a.stage),('Saved company',120,'US','booked'))
            self.assertEqual((a.fit_status,a.icp_fit_score),('strong_fit',100))
            self.assertTrue(a.icp_fit_reasons.startswith('icp-v2'))

    def test_same_facts_get_same_quality_regardless_of_source(self):
        for source in ['web','import','apollo']:
            account=Account(name='Firm',industry='Salesforce implementation',employee_count=100,location='United States',domain='firm.example',source=source)
            apply_quality(account)
            self.assertEqual((account.fit_status,account.icp_fit_score),('strong_fit',100))
