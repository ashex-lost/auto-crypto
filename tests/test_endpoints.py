"""Worker routes with a stubbed `workers` module; the real runtime is covered by runtime_smoke.py."""
import json
import sys
import types
import unittest
from types import SimpleNamespace
from test_core import D1

if 'workers' not in sys.modules:
    stub=types.ModuleType('workers')
    class Response:
        def __init__(self,body='',status=200,headers=None): self.body,self.status=body,status
        @staticmethod
        def from_json(data,status=200,headers=None): return Response(json.dumps(data),status)
    class WorkerEntrypoint:
        def __init__(self,env): self.env=env
    stub.Response,stub.WorkerEntrypoint=Response,WorkerEntrypoint
    sys.modules['workers']=stub
import worker

TOKEN='t'*40


class Req:
    def __init__(self,path,body=None):
        self.url='https://x.test'+path;self.method='POST' if body is not None else 'GET'
        self._b=json.dumps(body) if body is not None else ''
        self.headers={'Authorization':'Bearer '+TOKEN,'Content-Type':'application/json'}
    async def text(self): return self._b


class Endpoints(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db=D1();self.app=worker.Default(SimpleNamespace(DB=self.db,ADMIN_TOKEN=TOKEN))
    async def asyncTearDown(self): self.db.conn.close()
    async def call(self,path,body=None):
        r=await self.app.fetch(Req(path,body));return r.status,json.loads(r.body)

    async def test_ledger_and_interventions(self):
        s,b=await self.call('/api/ledger/income',{'source_ref':'h','asset':'USDC','amount_raw':'1000000','decimals':6,
                            'usd_micro':1000000,'price_basis':'stablecoin_1usd','tx_hash':'0x'+'b'*64})
        self.assertEqual(s,200)
        s,b=await self.call('/api/ledger/cost',{'category':'gas','usd_micro':200000,'evidence':'bill'})
        self.assertEqual(b['realized']['realized_net_usd_micro'],800000)
        s,m=await self.call('/api/metrics')
        self.assertEqual(m['human_interventions'],2)
        s,b=await self.call('/api/ledger/income',{'source_ref':'h','asset':'PTS','amount_raw':'5','decimals':0,'usd_micro':5,'price_basis':'points'})
        self.assertEqual(s,409)
