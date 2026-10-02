"""Gap fixes: human time, accounts, free batch screening, handoffs, realized ledger, email, loss cap."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from test_core import D1
from storage import Store
from common import Blocked, now, canonical
from config import settings
from collector import merkl_candidate, save_candidate, binance_articles
from engine import tick, evaluate
from finance import income_entry, cost_entry, realized, metrics
from galxe import candidate as galxe_candidate
from notifier import compose
from tasks import assess_task


def task(**over):
    d=dict(ends_at=now()+86400,automation='unknown',eligibility='unknown',requires_trading=False,requires_deposit=False,
           requires_public_post=False,reward_kind='fixed',reward_per_person_usd_micro=10_000_000,
           costs_usd_micro={k:0 for k in ('gas','trading','claim','ai','hosting','other')},human_minutes=30)
    d.update(over);return d


def analysis(**over):
    a=dict(recommendation='review',eligibility='unknown',automation='unknown',borrowing_required=False,reason='r',risks=[],
           missing_evidence=[],exit_conditions=[],citations=[],manual_participation='allowed',required_accounts=['x'],
           requires_public_post=False,requires_funds=False,estimated_human_minutes=10,manual_steps=['打开页面','完成任务'],
           analysis_cost_usd_micro=2000)
    a.update(over);return a


class HumanTime(unittest.TestCase):
    def test_time_is_a_cost_and_unknown_rate_keeps_net_unknown(self):
        s=settings(SimpleNamespace())
        r=assess_task(task(),s=s)
        self.assertEqual(r['conditional_net_usd_micro'],10_000_000)
        self.assertIsNone(r['net_after_time_usd_micro'])
        self.assertIn('net_after_time_unknown',r['handoff_blockers'])
        s['human_hour_usd_micro']=10_000_000
        r=assess_task(task(),s=s)
        self.assertEqual(r['net_after_time_usd_micro'],5_000_000)
        self.assertEqual(r['handoff_blockers'],[])

    def test_manual_handoff_does_not_need_machine_automation_permission(self):
        s=settings(SimpleNamespace(SETTINGS_JSON='{"human_hour_usd_micro":1000000}'))
        r=assess_task(task(),s=s)
        self.assertIn('automation_not_verified',r['reasons'])
        self.assertNotIn('automation_not_verified',r['handoff_blockers'])

    def test_missing_real_account_blocks(self):
        s=settings(SimpleNamespace(SETTINGS_JSON='{"accounts":{"x":true},"human_hour_usd_micro":1}'))
        self.assertIn('account_not_available',assess_task(task(requires_accounts=['discord']),s=s)['handoff_blockers'])
        self.assertNotIn('account_not_available',assess_task(task(requires_accounts=['x']),s=s)['reasons'])

    def test_raffle_needs_explicit_small_experiment_budget(self):
        s=settings(SimpleNamespace())
        self.assertIn('reward_value_unknown_research_only',assess_task(task(reward_kind='raffle'),s=s)['handoff_blockers'])
        s['speculative_task_max_minutes']=30
        self.assertEqual(assess_task(task(reward_kind='raffle'),s=s)['handoff_blockers'],[])
        self.assertIsNone(assess_task(task(reward_kind='raffle'),s=s)['net_after_time_usd_micro'])

    def test_settings_reject_unknown_account(self):
        with self.assertRaises(Blocked):
            settings(SimpleNamespace(SETTINGS_JSON='{"accounts":{"second_x":true}}'))


class Sources(unittest.TestCase):
    def test_binance_cms_shape(self):
        v={'success':True,'data':{'catalogs':[{'articles':[{'code':'a'*32,'title':'Binance Launchpool X','releaseDate':1},
                                                           {'code':'../evil','title':'Launchpool'}]}]}}
        self.assertEqual(binance_articles(v),[('https://www.binance.com/en/support/announcement/detail/'+'a'*32,'Binance Launchpool X',1)])
        with self.assertRaises(Blocked): binance_articles({'success':True,'data':{}})


class Ledger(unittest.TestCase):
    def test_income_requires_evidence_and_real_basis(self):
        base=dict(source_ref='h1',asset='USDC',amount_raw='5000000',decimals=6,usd_micro=5_000_000,price_basis='stablecoin_1usd')
        with self.assertRaisesRegex(Blocked,'income_evidence_required'): income_entry(base,now())
        with self.assertRaisesRegex(Blocked,'income_price_basis_invalid'): income_entry({**base,'price_basis':'apr','evidence':'x'},now())
        with self.assertRaises(Blocked): income_entry({**base,'amount_raw':'0','evidence':'x'},now())
        self.assertEqual(income_entry({**base,'tx_hash':'0x'+'A'*64},now())['tx_hash'],'0x'+'a'*64)
        with self.assertRaises(Blocked): cost_entry({'category':'gas','usd_micro':5},now())


class Flow(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db=D1();self.store=Store(self.db)
        await self.store.run('UPDATE control SET paused=0,next_discovery=? WHERE id=1',now()+86400)
    async def asyncTearDown(self): self.db.conn.close()

    async def test_no_model_still_screens_whole_batch_without_blocking(self):
        for i in range(30):
            row={'id':str(i),'name':'S','chainId':1,'status':'LIVE','action':'deposit','earliestCampaignEnd':now()+9*86400,'apr':10,
                 'tokens':[{'symbol':'USDC','address':'0x'+'1'*40}],
                 'rewardsRecord':{'breakdowns':[{'token':{'symbol':'USDC','address':'0x'+'1'*40}}]}}
            await save_candidate(self.store,merkl_candidate(row))
        with patch('engine.analyze',new=AsyncMock()) as model:
            out=await tick(SimpleNamespace(),self.store)
        model.assert_not_called()
        self.assertEqual(out['state'],'screened');self.assertEqual(out['screened'],25)
        n=(await self.store.one("SELECT COUNT(*) AS n FROM opportunities WHERE status='awaiting_ai'"))['n']
        self.assertEqual(n,25)
        self.assertIsNone((await self.store.one('SELECT error_code FROM control'))['error_code'])

    async def test_task_becomes_single_handoff_with_steps_and_email(self):
        env=SimpleNamespace(SETTINGS_JSON='{"human_hour_usd_micro":1000000,"accounts":{"x":true}}')
        s=settings(env)
        c=galxe_candidate({'id':'GC1','name':'Task','type':'Drop','status':'Active','description':'d','startTime':now()-60,
                           'endTime':now()+86400,'cap':0,'participantsCount':1,'loyaltyPoints':0,'gasType':'Gasless'},'40')
        c['data']['reward_kind']='fixed';c['data']['reward_per_person_usd_micro']=5_000_000
        c['data']['costs_usd_micro']['other']=0
        await save_candidate(self.store,c);row=await self.store.one('SELECT * FROM opportunities')
        r=await evaluate(env,self.store,s,row,analysis())
        self.assertEqual(r['state'],'task_handoff_approval',r)
        again=await evaluate(env,self.store,s,row,analysis())
        self.assertEqual(again['state'],'task_handoff_exists')
        self.assertEqual((await self.store.one('SELECT COUNT(*) AS n FROM task_handoffs'))['n'],1)
        self.assertIsNone(await self.store.one('SELECT * FROM proposals'))
        ev=await self.store.one("SELECT * FROM events WHERE kind='task_handoff_approval_required'")
        subject,text=compose(ev,'https://dash.example')
        self.assertIn('https://app.galxe.com/quest/40/GC1',text);self.assertIn('1. 打开页面',text)
        self.assertNotIn('ADMIN_TOKEN',text);self.assertIn('不会要求你提供私钥',text)

    async def test_ai_saying_funds_needed_or_prohibited_blocks_handoff(self):
        env=SimpleNamespace(SETTINGS_JSON='{"human_hour_usd_micro":1000000}');s=settings(env)
        c=galxe_candidate({'id':'GC2','name':'T','type':'Drop','status':'Active','description':'d','startTime':now()-60,
                           'endTime':now()+86400,'cap':0,'participantsCount':1,'loyaltyPoints':0,'gasType':'Gasless'},'40')
        await save_candidate(self.store,c);row=await self.store.one('SELECT * FROM opportunities')
        for bad in ({'requires_funds':True},{'manual_participation':'prohibited'},{'eligibility':'not_eligible'}):
            r=await evaluate(env,self.store,s,row,analysis(**bad))
            self.assertEqual(r['state'],'task_review_needed')
        self.assertIsNone(await self.store.one('SELECT * FROM task_handoffs'))

    async def test_realized_net_counts_only_receipts_and_all_costs(self):
        await self.store.run("INSERT INTO income(id,source_ref,asset,amount_raw,decimals,usd_micro,price_basis,tx_hash,received_at,recorded_at) VALUES('i','h','USDC','5000000',6,5000000,'stablecoin_1usd','0x1',1,1)")
        await self.store.run("INSERT INTO costs(id,category,reserved_micro,actual_micro,state,created_at) VALUES('ai:1','ai',100000,80000,'confirmed',1)")
        await self.store.run("INSERT INTO costs(id,category,reserved_micro,state,created_at) VALUES('hosting:x','hosting',500000,'reserved',1)")
        await self.store.run("INSERT INTO interventions(at,kind,minutes) VALUES(1,'task_complete',30)")
        r=await realized(self.store)
        self.assertEqual(r['realized_net_usd_micro'],5_000_000-80_000-500_000)
        m=await metrics(self.store)
        self.assertEqual(m['human_interventions'],1);self.assertEqual(m['net_per_human_hour_usd_micro'],(5_000_000-580_000)*2)

    async def test_loss_cap_pauses(self):
        await self.store.run("INSERT INTO costs(id,category,reserved_micro,actual_micro,state,created_at) VALUES('m','gas',600,600,'confirmed',1)")
        out=await tick(SimpleNamespace(SETTINGS_JSON='{"max_loss_usd_micro":500}'),self.store)
        self.assertEqual(out['state'],'paused')
        self.assertEqual((await self.store.one('SELECT paused FROM control'))['paused'],1)
        self.assertIsNotNone(await self.store.one("SELECT * FROM events WHERE kind='loss_cap_reached'"))

    async def test_periodic_report_is_free_and_scheduled(self):
        await self.store.run('UPDATE control SET next_report=1')
        with patch('engine.review',new=AsyncMock()) as model:
            await tick(SimpleNamespace(),self.store)
        model.assert_not_called()
        self.assertIsNotNone(await self.store.one("SELECT * FROM events WHERE kind='periodic_report'"))
        self.assertGreater((await self.store.one('SELECT next_report FROM control'))['next_report'],now())


class WorkersAI(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self): self.db=D1();self.store=Store(self.db)
    async def asyncTearDown(self): self.db.conn.close()

    async def test_binding_call_is_budgeted_and_schema_checked(self):
        from ai import call_model, REVIEW_SCHEMA
        answer={'conclusion':'ok','continue_research':True,'proposed_changes':[],'missing_evidence':[]}
        ai=SimpleNamespace(run=AsyncMock(return_value={'response':answer,'usage':{'prompt_tokens':1000,'completion_tokens':100}}))
        env=SimpleNamespace(AI=ai)
        s=settings(SimpleNamespace(SETTINGS_JSON=json.dumps({'provider':'workers_ai','provider_eligible':True,
            'monthly_ai_usd_micro':1_000_000,'lifetime_cost_usd_micro':1_000_000,'max_loss_usd_micro':1_000_000,
            'review_model':'@cf/meta/llama-3.3-70b-instruct-fp8-fast'})))
        value,cost=await call_model(env,self.store,s,'x',{'a':1},REVIEW_SCHEMA,role='review')
        self.assertEqual(value,answer);self.assertGreater(cost,0)
        self.assertEqual(ai.run.await_args.args[0],'@cf/meta/llama-3.3-70b-instruct-fp8-fast')
        self.assertEqual((await self.store.one("SELECT state FROM costs"))['state'],'confirmed')
        ai.run=AsyncMock(return_value={'response':{'conclusion':1},'usage':{}})
        with self.assertRaises(Exception): await call_model(env,self.store,s,'x',{},REVIEW_SCHEMA,role='review')

    async def test_binance_digest_once(self):
        from collector import discover
        listing={'success':True,'data':{'catalogs':[{'articles':[{'code':'c'*32,'title':'Binance HODLer Airdrops: X','releaseDate':now()*1000},
                                                                {'code':'d'*32,'title':'Futures listing','releaseDate':now()*1000}]}]}}
        async def fake(url,**k):
            return listing if 'binance' in url else []
        with patch('collector.get_json',new=fake):
            await discover(self.store,0,SimpleNamespace());await discover(self.store,0,SimpleNamespace())
        rows=await self.store.all("SELECT payload FROM events WHERE kind='binance_announcements'")
        self.assertEqual(len(rows),1)
        self.assertEqual(len(json.loads(rows[0]['payload'])['items']),1)
