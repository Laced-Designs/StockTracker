"""Frozen, descriptive token baseline; no parameter selection or live challenge credit."""
from datetime import datetime,timezone
from decimal import Decimal
from pathlib import Path
import csv,gzip,hashlib,json,uuid
import numpy as np
import pandas as pd
from core.db import DuckDBStore
from paper.ledger import PaperExchange
from paper.rehearsal import episode
from engine.research import load_series

INSTRUMENTS=(('US stocks','plotly_stock_archive','AAPL'),('US stocks','plotly_stock_archive','MSFT'),('US stocks','plotly_stock_archive','JPM'),
    ('crypto','coinmetrics_reference','BTC-USD'),('crypto','coinmetrics_reference','ETH-USD'),('crypto','coinmetrics_reference','LTC-USD'),
    ('crypto','coinmetrics_reference','DOGE-USD'),('crypto','coinmetrics_reference','ADA-USD'))
POLICIES=(('cash','cash','0'),('buy_hold_25','buy_hold','125'),('buy_hold_100','buy_hold','500'),('momentum_25','momentum','125'))

def summarize(runs):
    result=[]
    for market in ('US stocks','crypto'):
        for name,_,_ in POLICIES:
            rows=[x for x in runs if x['asset_class']==market and x['baseline_policy']==name]
            if not rows:continue
            ret=np.array([x['return_pct'] for x in rows])
            result.append({'asset_class':market,'policy':market+': '+name,'baseline_policy':name,'fee_bps':10,'episodes':len(rows),
                'mean_ending_tokens':float(np.mean([float(x['ending_tokens']) for x in rows])),
                'mean_return_pct':float(ret.mean()),'median_return_pct':float(np.median(ret)),
                'worst_return_pct':float(ret.min()),'best_return_pct':float(ret.max()),
                'positive_episode_fraction':float(np.mean(ret>0)),
                'target_hit_fraction':float(np.mean([x['target_reached_at_end'] for x in rows])),
                'mean_fees_tokens':float(np.mean([float(x['fees_tokens']) for x in rows])),
                'max_drawdown_pct':max(x['max_drawdown_pct'] for x in rows),
                'total_fills':sum(x['fills'] for x in rows),
                'directional_accuracy':float(np.mean([x['directional_accuracy'] for x in rows])) if name=='momentum_25' else None})
    return result

def paired_comparison(runs):
    result=[]
    for market in ('US stocks','crypto'):
        rows=[r for r in runs if r['asset_class']==market]
        groups={}
        for row in rows:groups.setdefault((row['symbol'],row['start']),{})[row['baseline_policy']]=row
        pairs=[p for p in groups.values() if 'momentum_25' in p and 'buy_hold_25' in p]
        if not pairs:continue
        lift=[p['momentum_25']['return_pct']-p['buy_hold_25']['return_pct'] for p in pairs]
        result.append({'asset_class':market,'paired_asset_windows':len(pairs),'mean_return_lift_percentage_points':float(np.mean(lift)),
            'beat_matched_buy_hold_fraction':float(np.mean(np.array(lift)>0)),
            'distinct_end_dates':len({p['momentum_25']['end'] for p in pairs}),
            'evidence':'descriptive only; correlated windows, no significance or future-edge claim'})
    return result

def run_baseline(store,windows=13,output_dir='reports/baseline-v1'):
    if not 1<=windows<=52:raise ValueError('windows must be 1–52')
    memory=DuckDBStore(':memory:');exchange=PaperExchange(memory);runs=[];data=[]
    try:
        for market,source,symbol in INSTRUMENTS:
            f=load_series(store,source,symbol).sort_values('timestamp').reset_index(drop=True)
            if len(f)<20+7*windows:raise ValueError(f'insufficient history for {symbol}')
            fingerprint=hashlib.sha256(pd.util.hash_pandas_object(f[['timestamp','close']],index=False).values.tobytes()).hexdigest()
            data.append({'asset_class':market,'source':source,'symbol':symbol,'first':f.timestamp.iloc[0].isoformat(),'last':f.timestamp.iloc[-1].isoformat(),'observations':len(f),'sha256':fingerprint})
            for start in range(len(f)-1-7*windows,len(f)-7,7):
                dates=f.timestamp.iloc[start:start+8]
                if market=='crypto' and not (dates.diff().dropna()==pd.Timedelta(days=1)).all():continue
                for name,policy,budget in POLICIES:
                    run=episode(exchange,f,symbol,start,policy,10,source=source,entry_budget=budget)
                    runs.append(run|{'baseline_policy':name,'asset_class':market})
        report={'run_id':uuid.uuid4().hex,'created_at':datetime.now(timezone.utc).isoformat(),
          'experiment':'token-baseline-v1','mode':'historical_replay_not_live_challenge','initial_tokens_per_independent_run':500,'token_usd':1,
          'horizon_note':'7 observed intervals: stock trading sessions or crypto calendar days','episode_days':7,
          'simulation_runs':len(runs),'asset_windows':len(runs)//4,'windows_per_instrument':windows,
          'design':{'policies':[x[0] for x in POLICIES],'fee_bps_per_side':10,'slippage_bps_per_side':5,'modeled_spread_bps_total':10,
             'prediction_rule':'5-day moving average above 20-day moving average and positive 5-observation momentum',
             'fills':'next observation only; exit on observation 7 submitted on observation 6',
             'selection':'fixed policies and instruments; no parameter search in this run'},
          'data':data,'summary':summarize(runs),'paired_comparison':paired_comparison(runs),
          'future_evaluation_contract':{'reference_version':'token-baseline-v1','requirements':['same token accounting, execution lag, costs and eligibility rules','freeze each candidate policy before collecting its future outcomes','at least 30 new non-overlapping date-windows before drawing conclusions; adjust power requirement for dependence','compare net returns and drawdown with cash and matched-exposure buy/hold','measure trading returns separately from next-observation directional hit rate'],
              'live_status':'blocked pending approved live data and persistent process'},
          'limitations':['Previously inspected historical archives: a descriptive starting point, not a new independent holdout.','Stock and crypto date ranges differ and are summarized separately.','Asset-windows sharing dates are correlated.','25% entry budget is an entry cap; not equal realized risk exposure to buy/hold.','Daily prices do not reconstruct intraday execution, dividends or corporate actions.','Next-observation directional hit rate cannot capture the price move before its own next-observation fill.'],
          'runs':runs}
        target=Path(output_dir);target.mkdir(parents=True,exist_ok=True)
        summary={k:v for k,v in report.items() if k!='runs'}
        (target/'summary.json').write_text(json.dumps(summary,indent=2,allow_nan=False))
        (target/'traces.json.gz').write_bytes(gzip.compress(json.dumps(report,allow_nan=False).encode(),mtime=0))
        fields=['asset_class','symbol','source','baseline_policy','start','end','initial_tokens','ending_tokens','return_pct','fees_tokens','fills','max_drawdown_pct','directional_accuracy']
        with (target/'runs.csv').open('w',newline='') as out:
            writer=csv.DictWriter(out,fieldnames=fields);writer.writeheader()
            for row in runs:writer.writerow({k:row[k] for k in fields})
        PaperExchange(store)
        with store.lock:store.conn.execute('INSERT INTO paper_trials VALUES (?,?,?)',[report['run_id'],datetime.now(timezone.utc),json.dumps(summary,allow_nan=False)])
        return summary
    finally:memory.close()
