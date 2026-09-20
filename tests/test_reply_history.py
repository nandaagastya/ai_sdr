import unittest
import test_record_reply
from app.agents.record_reply import record_reply
from app.models import Activity,Task

class ReplyHistoryTests(unittest.TestCase):
    setUp=test_record_reply.RecordReplyTests.setUp
    tearDown=test_record_reply.RecordReplyTests.tearDown
    def test_history_detail_filters_and_read_only(self):
        key=record_reply(self.c.email,'<script>bad</script> I am interested','interested')
        client=self.app.test_client()
        self.assertIn(f'Reply #{key}'.encode(),client.get('/replies').data)
        self.assertIn(b'No saved replies',client.get('/replies?outcome=unsubscribe').data)
        detail=client.get(f'/replies/{key}')
        self.assertIn(b'&lt;script&gt;',detail.data);self.assertNotIn(b'<script>',detail.data)
        self.assertIn(b'Stopped: paused',detail.data)
        self.assertIn(b'Review interested reply',detail.data)
        self.assertEqual(Activity.query.count(),1);self.assertEqual(Task.query.count(),1)
        for url in ['/replies/999','/replies?page=0','/replies?page=bad','/replies?outcome=bad']:
            self.assertIn(client.get(url).status_code,[400,404])
    def test_pagination(self):
        for i in range(21):record_reply(self.c.email,f'Reply {i}','needs_review')
        client=self.app.test_client()
        self.assertIn(b'Next',client.get('/replies').data)
        self.assertIn(b'Previous',client.get('/replies?page=2').data)
