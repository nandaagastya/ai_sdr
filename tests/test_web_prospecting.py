import json
import os
import unittest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

import test_outreach
from app.models import db, Account, Contact, Activity, AgentRun, WebDiscovery, ProspectCache
from app.services.public_web import normalize_url, public_ip, fetch_once, PublicCrawler, inspect_company, inspect_directory, MAX_BODY


def fixture(url):
    if url.endswith('/robots.txt'): return 200,{'Content-Type':'text/plain'},'User-agent: *\nAllow: /'
    if 'blocked.test' in url: return 403,{'Content-Type':'text/html'},'blocked'
    if url.endswith('/contact'): return 200,{'Content-Type':'text/html'},'<a href="mailto:hello@firm.example">Email</a>'
    return 200,{'Content-Type':'text/html'},'<html><title>Example Consulting</title><a href="/contact">Contact</a><script>stolen@firm.example</script><p>other@unrelated.example</p></html>'


class WebTests(unittest.TestCase):
    tearDown = test_outreach.OutreachTests.tearDown

    def setUp(self):
        test_outreach.OutreachTests.setUp(self)
        self.client.get('/leads/discover')
        with self.client.session_transaction() as session: self.token=session['web_csrf']

    @patch('requests.sessions.Session.request',side_effect=AssertionError('No Apollo or AI'))
    @patch('app.services.public_web.time.sleep')
    @patch('app.services.public_web.fetch_once',side_effect=fixture)
    def test_web_scan_review_save_cache_and_duplicate_safety(self,fetch,sleep,network):
        response=self.client.post('/leads/web/scan',data={'csrf_token':self.token,'urls':'https://firm.example'})
        self.assertEqual(response.status_code,303)
        self.assertEqual(Contact.query.count(),1)
        self.assertIn(b'hello@firm.example',self.client.get(response.location).data)
        self.assertNotIn(b'stolen@firm.example',self.client.get(response.location).data)
        self.assertNotIn(b'other@unrelated.example',self.client.get(response.location).data)
        self.assertEqual(fetch.call_count,3)
        again=self.client.post('/leads/web/scan',data={'csrf_token':self.token,'urls':'https://firm.example'})
        self.assertIn(b'0 web requests',self.client.get(again.location).data)
        self.assertEqual(fetch.call_count,3)
        saved=self.client.post(response.location,data={'csrf_token':self.token,'selected':'0','company_0':'Changed'})
        self.assertEqual(saved.status_code,303)
        self.assertEqual(Account.query.one().name,'Example Consulting')
        self.assertEqual(Account.query.one().stage,'booked')
        self.assertEqual(Contact.query.count(),2)
        self.client.post(response.location,data={'csrf_token':self.token,'selected':'0'})
        self.assertEqual(Contact.query.count(),2)
        self.client.post(again.location,data={'csrf_token':self.token,'selected':'0'})
        self.assertEqual(Contact.query.count(),2)
        self.assertTrue(Activity.query.filter_by(activity_type='web_source').first())
        network.assert_not_called()

    @patch('app.services.public_web.time.sleep')
    @patch('app.services.public_web.fetch_once',side_effect=fixture)
    def test_failed_site_never_falls_back_and_session_ownership(self,fetch,sleep):
        response=self.client.post('/leads/web/scan',data={'csrf_token':self.token,'urls':'https://blocked.test'})
        self.assertIn(b'HTTP 403',self.client.get(response.location).data)
        self.assertEqual(AgentRun.query.one().agent_name,'web_prospecting')
        self.assertEqual(AgentRun.query.one().status,'error')
        self.assertEqual(Account.query.count(),1)
        self.assertEqual(self.app.test_client().get(response.location).status_code,404)
        self.assertEqual(self.client.post(response.location,data={'selected':'0'}).status_code,400)
        self.assertEqual(self.client.post(response.location,data={'csrf_token':self.token,'selected':'0'}).status_code,400)

    def test_private_urls_and_bad_requests_are_rejected(self):
        for value in ('http://127.0.0.1','http://169.254.169.254','file:///etc/passwd','https://user:pass@example.com','http://localhost','https://example.com:8443','http://224.0.0.1'):
            with self.subTest(value=value), self.assertRaises(ValueError): normalize_url(value)
        self.assertEqual(self.client.post('/leads/web/scan',data={'urls':'example.com'}).status_code,400)
        self.assertEqual(self.client.post('/leads/web/scan',data={'csrf_token':self.token,'urls':'example.com\nexample.org','kind':'directory'}).status_code,400)
        for ip in ('127.0.0.1','10.0.0.1','169.254.169.254','224.0.0.1'):
            with patch('socket.getaddrinfo',return_value=[(2,1,6,'',(ip,0))]),self.assertRaises(ValueError): public_ip('public-looking.com')

    @patch('app.services.public_web.time.sleep')
    def test_robots_blocks_redirects_are_rechecked_and_directory_links_are_bounded(self,sleep):
        with patch('app.services.public_web.fetch_once',return_value=(200,{},'User-agent: *\nDisallow: /')) as fetch:
            with self.assertRaisesRegex(ValueError,'robots'): PublicCrawler().page('https://firm.example/')
            self.assertEqual(fetch.call_count,1)
        def redirect(url):
            return (404,{},'') if url.endswith('robots.txt') else (302,{'Location':'http://127.0.0.1/secret'},'')
        with patch('app.services.public_web.fetch_once',side_effect=redirect) as fetch:
            with self.assertRaises(ValueError): PublicCrawler().page('https://firm.example/')
            self.assertEqual(fetch.call_count,2)
        crawler=Mock(); crawler.page.return_value=('https://directory.example/', '<a href="https://firm.example/about">Firm</a><a href="https://firm.example/contact">Same</a><a href="https://facebook.com/a">Social</a><a href="javascript:bad">Bad</a>')
        self.assertEqual(inspect_directory(crawler,'https://directory.example/')['candidates'],['https://firm.example/'])

    def test_network_connection_pins_vetted_ip_and_limits_response(self):
        with patch('app.services.public_web.public_ip',return_value='93.184.216.34'),patch('app.services.public_web.urllib3.HTTPSConnectionPool') as pool:
            response=pool.return_value.urlopen.return_value
            response.read.return_value=b'hello'; response.status=200;response.headers={'Content-Type':'text/plain'}
            self.assertEqual(fetch_once('https://example.com/')[2],'hello')
            self.assertEqual(pool.call_args.args[0],'93.184.216.34')
            self.assertEqual(pool.call_args.kwargs['assert_hostname'],'example.com')
            self.assertEqual(pool.call_args.kwargs['server_hostname'],'example.com')
            self.assertFalse(pool.return_value.urlopen.call_args.kwargs['redirect'])
            response.read.return_value=b'x'*(MAX_BODY+1)
            with self.assertRaises(ValueError):fetch_once('https://example.com/')

    @patch('app.services.public_web.time.sleep')
    @patch('app.services.public_web.fetch_once',side_effect=fixture)
    def test_company_without_email_is_saveable_and_failed_commit_rolls_back(self,fetch,sleep):
        # fixture publishes only firm.example emails; another domain gets no contacts.
        response=self.client.post('/leads/web/scan',data={'csrf_token':self.token,'urls':'https://new.example'})
        self.assertIn(b'No same-domain email',self.client.get(response.location).data)
        self.app.logger.disabled=True
        try:
            with patch.object(db.session,'commit',side_effect=RuntimeError('disk')):
                self.assertEqual(self.client.post(response.location,data={'csrf_token':self.token,'selected':'0'}).status_code,400)
            self.assertEqual(Account.query.count(),1)
            self.client.post(response.location,data={'csrf_token':self.token,'selected':'0'})
            self.assertEqual(Account.query.count(),2)
            self.assertEqual(Contact.query.count(),1)
            self.assertEqual(Account.query.filter_by(domain='new.example').one().source,'web')
        finally:self.app.logger.disabled=False

    @patch.dict(os.environ,{'APOLLO_API_KEY':'fixture-only'})
    @patch('app.agents.prospecting.requests.post')
    def test_apollo_cache_targeted_lookup_refresh_and_expiry(self,post):
        post.return_value=Mock(status_code=200)
        post.return_value.json.return_value={'organizations':[{'name':'Example Consulting','primary_domain':'firm.example','estimated_num_employees':100,'industry':'Consulting','country':'United States'}]}
        payload={'domains':['https://www.firm.example/']}
        first=self.client.post('/api/prospect/run',json=payload)
        second=self.client.post('/api/prospect/run',json=payload)
        self.assertEqual(first.json['apollo_requests'],1)
        self.assertEqual(second.json['apollo_requests'],0)
        self.assertTrue(second.json['cached'])
        post.assert_called_once()
        self.assertEqual(post.call_args.kwargs['json'],{'q_organization_domains_list':['firm.example'],'per_page':10})
        self.assertEqual(Account.query.one().stage,'booked')
        self.client.post('/api/prospect/run',json={**payload,'refresh':True})
        self.assertEqual(post.call_count,2)
        cache=ProspectCache.query.filter_by(provider='apollo').one();cache.expires_at=datetime.utcnow()-timedelta(seconds=1);db.session.commit()
        self.client.post('/api/prospect/run',json=payload)
        self.assertEqual(post.call_count,3)
        for bad in ({'per_page':True},{'domains':'bad'},{'refresh':'yes'},{'send':True}):
            self.assertEqual(self.client.post('/api/prospect/run',json=bad).status_code,400)
