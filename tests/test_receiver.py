import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from common import Blocked
from receiver import configuration, snapshot


class Receiver(unittest.IsolatedAsyncioTestCase):
    def test_missing_configuration_is_read_only_idle(self):
        self.assertEqual(configuration(SimpleNamespace()), {'configured':False,'address':None,'chain_id':None})

    def test_only_supported_chain_and_valid_addresses_are_accepted(self):
        env=SimpleNamespace(RECEIVER_ADDRESS='0x'+'1'*40,RECEIVER_RPC_URL='https://rpc.example',
                            RECEIVER_CHAIN_ID='1',RECEIVER_ASSETS_JSON='[]')
        self.assertTrue(configuration(env)['configured'])
        with self.assertRaises(Blocked):
            configuration(SimpleNamespace(RECEIVER_ADDRESS='0x'+'1'*40,RECEIVER_RPC_URL='http://rpc.example',RECEIVER_CHAIN_ID='1'))

    async def test_snapshot_uses_public_rpc_calls_without_a_signer(self):
        env=SimpleNamespace(RECEIVER_ADDRESS='0x'+'1'*40,RECEIVER_RPC_URL='https://rpc.example',
                            RECEIVER_CHAIN_ID='1',RECEIVER_ASSETS_JSON='[{"address":"0x'+'2'*40+'","symbol":"USDC","decimals":6}]')
        async def rpc(url,**kwargs):
            method=kwargs['body']['method']
            return {'result': {'eth_chainId':'0x1','eth_getBalance':'0x2','eth_call':'0x3'}[method]}
        with patch('receiver.get_json',new=AsyncMock(side_effect=rpc)) as call:
            result=await snapshot(env)
        self.assertEqual(result['native_raw'],'2');self.assertEqual(result['assets'][0]['raw'],'3')
        self.assertIn('70a08231',call.await_args_list[2].kwargs['body']['params'][0]['data'])

    async def test_chain_mismatch_blocks_snapshot(self):
        env=SimpleNamespace(RECEIVER_ADDRESS='0x'+'1'*40,RECEIVER_RPC_URL='https://rpc.example',
                            RECEIVER_CHAIN_ID='56',RECEIVER_ASSETS_JSON='[]')
        with patch('receiver.get_json',new=AsyncMock(return_value={'result':'0x1'})):
            with self.assertRaisesRegex(Blocked,'receiver_chain_mismatch'):
                await snapshot(env)
