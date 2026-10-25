from decimal import Decimal
import numpy as np
import pandas as pd
from core.db import DuckDBStore
from paper.ledger import PaperExchange
from paper.rehearsal import episode
from paper.baseline import paired_comparison,summarize


def frame():
    return pd.DataFrame({'timestamp':pd.date_range('2025-01-01',periods=60,tz='UTC'),'close':100*np.exp(np.arange(60)*.002)})


def test_matched_budget_identical_signals_identical_execution():
    store=DuckDBStore(':memory:');exchange=PaperExchange(store);f=frame()
    try:
        momentum=episode(exchange,f,'BTC-USD',30,'momentum',10)
        matched=episode(exchange,f,'BTC-USD',30,'buy_hold',10,entry_budget='125')
        full=episode(exchange,f,'BTC-USD',30,'buy_hold',10)
        assert momentum['ending_tokens']==matched['ending_tokens']
        assert Decimal(full['ending_tokens'])>Decimal(matched['ending_tokens'])>500
        assert matched['orders'][0]['order']['token_budget']=='125'
        assert len(momentum['decisions'])==7
        assert all(x['asof']==x['features_through'] for x in momentum['decisions'])
        assert momentum['orders'][0]['fill']['market_time']>momentum['decisions'][0]['asof']
    finally:store.close()


def test_stock_replay_preserves_source_and_separates_summary():
    store=DuckDBStore(':memory:');exchange=PaperExchange(store);f=frame()
    try:
        one=episode(exchange,f,'AAPL',30,'buy_hold',10,source='plotly_stock_archive',entry_budget='125')
        two=episode(exchange,f,'AAPL',30,'momentum',10,source='plotly_stock_archive')
        assert all(x['order']['source']=='plotly_stock_archive' for x in one['orders'])
        rows=[one|{'asset_class':'US stocks','baseline_policy':'buy_hold_25'},two|{'asset_class':'US stocks','baseline_policy':'momentum_25'}]
        summary=summarize(rows)
        assert len(summary)==2 and {x['asset_class'] for x in summary}=={'US stocks'}
        comparison=paired_comparison(rows)
        assert comparison[0]['paired_asset_windows']==1
        assert comparison[0]['mean_return_lift_percentage_points']==0
    finally:store.close()
