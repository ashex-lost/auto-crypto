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
    def test_time_is_reported_not_charged(self):
        r=expected_value('fixed_task',{'cash_cost_usd':0,'human_minutes':15,'per_person_usd':5},s())
        self.assertAlmostEqual(r['ev_usd'],4.0);self.assertEqual(r['human_minutes'],15)
        self.assertAlmostEqual(r['ev_per_hour_usd'],16.0);self.assertEqual(r['certainty'],1.0)

    def test_raffle_with_known_participants_is_certain(self):
        r=expected_value('raffle',{'cash_cost_usd':0,'human_minutes':0,'pool_usd':1000,'participants':100},s())
        self.assertAlmostEqual(r['ev_usd'],5.0);self.assertEqual(r['basis'],'pool_with_known_participants');self.assertEqual(r['certainty'],1.0)

    def test_unknown_cost_keeps_ev_unknown(self):
        self.assertIsNone(expected_value('bounty',{'cash_cost_usd':None,'human_minutes':10},s())['ev_usd'])

    def test_yield_ev_and_roi(self):
        from strategy import yield_ev
        y=yield_ev({'apr':36.5,'chainId':8453,'tokens':[{'address':'0xa'}],'rewards':[{'address':'0xa'}]},{'default_principal_usd_micro':100_000_000},20)
        r=expected_value('points_deposit',{'yield':y},s())
        self.assertAlmostEqual(r['ev_usd'],100*0.365*20/365*0.5-0.12,places=6)
        self.assertAlmostEqual(r['roi'],r['ev_usd']/100);self.assertEqual(r['certainty'],0.8)
        y2=yield_ev({'apr':36.5,'chainId':1,'tokens':[{'address':'0xa'}],'rewards':[{'address':'0xb'}]},{},20)
        self.assertLess(expected_value('points_deposit',{'yield':y2},s())['ev_usd'],0)  # 50U on mainnet loses to gas

    def test_composite_rank_and_certainty_tiebreak(self):
        from strategy import rank
        rows=[{'id':'a','ev_usd':10,'ev_per_hour_usd':10,'roi':None,'certainty':0.6},
              {'id':'b','ev_usd':10,'ev_per_hour_usd':10,'roi':None,'certainty':1.0},
              {'id':'c','ev_usd':-1,'ev_per_hour_usd':None,'roi':None,'certainty':1.0},
              {'id':'d','ev_usd':50,'ev_per_hour_usd':None,'roi':0.5,'certainty':0.5}]
        out=[r['id'] for r in rank(rows)]
        self.assertEqual(out[0],'d');self.assertEqual(out[1:3],['b','a']);self.assertEqual(out[-1],'c')

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


class TryFirst(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db=D1();self.store=Store(self.db);self.app=worker.Default(SimpleNamespace(DB=self.db,ADMIN_TOKEN=TOKEN))
    async def asyncTearDown(self): self.db.conn.close()

    async def test_rejection_skips_same_project_only(self):
        from collector import save_candidate
        from galxe import candidate
        from engine import tick
        from common import now
        def row(i): return {'id':i,'name':'T','type':'Drop','status':'Active','description':'d','startTime':now()-60,
                            'endTime':now()+5*86400,'cap':0,'participantsCount':1,'loyaltyPoints':0,'gasType':'Gasless'}
        await save_candidate(self.store,candidate(row('A1'),'40'))
        r=await self.app.fetch(Req('/api/activities/galxe:A1',{'ineligible':True}));self.assertEqual(r.status,200)
        await save_candidate(self.store,candidate(row('A2'),'40'))   # same Galxe space
        await save_candidate(self.store,candidate(row('B1'),'77'))   # different project
        await self.store.run('UPDATE control SET paused=0,next_discovery=? WHERE id=1',now()+86400)
        await tick(SimpleNamespace(),self.store)
        a2=await self.store.one("SELECT status,screening FROM opportunities WHERE id='galxe:A2'")
        b1=await self.store.one("SELECT status FROM opportunities WHERE id='galxe:B1'")
        self.assertIn('previously_ineligible',json.loads(a2['screening'])['reasons'])
        self.assertEqual(b1['status'],'awaiting_ai')
