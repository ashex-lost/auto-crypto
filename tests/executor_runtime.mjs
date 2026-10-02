// Run after check:executor. Real local workerd/SQLite DO, no keys or network access.
import { Miniflare, convertV4MiniflareOptions } from 'miniflare';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';

const machine='local-machine-test-only-12345678901234567890';
const owner='local-owner-test-only-1234567890123456789012';
const mf=new Miniflare(convertV4MiniflareOptions({cf:false,workers:[{
  name:'executor-test',modules:true,
  scriptPath:fileURLToPath(new URL('../executor/dist-executor/worker.js',import.meta.url)),
  compatibilityDate:'2026-09-23',
  durableObjects:{WALLET:{className:'WalletExecutor',useSQLite:true}},
  bindings:{EXECUTION_TOKEN:machine,OWNER_TOKEN:owner,EXECUTOR_CONFIG_JSON:'{}'},
  outboundService(){throw Error('Network is prohibited in this test');},
}]}));
try {
  async function call(path,token,method='POST',body={}) {
    const r=await mf.dispatchFetch('https://test.internal'+path,{
      method,headers:{Authorization:'Bearer '+token,'Content-Type':'application/json'},
      body:method==='GET'?undefined:JSON.stringify(body),
    });
    return [r.status,await r.json()];
  }
  assert.equal((await call('/state','invalid','GET'))[0],401);
  assert.equal((await call('/owner/approve',machine))[0],401);
  assert.equal((await call('/owner/resume',machine))[0],401);
  assert.equal((await call('/owner/check',machine))[0],401);
  assert.deepEqual(await call('/owner/check',owner),[200,{authorized:true}]);
  assert.equal((await call('/state',owner,'GET'))[0],401);
  assert.deepEqual(await call('/state',machine,'GET'),[200,{paused:true,plan:null}]);
  assert.deepEqual(await call('/pause',machine),[200,{paused:true}]);
  assert.equal((await call('/owner/approve',owner))[1].error,'executor_config_missing');
  assert.equal((await call('/state',machine,'GET'))[1].plan,null);
  console.log('Signer runtime passed: owner/machine separation, real Durable Object, pause and missing-config rejection.');
} finally {
  await mf.dispose();
}
