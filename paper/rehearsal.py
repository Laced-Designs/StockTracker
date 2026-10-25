"""Predeclared historical seven-day rehearsals, never live challenge results."""
from datetime import datetime,timezone
from decimal import Decimal
import json
import numpy as np
import pandas as pd
from core.db import DuckDBStore
from engine.research import load_series
from paper.ledger import PaperExchange,units,stamp
from paper.models import OrderRequest
from paper.replay import HistoricalReplay
from paper.analytics import account_analytics

ASSETS=('BTC-USD','ETH-USD','LTC-USD','DOGE-USD','ADA-USD')

def episode(exchange,frame,symbol,start,policy,fee_bps):
    source='coinmetrics_reference';initial=frame.iloc[start]
    a,_=exchange.create(f'{symbol} {policy} fees {fee_bps}','replay',500,source=source,symbol=symbol,cursor=initial.timestamp.to_pydatetime())
    with exchange.transaction():
        a=exchange._load(a['id']);a['fee_bps']=str(fee_bps);exchange._save(a)
    account_id=a['id'];exchange.publish(HistoricalReplay.quote(source,symbol,initial))
    forecasts=[]
    for offset in range(8):
        row=frame.iloc[start+offset]
        if offset:
            with exchange.transaction():
                a=exchange._load(account_id);a['cursor']=row.timestamp.isoformat();exchange._save(a)
                exchange.publish(HistoricalReplay.quote(source,symbol,row),within_transaction=True)
        valuation=exchange.valuation(account_id)
        if offset==7:break
        a=exchange.get(account_id);history=frame.close.iloc[:start+offset+1]
        fast=float(history.iloc[-5:].mean());slow=float(history.iloc[-20:].mean())
        signal=fast>slow and float(history.iloc[-1]/history.iloc[-6]-1)>0
        if policy=='momentum':forecasts.append({'asof':row.timestamp.isoformat(),'prediction_up':bool(signal),'actual_up':bool(frame.close.iloc[start+offset+1]>row.close)})
        position=next((p for p in a['positions'].values() if Decimal(p['quantity'])>0),None)
        side=None;budget=None;qty=None
        if offset==6 and position:side='sell';qty=position['quantity']
        elif offset<6 and policy=='buy_hold' and offset==0:side='buy';budget='500'
        elif offset<6 and policy=='momentum':
            if position:
                unit_cost=Decimal(position['cost_basis'])/Decimal(position['quantity'])
                move=Decimal(str(row.close))/unit_cost-1
                if not signal or move<=Decimal('-.05') or move>=Decimal('.10'):side='sell';qty=position['quantity']
            elif signal:side='buy';budget=str(min(Decimal(a['cash_tokens']),Decimal('125')))
        if side:
            order=OrderRequest(client_order_id=f'day_{offset}',symbol=symbol,source=source,side=side,token_budget=budget,quantity=qty)
            exchange.submit(account_id,order)
    analytics=account_analytics(exchange,account_id)
    return {'symbol':symbol,'policy':policy,'fee_bps':fee_bps,'start':initial.timestamp.isoformat(),'end':row.timestamp.isoformat(),
      'initial_tokens':'500.00000000','ending_tokens':analytics['valuation']['equity_tokens'],
      'return_pct':analytics['valuation']['return_pct'],'fees_tokens':analytics['total_fees_tokens'],
      'fills':analytics['fill_count'],'max_drawdown_pct':analytics['max_drawdown_pct'],
      'target_reached_at_end':Decimal(analytics['valuation']['equity_tokens'])>=1000,
      'directional_accuracy':float(np.mean([x['prediction_up']==x['actual_up'] for x in forecasts])) if forecasts else None,
      'orders':exchange.orders(account_id),'equity_curve':analytics['equity_curve'],'forecasts':forecasts}

def run_rehearsal(store,lookback_days=180):
    memory=DuckDBStore(':memory:');exchange=PaperExchange(memory);episodes=[]
    try:
        for symbol in ASSETS:
            f=load_series(store,'coinmetrics_reference',symbol)
            if len(f)<30:continue
            f=f.sort_values('timestamp').reset_index(drop=True)
            for start in range(max(20,len(f)-lookback_days-7),len(f)-7,7):
                dates=f.timestamp.iloc[start:start+8]
                if not (dates.diff().dropna()==pd.Timedelta(days=1)).all():continue
                for policy in ('cash','buy_hold','momentum'):
                    for fee in ((0,10,25) if policy!='cash' else (10,)):
                        episodes.append(episode(exchange,f,symbol,start,policy,fee))
        summary=[]
        for policy in ('cash','buy_hold','momentum'):
            for fee in ((0,10,25) if policy!='cash' else (10,)):
                rows=[e for e in episodes if e['policy']==policy and e['fee_bps']==fee]
                if not rows:continue
                ret=np.array([x['return_pct'] for x in rows])
                summary.append({'policy':policy,'fee_bps':fee,'episodes':len(rows),'mean_return_pct':float(ret.mean()),'median_return_pct':float(np.median(ret)),
                  'worst_return_pct':float(ret.min()),'best_return_pct':float(ret.max()),'positive_episode_fraction':float(np.mean(ret>0)),
                  'target_hit_fraction':float(np.mean([x['target_reached_at_end'] for x in rows])),
                  'mean_fees_tokens':float(np.mean([float(x['fees_tokens']) for x in rows])),
                  'max_drawdown_pct':float(max(x['max_drawdown_pct'] for x in rows)),
                  'directional_accuracy':float(np.mean([x['directional_accuracy'] for x in rows])) if policy=='momentum' else None})
        report={'created_at':datetime.now(timezone.utc).isoformat(),'mode':'historical_rehearsal_not_live_challenge','initial_tokens':500,'token_usd':1,
          'episode_days':7,'fixed_policy_definition':'cash; 100% buy/hold; long-only 25% initial-equity 5/20-day momentum with -5%/+10% close-observed exit rules',
          'costs':'10 bps modeled total spread, 5 bps per-side slippage, 0/10/25 bps per-side fee sensitivity',
          'execution':'signal after daily observation; fill on next observed daily price; forced final exit submitted on day 6 for day 7',
          'limitations':['Retrospective optimization dataset, not an independent future validation.','Five surviving crypto assets; snapshots end May 2026.','Daily reference prices cannot reconstruct intraday liquidity or stops.','Buy/hold has 100% allocation; momentum caps each entry at 125 tokens, so exposures differ.','Target hit fraction is endpoint equity, not evidence of achievable live performance.'],
          'summary':summary,'episodes':episodes}
        import uuid
        PaperExchange(store)
        run_id=uuid.uuid4().hex
        with store.lock:
            store.conn.execute('INSERT INTO paper_trials VALUES (?,?,?)',[run_id,datetime.now(timezone.utc),json.dumps({k:v for k,v in report.items() if k!='episodes'}|{'run_id':run_id,'simulation_runs':len(episodes)})])
        return report|{'run_id':run_id}
    finally:memory.close()
