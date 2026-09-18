import os
import unittest
from unittest.mock import Mock, patch

from app import create_app
from app.models import db, Account, AgentRun
from app.agents.prospecting import score_icp_fit

ORG = {"name": "Demo Consulting", "primary_domain": "demo.example",
       "estimated_num_employees": 120, "industry": "Salesforce Consulting",
       "country": "United States"}


class BaselineTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite://"})
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_dashboard_and_read_endpoints(self):
        account = Account(name="Demo", domain="demo.example")
        db.session.add(account)
        db.session.commit()
        for path in ["/", "/api/accounts", f"/api/accounts/{account.id}",
                     "/api/contacts", "/api/tasks", "/api/agent-runs", "/api/pipeline"]:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)
        self.assertEqual(self.client.get("/api/accounts/999").status_code, 404)
        self.assertEqual(self.client.get("/api/pipeline").json["total_accounts"], 1)

    def test_scoring_explains_points(self):
        score, reasons = score_icp_fit(ORG)
        self.assertEqual(score, 100)
        self.assertEqual(len(reasons), 4)

    @patch.dict(os.environ, {"APOLLO_API_KEY": ""})
    @patch("app.agents.prospecting.requests.post")
    def test_missing_key_is_audited_without_network(self, post):
        response = self.client.post("/api/prospect/run", json={})
        self.assertEqual(response.status_code, 502)
        post.assert_not_called()
        run = db.session.get(AgentRun, response.json["agent_run_id"])
        self.assertEqual(run.status, "error")
        self.assertIsNotNone(run.finished_at)

    @patch.dict(os.environ, {"APOLLO_API_KEY": "test-placeholder"})
    @patch("app.agents.prospecting.requests.post")
    def test_repeat_prospecting_preserves_booked_stage(self, post):
        post.return_value = Mock(status_code=200)
        post.return_value.json.return_value = {"organizations": [ORG]}
        self.assertEqual(self.client.post("/api/prospect/run", json={}).status_code, 200)
        account = Account.query.one()
        account.stage = "booked"
        db.session.commit()
        self.assertEqual(self.client.post("/api/prospect/run", json={}).status_code, 200)
        self.assertEqual(Account.query.count(), 1)
        self.assertEqual(Account.query.one().stage, "booked")
        self.assertEqual(AgentRun.query.filter_by(status="success").count(), 2)

    @patch.dict(os.environ, {"APOLLO_API_KEY": "test-placeholder"})
    @patch("app.agents.prospecting.requests.post")
    def test_provider_failure_is_audited(self, post):
        post.return_value = Mock(status_code=429, text="rate limited")
        self.assertEqual(self.client.post("/api/prospect/run", json={}).status_code, 502)
        self.assertEqual(Account.query.count(), 0)
        self.assertEqual(AgentRun.query.one().status, "error")


if __name__ == "__main__":
    unittest.main()
