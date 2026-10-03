"""EV ranking, category learning and console overrides."""
import json
import unittest
from types import SimpleNamespace
from test_core import D1
from storage import Store
from config import settings, load_settings
from common import Blocked
from strategy import expected_value, calibrated, DEFAULT_PRIORS, report
from test_endpoints import Req, TOKEN
import worker


def s(**kw):
    base=settings(SimpleNamespace());base.update(human_hour_usd_micro=60_000_000);base.update(kw);return base


class EV(unittest.TestCase):
    def test_time_dominates_small_tasks(self):
        r=expected_value('fixed_task',{'cash_cost_usd':0,'human_minutes':15,'per_person_usd':5},s())
        self.assertLess(r['ev_usd'],0)  # 0.8*5 - 15 min at $60/h
        r=expected_value('fixed_task',{'cash_cost_usd':0,'human_minutes':5,'per_person_usd':50},s())
        self.assertAlmostEqual(r['ev_usd'],40-5)

    def test_raffle_uses_pool_over_expected_participants(self):
        r=expected_value('raffle',{'cash_cost_usd':0,'human_minutes':0,'pool_usd':1000,'participants':100},s())
        self.assertAlmostEqual(r['ev_usd'],5.0);self.assertEqual(r['basis'],'pool_divided_by_expected_participants')

    def test_unknown_time_value_or_cost_keeps_ev_unknown(self):
        self.assertIsNone(expected_value('bounty',{'cash_cost_usd':None,'human_minutes':10},s())['ev_usd'])
        self.assertIsNone(expected_value('bounty',{'cash_cost_usd':0,'human_minutes':10},s(human_hour_usd_micro=None))['ev_usd'])

    def test_history_pulls_raffle_rate_toward_reality(self):
        prior={'p':0.5,'payout_usd':100,'weight':1}
        p,pay,w=calibrated(prior,{'finished':30,'paid':0,'income_usd':0})
        self.assertLess(p,0.15);self.assertGreater(w,0.7)
        p,pay,w=calibrated(prior,{'finished':0})
        self.assertEqual((p,pay,w),(0.5,100,0.0))

    def test_weight_and_priors_validated(self):
        with self.assertRaises(Blocked): settings(SimpleNamespace(),{'category_priors':{'raffle':{'p':2}}})
        with self.assertRaises(Blocked): settings(SimpleNamespace(),{'max_loss_usd_micro':10**12})
        x=settings(SimpleNamespace(),{'category_priors':{'raffle':{'weight':0}},'participant_region':'Japan'})
        self.assertEqual(x['participant_region'],'Japan')


class Console(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db=D1();self.store=Store(self.db);self.app=worker.Default(SimpleNamespace(DB=self.db,ADMIN_TOKEN=TOKEN))
    async def asyncTearDown(self): self.db.conn.close()
    async def call(self,path,body=None):
        r=await self.app.fetch(Req(path,body));return r.status,json.loads(r.body)

    async def test_overrides_saved_and_applied(self):
        st,b=await self.call('/api/settings',{'overrides':{'participant_region':'Japan','human_hour_usd_micro':60_000_000,
                              'receiver_address':'0xb985fA629111d3652316d265313F6BA97bf67514','receiver_chain_id':1}})
        self.assertEqual(st,200,b)
        eff=await load_settings(SimpleNamespace(),self.store)
        self.assertEqual(eff['participant_region'],'Japan');self.assertEqual(eff['receiver_address'],'0xb985fa629111d3652316d265313f6ba97bf67514')
        st,b=await self.call('/api/settings',{'overrides':{'max_principal_usd_micro':1}})
        self.assertEqual(st,409)

    async def test_priority_skip_outcome_and_strategy_report(self):
        await self.store.run("INSERT INTO opportunities(id,source,title,url,fingerprint,data,observed_at,status) VALUES('galxe:x','task','T','https://x','f','{\"reward_kind\":\"raffle\"}',1,'discovered')")
        st,b=await self.call('/api/activities/galxe:x',{'priority':5,'skip':False,'outcome':'not_paid'})
        self.assertEqual(st,200,b)
        st,d=await self.call('/api/strategy')
        raffle=[c for c in d['categories'] if c['category']=='raffle'][0]
        self.assertEqual(raffle['finished'],1);self.assertEqual(raffle['win_rate'],0)
        self.assertEqual(d['ranking'][0]['priority'],5)
