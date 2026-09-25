"""CPython tests exercise business rules/SQL; Worker runtime smoke is separate."""
import asyncio
import json
from pathlib import Path
import sqlite3
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from common import Blocked,canonical,digest,json_object
from finance import estimate,worth_review,COST_FIELDS
from config import settings
from storage import Store
from collector import merkl_candidate,save_candidate,Announcements
from ai import call_model
from finance import usage_cost
from finance import position_result
from engine import tick
from finance import value_receipts


class Statement:
    def __init__(self,db,sql,args=()): self.db,self.sql,self.args=db,sql,args
    def bind(self,*args): return Statement(self.db,self.sql,args)
    def execute(self):
        c=self.db.conn.execute(self.sql,self.args)
        results=[dict(r) for r in c.fetchall()] if c.description else []
        return {'results':results,'success':True,'meta':{'changes':max(c.rowcount,0)}}
    async def all(self): return self.execute()
    async def run(self): return self.execute()


class D1:
    def __init__(self):
        self.conn=sqlite3.connect(':memory:',isolation_level=None)
        self.conn.row_factory=sqlite3.Row
        for path in sorted((ROOT/'migrations').glob('*.sql')): self.conn.executescript(path.read_text())
    def prepare(self,sql): return Statement(self,sql)
    async def batch(self,statements):
        self.conn.execute('BEGIN IMMEDIATE')
        try:
            result=[s.execute() for s in statements];self.conn.execute('COMMIT');return result
        except Exception:
            self.conn.execute('ROLLBACK');raise


class Rules(unittest.TestCase):
    def test_market_valuation_subtracts_native_gas_once(self):
        state={'stage':'closed','deposited_raw':'100000000','redeemed_raw':'100000000','claimed_raw':'2000000','fee_wei':'1000000000000000'}
        r=value_receipts(state,6,'1','1000',100)
        self.assertEqual(r['realized_asset_pnl_valued_usdt_micro'],2000000)
        self.assertEqual(r['gas_valued_usdt_micro'],1000000)
        self.assertEqual(r['net_before_shared_operating_costs_usdt_micro'],1000000)
        self.assertEqual(r['status'],'market_estimate')
    def test_unknown_cost_is_not_zero(self):
        costs={x:0 for x in COST_FIELDS};costs['exit']=None
        e=estimate(100_000_000,20,7,costs)
        self.assertIsNone(e['net_scenarios_usd_micro']);self.assertFalse(worth_review(e,0))

    def test_principal_not_expense(self):
        costs={x:0 for x in COST_FIELDS};costs['gas']=10_000
        e=estimate(100_000_000,36.5,10,costs)
        self.assertEqual(e['net_scenarios_usd_micro']['snapshot'],990000)
        self.assertEqual(e['net_scenarios_usd_micro']['zero'],-10000)
        self.assertEqual(e['worst_loss_usd_micro'],100010000)

    def test_invalid_numbers(self):
        for v in (True,-1,1.1,'1'):
            with self.assertRaises(Blocked): estimate(v,10,7,{x:0 for x in COST_FIELDS})
        for rate in ('NaN','Infinity',-1):
            with self.assertRaises(Blocked): estimate(100,rate,7,{x:0 for x in COST_FIELDS})

    def test_duplicate_json_rejected(self):
        with self.assertRaises(Blocked):json_object('{"approve":false,"approve":true}')

    def test_default_budget_off(self):
        s=settings(SimpleNamespace());self.assertEqual(s['monthly_ai_usd_micro'],0)
        self.assertFalse(s['provider_eligible'])

    def test_hash_changes_with_authority(self):
        p={'amount':10,'contract':'a'}
        self.assertNotEqual(digest(p),digest({**p,'amount':11}))
        self.assertEqual(digest(p),digest({'contract':'a','amount':10}))

    def test_source_fingerprint_tracks_rules_not_apr(self):
        r={'id':'1','name':'Test','chainId':1,'status':'LIVE','apr':10,'description':'supply'}
        self.assertEqual(merkl_candidate(r)['fingerprint'],merkl_candidate({**r,'apr':11})['fingerprint'])
        self.assertNotEqual(merkl_candidate(r)['fingerprint'],merkl_candidate({**r,'description':'borrow required'})['fingerprint'])

    def test_official_links_only(self):
        p=Announcements();p.feed('<a href="https://evil.test/en/support/announcement/detail/'+'a'*32+'">Launchpool</a><a href="/en/support/announcement/detail/'+'b'*32+'">Launchpool USDC</a>')
        self.assertEqual(len(p.links),1);self.assertIn('www.binance.com',p.links[0][0])

    def test_returned_capital_not_profit(self):
        state={'plan':{'asset':'USDC','chain_id':1},'stage':'closed','deposited_raw':'100','redeemed_raw':'99','claimed_raw':'2','fee_wei':'7'}
        r=position_result(state);self.assertEqual(r['realized_asset_pnl_before_costs_raw'],'1')
        self.assertIsNone(r['net_usd_micro'])

    def test_usage_includes_reasoning_output(self):
        s=settings(SimpleNamespace());self.assertEqual(usage_cost({'input_tokens':1000,'output_tokens':2000},s),110000)


class Persistence(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self): self.db=D1();self.store=Store(self.db)
    async def asyncTearDown(self): self.db.conn.close()

    async def test_valuation_uses_supplied_quotes_and_keeps_actual_amounts(self):
        from finance import value_position
        state={'plan':{'vault_id':'v','chain_id':1},'stage':'closed','deposited_raw':'100000000',
               'redeemed_raw':'100000000','claimed_raw':'2000000','fee_wei':'1000000000000000'}
        before=canonical(state)
        quotes=AsyncMock(side_effect=[{'symbol':'ETHUSDT','price':'1000'},{'symbol':'USDCUSDT','price':'1'}])
        result=await value_position(state,{'vaults':[{'id':'v','asset_symbol':'USDC','asset_decimals':6}]},quotes)
        self.assertEqual(result['net_before_shared_operating_costs_usdt_micro'],1_000_000)
        self.assertEqual(canonical(state),before)
        self.assertEqual(quotes.await_count,2)

    async def test_scheduler_prepares_and_saves_read_only_review(self):
        from common import now
        await self.store.run('UPDATE control SET paused=0,next_discovery=? WHERE id=1',now()+86400)
        advice={'conclusion':'No completed positions','continue_research':True,'proposed_changes':[], 'missing_evidence':['receipts']}
        with patch('engine.review',new=AsyncMock(return_value=advice)) as model:
            result=await tick(SimpleNamespace(),self.store)
        self.assertEqual(result['state'],'reviewed')
        report=model.await_args.args[3]
        self.assertEqual(report['ledger']['positions'],[])
        self.assertEqual(report['screening'],[])
        saved=await self.store.one('SELECT data FROM reviews')
        self.assertEqual(json.loads(saved['data']),advice)

    async def test_single_lease(self):
        got=await asyncio.gather(*[self.store.acquire(100) for _ in range(20)])
        self.assertEqual(sum(x is not None for x in got),1)
        self.assertIsNone(await self.store.acquire(200));self.assertIsNotNone(await self.store.acquire(341))

    async def test_atomic_budget_under_concurrency(self):
        s=settings(SimpleNamespace());s.update(monthly_ai_usd_micro=100,lifetime_cost_usd_micro=100,max_loss_usd_micro=100,ai_calls_per_day=20)
        result=await asyncio.gather(*[self.store.reserve_ai(str(i),30,s,1000) for i in range(20)],return_exceptions=True)
        self.assertEqual(sum(x is None for x in result),3)
        self.assertEqual((await self.store.one('SELECT SUM(reserved_micro) AS n FROM costs'))['n'],90)

    async def test_uncertain_keeps_reservation(self):
        s=settings(SimpleNamespace());s.update(monthly_ai_usd_micro=100,lifetime_cost_usd_micro=100,max_loss_usd_micro=100)
        await self.store.reserve_ai('x',100,s,1000);await self.store.uncertain_cost('x')
        with self.assertRaises(Blocked): await self.store.reserve_ai('y',1,s,1000)

    async def test_actual_usage_releases_unused_reservation(self):
        s=settings(SimpleNamespace());s.update(monthly_ai_usd_micro=100,lifetime_cost_usd_micro=100,max_loss_usd_micro=100)
        await self.store.reserve_ai('x',100,s,1000);await self.store.settle_cost('x',40,{'id':'r'})
        await self.store.reserve_ai('y',60,s,1000)

    async def test_batch_rolls_back(self):
        with self.assertRaises(sqlite3.IntegrityError):
            await self.store.batch([('INSERT INTO sources(id) VALUES(?)',('x',)),('INSERT INTO sources(id) VALUES(?)',('x',))])
        self.assertIsNone(await self.store.one('SELECT * FROM sources WHERE id=?','x'))

    async def test_candidate_upsert_deduplicates(self):
        c=merkl_candidate({'id':'1','name':'T','chainId':1,'status':'LIVE'})
        await save_candidate(self.store,c);await save_candidate(self.store,c)
        self.assertEqual((await self.store.one('SELECT COUNT(*) AS n FROM opportunities'))['n'],1)

    async def test_event_deduplication(self):
        await self.store.event('same','approval',{});await self.store.event('same','approval',{})
        self.assertEqual((await self.store.one('SELECT COUNT(*) AS n FROM events'))['n'],1)

    async def test_paused_never_calls_paid_or_execution(self):
        with patch('engine.process_execution',new=AsyncMock()) as execute,patch('engine.discover',new=AsyncMock()) as discover:
            r=await tick(SimpleNamespace(),self.store)
            self.assertEqual(r['state'],'paused');execute.assert_not_called();discover.assert_not_called()

    async def test_model_missing_account_never_reserves(self):
        with self.assertRaises(Blocked):await call_model(SimpleNamespace(),self.store,settings(SimpleNamespace()),'x',{}, {})
        self.assertEqual((await self.store.one('SELECT COUNT(*) AS n FROM costs'))['n'],0)

    async def test_no_approved_plan_never_calls_executor(self):
        from engine import process_execution
        with patch('engine.advance',new=AsyncMock()) as advance:
            self.assertFalse(await process_execution(SimpleNamespace(),self.store));advance.assert_not_called()

    async def test_receipts_revocation_and_exit_do_not_depend_on_research_source(self):
        from engine import process_execution
        await self.store.run("INSERT INTO proposals(id,opportunity_id,fingerprint,plan,digest,state,created_at,expires_at) VALUES(?,?,?,?,?,?,?,?)",
                             'p','merkl:1','f','{}','d','executing',1,200)
        for stage,pending in [('approved',{'hash':'h'}),('allowance_set',{'hash':'h'}),('deposited',None),('holding',None)]:
            state={'id':'p','stage':stage,'pending':pending,'plan':{'vault_id':'v','expires_at':200},'receipts':[]}
            with patch('engine.executor',new=AsyncMock(return_value={'plan':state})), \
                 patch('engine.advance',new=AsyncMock(return_value=state)) as advance, \
                 patch('engine.refresh_merkl',new=AsyncMock(side_effect=Blocked('source_down'))) as source, \
                 patch('engine.now',return_value=100):
                self.assertTrue(await process_execution(SimpleNamespace(),self.store))
                advance.assert_awaited_once();source.assert_not_called()


if __name__=='__main__':unittest.main()
