import json
import unittest
from unittest.mock import patch
from app import create_app
from app.models import db, Account, Contact, Activity, AgentRun, Task


class OutreachTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite://"})
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.client = self.app.test_client()
        account = Account(name="Example Consulting", domain="firm.example", stage="booked")
        db.session.add(account)
        db.session.flush()
        contact = Contact(account_id=account.id, first_name="Alex", title="CEO", email="alex@firm.example")
        db.session.add(contact)
        db.session.commit()
        self.contact_id = contact.id
        self.payload = {"contact_id": contact.id, "sender_name": "Nanda",
                        "offer": "We help teams prepare for sales conversations."}

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    @patch("requests.sessions.Session.request", side_effect=AssertionError("Unexpected network"))
    def test_preview_persists_without_sending_or_advancing(self, network):
        response = self.client.post("/api/outreach/preview", json=self.payload)
        self.assertEqual(response.status_code, 201)
        data = response.json
        self.assertFalse(data["sent"])
        self.assertFalse(data["scheduled"])
        self.assertEqual([m["suggested_day"] for m in data["messages"]], [0, 4, 9])
        self.assertIn("Hi Alex", data["messages"][0]["body"])
        self.assertIn(self.payload["offer"], data["messages"][0]["body"])
        self.assertEqual(Account.query.one().stage, "booked")
        self.assertEqual(Task.query.count(), 0)
        activity = Activity.query.one()
        self.assertEqual(activity.activity_type, "outreach_preview")
        self.assertEqual(json.loads(activity.summary)["messages"], data["messages"])
        self.assertEqual(AgentRun.query.one().status, "success")
        self.assertIn("Sent 0", AgentRun.query.one().detail)
        network.assert_not_called()

    def test_invalid_requests_do_not_write(self):
        for payload in [None, [], {}, {**self.payload, "contact_id": True},
                        {**self.payload, "contact_id": 999}, {**self.payload, "offer": ""},
                        {**self.payload, "sender_name": "a\nb"},
                        {**self.payload, "send": True}, {**self.payload, "offer": "x" * 601}]:
            with self.subTest(payload=payload):
                response = self.client.post("/api/outreach/preview", json=payload)
                self.assertEqual(response.status_code, 400)
        self.assertEqual(Activity.query.count(), 0)
        self.assertEqual(AgentRun.query.count(), 0)

    def test_missing_email_rejected(self):
        db.session.get(Contact, self.contact_id).email = None
        db.session.commit()
        self.assertEqual(self.client.post("/api/outreach/preview", json=self.payload).status_code, 400)

    def test_saved_page_refresh_does_not_regenerate_and_escapes_input(self):
        form = {**self.payload, "offer": "<script>alert('x')</script>"}
        response = self.client.post("/outreach", data=form)
        self.assertEqual(response.status_code, 303)
        for _ in range(2):
            page = self.client.get(response.headers["Location"])
            self.assertEqual(page.status_code, 200)
            self.assertIn(f"Saved preview #{Activity.query.one().id}".encode(), page.data)
            self.assertIn(b"&lt;script&gt;", page.data)
            self.assertNotIn(b"<script>", page.data)
        self.assertEqual(Activity.query.count(), 1)
        self.assertEqual(AgentRun.query.count(), 1)
        self.assertEqual(self.client.get("/outreach?preview_id=999").status_code, 404)
        self.assertIn(b'/outreach', self.client.get("/").data)

    @patch("pathlib.Path.read_text", side_effect=OSError("missing template"))
    def test_generation_error_closes_audit_and_rolls_back(self, read):
        response = self.client.post("/api/outreach/preview", json=self.payload)
        self.assertEqual(response.status_code, 500)
        self.assertEqual(Activity.query.count(), 0)
        run = AgentRun.query.one()
        self.assertEqual(run.status, "error")
        self.assertIsNotNone(run.finished_at)
        self.assertEqual(Account.query.one().stage, "booked")


if __name__ == "__main__":
    unittest.main()
