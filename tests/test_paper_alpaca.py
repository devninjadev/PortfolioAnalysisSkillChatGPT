from copy import deepcopy
import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from advisor_data import DataGateError
from advisor_data.alpaca import normalize_alpaca_envelope
from advisor_data.paper_alpaca import CONNECTOR

def envelope():
    def call(tool,args,data):
        return {'connector_id':CONNECTOR,'tool':tool,'arguments':args,'retrieved_at':'2026-09-26T06:00:00Z','response':{'_alpaca_mcp_security':{'tool_name':tool},'data':data}}
    return {'schema_version':1,'symbol':'SPY','provider_symbol':'SPY','fallback_class':'us_equity','connector_id':CONNECTOR,'connector_failure':{'code':'tool_unavailable'},'primary_failure':{'code':'price_history_unavailable'},'paper_calls':{
      'bars':call('get_stock_bars',{'symbols':'SPY','timeframe':'1Day','start':'2026-09-21T00:00:00Z','end':'2026-09-23T00:00:00Z','feed':'iex','currency':'USD','adjustment':'raw'},{'bars':{'SPY':[{'t':'2026-09-21T04:00:00Z','c':100},{'t':'2026-09-22T04:00:00Z','c':101}]},'next_page_token':None}),
      'asset':call('get_asset',{'symbol_or_asset_id':'SPY'},{'symbol':'SPY','class':'us_equity','status':'active'}),
      'corporate_actions':call('get_corporate_actions',{'symbols':'SPY','start':'2026-09-21','end':'2026-09-23'},{'corporate_actions':{},'next_page_token':None})}}
class PaperTests(unittest.TestCase):
    def run_envelope(self,e):return normalize_alpaca_envelope(e,start='2026-09-21',end='2026-09-23')
    def test_preserves_raw_and_receipt(self):
        e=envelope();original=deepcopy(e);r=self.run_envelope(e)
        self.assertEqual(e,original);self.assertEqual(r.series.tolist(),[100,101]);self.assertEqual(r.receipt['connector_name'],'Alpaca Paper Trading');self.assertEqual(len(r.receipt['paper_calls']['bars']['raw_response_sha256']),64)
    def test_rejects_incomplete_wrong_identity_and_adjusted(self):
        for mutate in [lambda e:e['paper_calls']['bars']['response']['data'].update(next_page_token='more'),lambda e:e['paper_calls']['bars']['response']['_alpaca_mcp_security'].update(tool_name='get_orders'),lambda e:e['paper_calls']['bars']['arguments'].update(adjustment='all'),lambda e:e['paper_calls']['bars']['arguments'].update(currency='EUR'),lambda e:e['paper_calls']['asset']['response']['data'].update(symbol='QQQ'),lambda e:e['paper_calls']['corporate_actions']['arguments'].update(types='cash_dividend'),lambda e:e.update(connector_failure=None)]:
            with self.subTest(mutate=mutate):
                e=envelope();mutate(e)
                with self.assertRaises(DataGateError):self.run_envelope(e)
    def test_nonempty_actions_fail_closed(self):
        e=envelope();e['paper_calls']['corporate_actions']['response']['data']['corporate_actions']={'cash_dividends':[{'cash':1}]}
        with self.assertRaises(DataGateError):self.run_envelope(e)
    def test_crypto_needs_no_account_or_corporate_action(self):
        e=envelope();e.update(symbol='BTC-USD',provider_symbol='BTC/USD',fallback_class='crypto');b=e['paper_calls']['bars'];b['tool']='get_crypto_bars';b['response']['_alpaca_mcp_security']['tool_name']='get_crypto_bars';b['arguments']['symbols']='BTC/USD';b['response']['data']['bars']={'BTC/USD':b['response']['data']['bars']['SPY']};del e['paper_calls']['asset'];del e['paper_calls']['corporate_actions'];self.assertEqual(self.run_envelope(e).receipt['price_basis'],'raw_crypto_close')
if __name__=='__main__':unittest.main()
