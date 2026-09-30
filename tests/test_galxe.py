"""Official-schema fixtures, not claims of a live account/API-token integration test."""
import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from test_core import D1
from storage import Store
from common import Blocked, now
from collector import save_candidate, discover
from config import settings
from engine import evaluate
from galxe import candidate, query, LIST, CHECK, discover as galxe_discover, qualification, check_eligibility, capabilities
from policy import prescreen


def row(**overrides):
    return dict(id='GCtest123',name='Fixture',type='Airdrop',status='Active',description='Unknown reward terms',
                startTime=now()-60,endTime=now()+86400,cap=100,participantsCount=10,loyaltyPoints=0,gasType='Gasless',**overrides)


class GalxeRules(unittest.TestCase):
    def test_unknown_reward_and_costs_never_become_cash(self):
        c=candidate(row(),'40'); c['observed_at']=now()
        r=prescreen(c)
        self.assertTrue(r['eligible_for_analysis'])
        self.assertFalse(r['execution_supported'])
        self.assertIn('automation_not_verified',r['execution_blockers'])
        self.assertIsNone(r['conditional_net_usd_micro'])
        self.assertIsNone(c['data']['costs_usd_micro']['gas'])

    def test_full_ended_and_points_do_not_buy_analysis(self):
        for delta in ({'participantsCount':100},{'endTime':now()-1},{'status':'Deleted'},{'type':'Points'}):
            c=candidate({**row(),**delta},'40');c['observed_at']=now()
            self.assertFalse(prescreen(c)['eligible_for_analysis'])

    def test_rule_changes_invalidate_but_count_changes_do_not(self):
        c=candidate(row(),'40')
        self.assertEqual(c['fingerprint'],candidate({**row(),'participantsCount':11},'40')['fingerprint'])
        self.assertNotEqual(c['fingerprint'],candidate({**row(),'description':'new terms'},'40')['fingerprint'])

    def test_qualification_handles_all_any_and_unknown_without_truthiness(self):
        def q(relation,values,reward=True):
            return qualification({'credentialGroups':[{'conditionRelation':relation,'conditions':[{'eligible':v} for v in values],'rewards':[{'eligible':reward}]}]})
        self.assertEqual(q('ALL',[True,False]),'conditions_not_met')
        self.assertEqual(q('ANY',[True,False]),'conditions_met')
        self.assertEqual(q('ALL',[]),'unknown')
        self.assertEqual(q('ANY',['true']),'unknown')
        self.assertEqual(q('NEW',[True]),'unknown')
        self.assertEqual(q('ALL',[True],False),'conditions_not_met')


class GalxeFlow(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db=D1();self.store=Store(self.db)
        self.env=SimpleNamespace(GALXE_ACCESS_TOKEN='unit-test-only',GALXE_SPACE_IDS_JSON='["40"]',RECEIVER_ADDRESS='0x'+'1'*40)
    async def asyncTearDown(self): self.db.conn.close()

    async def test_missing_config_does_not_call_network(self):
        with patch('galxe.get_json',new=AsyncMock()) as net:
            self.assertEqual((await galxe_discover(SimpleNamespace(),self.store))['state'],'not_configured')
            self.assertFalse(capabilities(SimpleNamespace())['can_read']);net.assert_not_called()

    async def test_cursor_and_upsert_resume_without_duplicates(self):
        payload={'data':{'quests':{'list':[row()], 'pageInfo':{'hasNextPage':True,'endCursor':'next'}}}}
        with patch('galxe.get_json',new=AsyncMock(return_value=payload)) as net:
            await galxe_discover(self.env,self.store)
            payload['data']['quests']['pageInfo']={'hasNextPage':False,'endCursor':None}
            await galxe_discover(self.env,self.store)
            self.assertEqual(net.await_args.kwargs['body']['variables']['input']['after'],'next')
        self.assertEqual((await self.store.one('SELECT COUNT(*) AS n FROM opportunities'))['n'],1)
        self.assertIsNone((await self.store.one('SELECT cursor FROM adapter_cursors'))['cursor'])

    async def test_partial_graphql_error_is_not_a_successful_empty_page(self):
        payload={'errors':[{'message':'secret attacker text'}],'data':{'quests':{'list':[]}}}
        with patch('galxe.get_json',new=AsyncMock(return_value=payload)):
            with self.assertRaisesRegex(Blocked,'galxe_api_error'): await galxe_discover(self.env,self.store)
        self.assertIsNone(await self.store.one('SELECT * FROM adapter_cursors'))

    async def test_concurrent_qualification_calls_only_read_once(self):
        await save_candidate(self.store,candidate(row(),'40'))
        payload={'data':{'quest':{**row(),'credentialGroups':[{'conditionRelation':'ALL','conditions':[{'eligible':True}],'rewards':[{'eligible':True}]}]}}}
        with patch('galxe.get_json',new=AsyncMock(return_value=payload)) as net:
            results=await asyncio.gather(*[check_eligibility(self.env,self.store,'galxe:GCtest123') for _ in range(4)],return_exceptions=True)
            self.assertEqual(net.await_count,1)
            self.assertEqual(net.await_args.kwargs['body']['query'],CHECK)
        good=[r for r in results if isinstance(r,dict)][0]
        self.assertEqual(good['qualification'],'conditions_met')
        self.assertFalse(good['claimed']);self.assertFalse(good['participation_approved'])
        self.assertIsNone(good['income_usd_micro'])
        self.assertEqual((await self.store.one('SELECT COUNT(*) AS n FROM proposals'))['n'],0)

    async def test_mutations_and_unregistered_tasks_block_before_network(self):
        with patch('galxe.get_json',new=AsyncMock()) as net:
            with self.assertRaises(Blocked): await query(self.env,'mutation Claim {}',{})
            with self.assertRaises(Blocked): await check_eligibility(self.env,self.store,'galxe:arbitrary')
            net.assert_not_called()

    async def test_enthusiastic_model_cannot_promote_read_adapter_to_execution(self):
        c=candidate(row(),'40');await save_candidate(self.store,c)
        c=await self.store.one('SELECT * FROM opportunities')
        result=await evaluate(self.env,self.store,settings(self.env),c,{'recommendation':'review','eligibility':'confirmed','automation':'allowed','borrowing_required':False})
        self.assertEqual(result['state'],'task_review_needed')
        self.assertIsNone(await self.store.one('SELECT * FROM task_handoffs'))
        self.assertIsNone(await self.store.one('SELECT * FROM proposals'))
