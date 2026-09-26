"""Translate recorded Paper Trading read calls without changing their raw evidence."""
from copy import deepcopy
import hashlib
import json
from . import DataGateError

CONNECTOR = 'asdk_app_6a3cdf9e34b881918505f1cd5e06dbd8'

def adapt_paper_envelope(source):
    def fail(message):
        raise DataGateError('alpaca_schema_error', message, {})
    calls = source.get('paper_calls')
    if not isinstance(calls, dict) or not source.get('connector_failure'):
        fail('Paper fallback requires recorded calls and original connector failure.')
    receipts = {}
    def read(key, tool):
        call = calls.get(key)
        if not isinstance(call, dict) or call.get('connector_id') != CONNECTOR or call.get('tool') != tool:
            fail('Paper call identity mismatch: ' + key)
        if not isinstance(call.get('arguments'), dict) or not call.get('retrieved_at'):
            fail('Paper call requires exact arguments and retrieval time.')
        raw = call.get('response')
        if not isinstance(raw, dict) or raw.get('isError'):
            fail('Paper response missing or failed.')
        payload = raw.get('structuredContent', raw)
        if not isinstance(payload, dict) or payload.get('_alpaca_mcp_security', {}).get('tool_name') != tool:
            fail('Paper response tool mismatch.')
        data = payload.get('data')
        if not isinstance(data, dict):
            fail('Paper response data must be structured.')
        receipts[key] = {k: deepcopy(call[k]) for k in ('connector_id','tool','arguments','retrieved_at')}
        receipts[key]['raw_response_sha256'] = hashlib.sha256(json.dumps(raw,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        return call['arguments'], data
    result = deepcopy(source)
    symbol = source.get('provider_symbol')
    stock = source.get('fallback_class') == 'us_equity'
    tool = 'get_stock_bars' if stock else 'get_crypto_bars'
    args, data = read('bars', tool)
    if args.get('symbols') != symbol or args.get('timeframe') != '1Day' or not args.get('start') or not args.get('end'):
        fail('Paper history requires one exact symbol, explicit range and daily bars.')
    if stock and (args.get('adjustment') != 'raw' or args.get('currency') != 'USD' or not args.get('feed')):
        fail('Paper stock history requires explicit raw USD prices and feed.')
    if data.get('next_page_token'):
        fail('Paper bars are paginated and incomplete.')
    groups = data.get('bars')
    if not isinstance(groups, dict) or set(groups) != {symbol} or not isinstance(groups[symbol], list):
        fail('Paper bars must match the single requested symbol.')
    bars = []
    for row in groups[symbol]:
        if not isinstance(row, dict) or 't' not in row or 'c' not in row:
            fail('Paper bar missing timestamp or close.')
        bars.append({'symbol': symbol, 'timestamp': row['t'], 'close': row['c']})
    result['bars_response'] = {'tool':tool,'request':{**args,'symbols':[symbol]},'bars':{symbol:bars}}
    if stock:
        asset_args, asset = read('asset','get_asset')
        if asset_args.get('symbol_or_asset_id') != symbol:
            fail('Paper asset request must match the exact symbol.')
        result['asset_response'] = {**asset,'asset_class':asset.get('class')}
        ca_args, ca = read('corporate_actions','get_corporate_actions')
        if ca_args.get('symbols') != symbol or any(ca_args.get(k) is not None for k in ('types','ids','cusips')):
            fail('Paper corporate actions must cover one symbol and all types.')
        if ca.get('next_page_token') or not isinstance(ca.get('corporate_actions'),dict):
            fail('Paper corporate actions missing or incomplete.')
        # Nonempty process-date API actions need a separately verified mapping.
        if any(v not in (None,[]) for v in ca['corporate_actions'].values()):
            raise DataGateError('corporate_action_adjustment_failed','Nonempty Paper corporate actions are not yet supported; use the next evidence source.',{})
        result['corporate_actions_response'] = {'request':{**ca_args,'symbols':[symbol],'ca_types':None},'announcements':{},'next_page_token':None}
    return result, receipts
