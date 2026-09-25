"""Market valuation of verified receipts. This is not a swap fill or a fiat receipt."""
from decimal import Decimal,ROUND_CEILING
from common import Blocked,decimal,now
from network import get_json


def value_receipts(state,decimals,asset_price,native_price,timestamp):
    asset_price=decimal(asset_price);native_price=decimal(native_price)
    if asset_price<=0 or native_price<=0 or not 0<=decimals<=18:
        raise Blocked('invalid_market_quote')
    closed=state['stage'] in ('exited','closed')
    raw=int(state.get('claimed_raw','0'))
    if closed:
        raw+=int(state.get('redeemed_raw','0'))-int(state.get('deposited_raw','0'))
    gross=int(Decimal(raw)*asset_price*1000000/(10**decimals))
    gas=int((Decimal(state.get('fee_wei','0'))*native_price/Decimal(10**12)).to_integral_value(rounding=ROUND_CEILING))
    return {'status':'market_estimate','as_of':timestamp,'quote_currency':'USDT',
            'asset_price_usdt':str(asset_price),'native_price_usdt':str(native_price),
            'realized_asset_pnl_valued_usdt_micro':gross,'gas_valued_usdt_micro':gas,
            'net_before_shared_operating_costs_usdt_micro':gross-gas,
            'open_principal_excluded':not closed,
            'basis':'current_spot_mark_of_verified_receipts_not_actual_sale_proceeds'}


async def value_position(state,s):
    matches=[v for v in s['vaults'] if v['id']==state['plan']['vault_id']]
    if len(matches)!=1:
        return {'status':'adapter_not_configured'}
    v=matches[0];symbol=v.get('asset_symbol');decimals=v.get('asset_decimals')
    if symbol not in ('USDC','USDT') or type(decimals) is not int:
        return {'status':'asset_quote_not_configured'}
    native={1:'ETHUSDT',56:'BNBUSDT'}.get(state['plan']['chain_id'])
    if not native:
        return {'status':'native_quote_not_configured'}
    try:
        root='https://data-api.binance.vision/api/v3/ticker/price?symbol='
        native_data=await get_json(root+native,timeout=8,max_bytes=2048)
        if native_data.get('symbol')!=native:
            raise Blocked('market_symbol_mismatch')
        asset_price='1'
        if symbol!='USDT':
            asset_data=await get_json(root+symbol+'USDT',timeout=8,max_bytes=2048)
            if asset_data.get('symbol')!=symbol+'USDT':
                raise Blocked('market_symbol_mismatch')
            asset_price=asset_data['price']
        return value_receipts(state,decimals,asset_price,native_data['price'],now())
    except (Blocked,KeyError,ValueError):
        return {'status':'market_quote_unavailable','as_of':now()}
