import unittest
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from common import Blocked
from task_handoff import prepare, evidence


class TaskHandoff(unittest.TestCase):
    def test_plan_is_bounded_and_digest_bound(self):
        item=prepare({'title':'Official task','url':'https://example.org/task','steps':['Open page','Submit after review']},100)
        self.assertEqual(item['id'],item['digest']);self.assertTrue(item['plan']['requires_user_confirmation'])
        self.assertNotIn('password',str(item))

    def test_non_https_or_missing_steps_rejected(self):
        with self.assertRaisesRegex(Blocked,'task_url_invalid'):
            prepare({'url':'http://example.org','steps':['x']})
        with self.assertRaisesRegex(Blocked,'task_steps_missing'):
            prepare({'url':'https://example.org'})

    def test_evidence_is_bounded(self):
        self.assertEqual(evidence('done'),'done')
        with self.assertRaisesRegex(Blocked,'task_evidence_invalid'):
            evidence('')
