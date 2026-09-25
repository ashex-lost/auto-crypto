// This module has no access to the wallet key or network; independently testable.
import { getAddress } from 'ethers';

export function requireThat(ok, code) { if (!ok) throw new Error(code); }
export function uint(value, max=(1n<<256n)-1n) {
  requireThat(typeof value==='string' && /^(0|[1-9][0-9]{0,77})$/.test(value),'invalid_uint');
  const n=BigInt(value); requireThat(n<=max,'uint_too_large'); return n;
}
export function address(value) { try { return getAddress(value).toLowerCase(); } catch { throw new Error('invalid_address'); } }
export function validatePlan(p, config, wallet, time) {
  const fields=['version','adapter','vault_id','opportunity_id','evidence_hash','chain_id','wallet','asset','vault','distributor','amount_raw','shares_raw','max_fee_wei','gas_limit','max_gas_price_wei','created_at','expires_at','exit_at','claim_until','max_claims','max_txs','min_claim_raw','stop_loss_bps'];
  requireThat(p && Object.keys(p).sort().join(',')===fields.sort().join(','),'plan_fields');
  requireThat(p.version===1 && p.adapter==='erc4626_merkl_v1','adapter_unsupported');
  requireThat([1,56].includes(config.chain_id) && p.chain_id===config.chain_id,'chain_unsupported');
  requireThat(address(p.wallet)===address(wallet),'wallet_mismatch');
  const v=config.vaults.find(v=>v.id===p.vault_id);
  requireThat(v && v.reviewed===true,'vault_not_reviewed');
  for (const key of ['asset','vault','distributor']) requireThat(address(p[key])===address(v[key]),key+'_mismatch');
  requireThat(p.opportunity_id==='merkl:'+v.opportunity_id,'campaign_mismatch');
  requireThat(/^[a-f0-9]{64}$/.test(p.evidence_hash),'invalid_evidence');
  requireThat(uint(p.amount_raw)>0n && uint(p.amount_raw)<=uint(v.max_amount_raw),'principal_limit');
  requireThat(uint(p.shares_raw)>0n,'zero_shares');
  requireThat(Number.isSafeInteger(p.gas_limit) && p.gas_limit>=21000 && p.gas_limit<=config.gas_limit,'gas_limit');
  requireThat(uint(p.max_gas_price_wei)>0n && uint(p.max_gas_price_wei)<=uint(config.max_gas_price_wei),'gas_price_limit');
  requireThat(uint(p.max_fee_wei)<=uint(config.lifetime_fee_cap_wei),'fee_limit');
  requireThat(p.max_txs===7 && p.max_claims===2,'transaction_count_limit');
  requireThat(uint(p.max_fee_wei)>=BigInt(p.max_txs*p.gas_limit)*uint(p.max_gas_price_wei),'exit_fee_not_reserved');
  requireThat(uint(p.min_claim_raw)>0n,'claim_threshold_missing');
  requireThat(Number.isSafeInteger(p.stop_loss_bps) && p.stop_loss_bps>=1 && p.stop_loss_bps<=5000,'stop_loss_invalid');
  for (const k of ['created_at','expires_at','exit_at','claim_until']) requireThat(Number.isSafeInteger(p[k]),'invalid_time');
  requireThat(p.created_at<=time && p.created_at>=time-3600 && p.expires_at>time && p.expires_at<=p.created_at+1800,'approval_expired');
  requireThat(p.exit_at>p.expires_at && p.exit_at<=time+30*86400 && p.claim_until>=p.exit_at && p.claim_until<=p.exit_at+7*86400,'invalid_exit');
  return v;
}

export function publicState(state) {
  if (!state) return null;
  const { raw, pending, ...rest }=state;
  return {...rest,pending:pending?{hash:pending.hash,kind:pending.kind,nonce:pending.nonce,created_at:pending.created_at}:null};
}
