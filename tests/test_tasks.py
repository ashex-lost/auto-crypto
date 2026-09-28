import unittest
from tasks import assess_task
from policy import prescreen,proposal
from common import Blocked,now

class TaskRules(unittest.TestCase):
    def data(self):
        return dict(ends_at=now()+86400,automation='allowed',eligibility='confirmed',requires_trading=False,
                    requires_deposit=False,requires_public_post=False,reward_kind='fixed',reward_per_person_usd_micro=10000000,
                    costs_usd_micro={k:0 for k in ('gas','trading','claim','ai','hosting','other')},human_minutes=10)
    def test_pool_and_points_are_not_income(self):
        for kind in ('raffle','points','unannounced'):
            r=assess_task({**self.data(),'reward_kind':kind,'pool_usd_micro':500000000})
            self.assertIsNone(r['conditional_net_usd_micro']);self.assertIsNone(r['payout_probability'])
    def test_unknown_cost_and_permission_block(self):
        d=self.data();d['costs_usd_micro']['claim']=None;d['automation']='unknown'
        r=assess_task(d);self.assertIsNone(r['conditional_net_usd_micro']);self.assertFalse(r['eligible_for_analysis'])
    def test_pass_is_never_execution_approval(self):
        r=assess_task(self.data());self.assertEqual(r['conditional_net_usd_micro'],10000000)
        self.assertFalse(r['execution_supported']);self.assertFalse(r['participation_approved'])
    def test_stale_tasks_cannot_go_to_model(self):
        r=prescreen({'source':'task','data':self.data(),'observed_at':1})
        self.assertFalse(r['eligible_for_analysis'])

class ExecutionBoundary(unittest.IsolatedAsyncioTestCase):
    async def test_task_cannot_enter_vault_executor(self):
        with self.assertRaisesRegex(Blocked,'task_executor_not_connected'):
            await proposal(None,{}, {'source':'task'}, {},None)
