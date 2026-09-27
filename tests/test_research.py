"""No external calls or funds: fixed-rule rejection and budgeted model role audit."""
import json
from pathlib import Path
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch
from test_core import D1
from storage import Store
from common import now,canonical,Blocked
from collector import merkl_candidate,save_candidate
from policy import prescreen
from config import settings
from engine import tick
from ai import call_model,REVIEW_SCHEMA
from finance import research_estimate


def candidate(**changes):
    # Synthetic passing fixture; not a real or reviewed investment opportunity.
    row={'id':'1','name':'Synthetic deposit','chainId':1,'status':'LIVE','action':'deposit',
         'earliestCampaignEnd':now()+10*86400,'apr':10,
         'tokens':[{'symbol':'USDC','address':'0x'+'1'*40}],
         'rewardsRecord':{'breakdowns':[{'token':{'symbol':'USDC','address':'0x'+'1'*40}}]}}
    row.update(changes)
    return {**merkl_candidate(row),'observed_at':now()}


class Screening(unittest.TestCase):
    def test_real_api_candidates_replay_at_observation_time(self):
        report=json.loads((Path(__file__).parent/'fixtures/merkl_normalized_2026-09-27.json').read_text())
        self.assertEqual(len(report['candidates']),10)
        for c in report['candidates']:
            out=prescreen(c,timestamp=report['observed_at'])
            self.assertFalse(out['eligible_for_analysis'],c['title'])
            self.assertNotIn('campaign_dates_unknown',out['reasons'])
            self.assertFalse(out['participation_approved'])

    def test_official_historical_cases_never_pass(self):
        cases=json.loads((Path(__file__).parent/"fixtures/official_research_cases.json").read_text())
        for c in cases:
            out=prescreen(c,timestamp=c["observed_at"])
            self.assertFalse(out["eligible_for_analysis"])
            self.assertIn(c["expected_reason"],out["reasons"])

    def test_api_string_timestamp_is_supported(self):
        self.assertTrue(prescreen(candidate(earliestCampaignEnd=str(now()+864000)))["eligible_for_analysis"])
        self.assertEqual(research_estimate(candidate(earliestCampaignEnd=str(now()+864000))["data"],settings(SimpleNamespace()))["state"],"research_only")

    def test_rejection_matrix(self):
        for change,reason in [({'earliestCampaignEnd':1},'campaign_not_live'),
                              ({'earliestCampaignEnd':None},'campaign_dates_unknown'),
                              ({'chainId':42161},'chain_unsupported'),
                              ({'description':'Borrow USDC'},'borrowing_or_leverage'),
                              ({'action':'swap'},'activity_type_unsupported'),
                              ({'rewardsRecord':{}},'reward_conversion_needed')]:
            with self.subTest(reason=reason):
                out=prescreen(candidate(**change))
                self.assertFalse(out['eligible_for_analysis']);self.assertIn(reason,out['reasons'])

    def test_pass_is_not_approval_and_stale_source_cannot_pass(self):
        c=candidate();out=prescreen(c)
        self.assertTrue(out['eligible_for_analysis']);self.assertFalse(out['participation_approved'])
        c['observed_at']=1
        self.assertIn('source_stale',prescreen(c)['reasons'])

    def test_unknown_friction_never_becomes_profitable(self):
        e=research_estimate(candidate()['data'],settings(SimpleNamespace()))
        self.assertIsNone(e['economics']['net_scenarios_usd_micro'])
        self.assertFalse(e['participation_approved'])

    def test_malformed_rewards_rejected(self):
        c=candidate();c['data']['rewards']=['USDC']
        self.assertFalse(prescreen(c)['eligible_for_analysis'])

    def test_binance_title_cannot_trigger_paid_analysis(self):
        c={'source':'binance','observed_at':now(),'data':{'title':'Launchpool'}}
        out=prescreen(c)
        self.assertIn('binance_execution_unverified',out['reasons'])
        self.assertFalse(out['eligible_for_analysis'])


class Pipeline(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db=D1();self.store=Store(self.db)
        await self.store.run('UPDATE control SET paused=0,next_discovery=? WHERE id=1',now()+86400)
    async def asyncTearDown(self):self.db.conn.close()

    async def test_expired_candidate_never_calls_model_and_refresh_rescreens(self):
        c=candidate(earliestCampaignEnd=1);await save_candidate(self.store,c)
        with patch('engine.analyze',new=AsyncMock()) as model:
            out=await tick(SimpleNamespace(),self.store)
        self.assertEqual(out['state'],'screened');model.assert_not_called()
        row=await self.store.one('SELECT * FROM opportunities')
        self.assertEqual(row['status'],'screened_out');self.assertIsNone(row['analysis'])
        self.assertIn('campaign_not_live',json.loads(row['screening'])['reasons'])
        await save_candidate(self.store,c)
        self.assertEqual((await self.store.one('SELECT status FROM opportunities'))['status'],'discovered')

    async def test_review_disabled_by_default(self):
        with patch('engine.review',new=AsyncMock()) as model:
            self.assertEqual((await tick(SimpleNamespace(),self.store))['state'],'idle')
        model.assert_not_called()

    def profile(self):
        s=settings(SimpleNamespace())
        s.update(provider_eligible=True,monthly_ai_usd_micro=1_000_000,
                 lifetime_cost_usd_micro=1_000_000,max_loss_usd_micro=1_000_000)
        return s

    async def test_role_rates_recorded_and_shared_budget_applies(self):
        s=self.profile();env=SimpleNamespace(MODEL_API_KEY='test-only')
        value={'conclusion':'test','continue_research':False,'proposed_changes':[],'missing_evidence':[]}
        response={'id':'mock','status':'completed','usage':{'input_tokens':100,'output_tokens':20},
                  'output':[{'type':'message','content':[{'type':'output_text','text':canonical(value)}]}]}
        with patch('ai.get_json',new=AsyncMock(return_value=response)) as net:
            _,cheap=await call_model(env,self.store,s,'test',{},REVIEW_SCHEMA)
            _,review=await call_model(env,self.store,s,'test',{},REVIEW_SCHEMA,role='review')
            self.assertEqual([c.kwargs['body']['model'] for c in net.await_args_list],[s['model'],s['review_model']])
        self.assertEqual((cheap,review),(20,400))
        rows=await self.store.all('SELECT * FROM model_runs ORDER BY actual_micro')
        self.assertEqual([r['state'] for r in rows],['completed','completed'])
        self.assertEqual([r['actual_micro'] for r in rows],[20,400])
        self.assertNotIn('test-only',canonical(rows))
        s['monthly_ai_usd_micro']=420
        with patch('ai.get_json',new=AsyncMock()) as net:
            with self.assertRaisesRegex(Blocked,'ai_budget_exhausted'):
                await call_model(env,self.store,s,'test',{},REVIEW_SCHEMA)
        net.assert_not_called()

    async def test_per_call_cap_prevents_network_and_cost_reservation(self):
        s=self.profile();s['analysis_max_call_usd_micro']=1
        with patch('ai.get_json',new=AsyncMock()) as net:
            with self.assertRaisesRegex(Blocked,'model_call_cap_exceeded'):
                await call_model(SimpleNamespace(MODEL_API_KEY='test-only'),self.store,s,'test',{},REVIEW_SCHEMA)
        net.assert_not_called()
        self.assertEqual((await self.store.one('SELECT COUNT(*) AS n FROM costs'))['n'],0)

    async def test_timeout_retains_budget_and_audit(self):
        with patch('ai.get_json',new=AsyncMock(side_effect=Blocked('timeout'))):
            with self.assertRaises(Blocked):
                await call_model(SimpleNamespace(MODEL_API_KEY='test-only'),self.store,self.profile(),'test',{},REVIEW_SCHEMA)
        self.assertEqual((await self.store.one('SELECT state FROM costs'))['state'],'uncertain')
        self.assertEqual((await self.store.one('SELECT state FROM model_runs'))['state'],'needs_attention')

    async def test_invalid_nested_output_is_paid_but_not_accepted(self):
        invalid={'conclusion':'test','continue_research':False,'proposed_changes':[{'bad':'object'}],'missing_evidence':[]}
        response={'status':'completed','usage':{'input_tokens':100,'output_tokens':20},
                  'output':[{'type':'message','content':[{'type':'output_text','text':canonical(invalid)}]}]}
        with patch('ai.get_json',new=AsyncMock(return_value=response)):
            with self.assertRaisesRegex(Blocked,'model_schema_invalid'):
                await call_model(SimpleNamespace(MODEL_API_KEY='test-only'),self.store,self.profile(),'test',{},REVIEW_SCHEMA)
        row=await self.store.one('SELECT * FROM model_runs')
        self.assertEqual(row['state'],'needs_attention');self.assertEqual(row['actual_micro'],20)
