"""Historical European option scenarios, NOT actual quoted options or broker fills."""
from datetime import datetime,timezone,timedelta
from decimal import Decimal,ROUND_FLOOR
from pathlib import Path
import csv,gzip,json
import numpy as np
import pandas as pd
from engine.options import black_scholes
from engine.research import load_series
from paper.ledger import money

D=Decimal

def option_path(frame,start,right,iv_shock):
    f=frame.reset_index(drop=True);begin=f.timestamp.iloc[start];deadline=begin+pd.Timedelta(days=7)
    indices=[i for i in range(start+1,len(f)) if f.timestamp.iloc[i]<=deadline]
    if not indices:raise ValueError('no next-observation price inside seven-calendar-day window')
    entry=indices[0];entry_time=f.timestamp.iloc[entry];expiry=entry_time+pd.Timedelta(days=14)
    returns=np.log(f.close.iloc[max(0,start-30):start+1]).diff().dropna()
    sigma=float(np.clip(returns.std(ddof=0)*np.sqrt(252),.05,2))
    strike=float(round(float(f.close.iloc[start])))
    entry_model=black_scholes(float(f.close.iloc[entry]),strike,14/365,sigma,.04,0,right)
    # Whole, fully funded hypothetical stock-option contracts; multiplier 100.
    per_contract=money(D(str(entry_model['price']))*100*D('1.03'))+D('.65')
    quantity=int((D(500)/per_contract).to_integral_value(rounding=ROUND_FLOOR)) if per_contract>0 else 0
    cash=D(500)-quantity*per_contract;curve=[]
    for i in indices:
        now=f.timestamp.iloc[i];age=(now-entry_time).total_seconds()/86400
        progress=age/max((deadline-entry_time).total_seconds()/86400,1e-9)
        vol=float(np.clip(sigma+iv_shock*progress,.01,3))
        days=(expiry-now).total_seconds()/86400
        m=black_scholes(float(f.close.iloc[i]),strike,days/365,vol,.04,0,right)
        gross=money(D(str(m['price']))*100*quantity*D('.97'))
        exit_cost=min(gross,D('.65')*quantity)
        equity=money(cash+gross-exit_cost)
        curve.append({'asof':now.isoformat(),'underlying':float(f.close.iloc[i]),'days_remaining':days,'model_volatility':vol,'theoretical_price_per_share':m['price'],
            'net_model_equity_tokens':str(equity),'delta_notional_multiple':abs(m['delta']*float(f.close.iloc[i])*100*quantity/500),
            'delta':m['delta'],'gamma':m['gamma'],'theta_per_day':m['theta_per_day'],'vega_per_vol_point':m['vega_per_vol_point']})
    ending=D(curve[-1]['net_model_equity_tokens']);peak=D(500);dd=D(0)
    for point in curve:
        v=D(point['net_model_equity_tokens']);peak=max(peak,v);dd=max(dd,(peak-v)/peak)
    return {'right':right,'iv_shock_points':iv_shock*100,'start':begin.isoformat(),'entry':entry_time.isoformat(),'valuation_time':curve[-1]['asof'],'window_ends':deadline.isoformat(),
      'hypothetical_expiry':expiry.isoformat(),'hypothetical_strike':strike,'multiplier':100,'whole_contracts':quantity,
      'initial_tokens':500,'funding_spent_tokens':str(money(quantity*per_contract)),'cash_remaining_tokens':str(money(cash)),
      'ending_model_tokens':str(ending),'model_return_pct':float((ending/D(500)-1)*100),'max_model_drawdown_pct':float(dd*100),
      'status':'modeled_position' if quantity else 'skipped_unaffordable_whole_contract','entry_realized_volatility_not_observed_iv':sigma,
      'curve':curve,'mode':'hypothetical_model_based_not_quoted_options'}

def run_option_tests(store,windows=13,output='reports/week-study'):
    if not 1<=windows<=52:raise ValueError('windows must be 1–52')
    rows=[]
    for symbol in ('AAPL','MSFT','JPM'):
        f=load_series(store,'plotly_stock_archive',symbol)
        if len(f)<40:continue
        last=f.timestamp.iloc[-1]
        for w in range(windows):
            target=last-pd.Timedelta(days=7*(w+1));found=np.flatnonzero((f.timestamp>=target).to_numpy())
            if not len(found):continue
            start=int(found[0])
            if start<30:continue
            for right in ('call','put'):
                for shock in (-.10,0,.10):rows.append({'symbol':symbol,**option_path(f,start,right,shock)})
    summary=[]
    for right in ('call','put'):
        for shock in (-10.,0.,10.):
            subset=[x for x in rows if x['right']==right and x['iv_shock_points']==shock]
            if not subset:continue
            summary.append({'right':right,'volatility_shock_points':shock,'scenarios':len(subset),'affordable_positions':sum(x['whole_contracts']>0 for x in subset),
              'mean_ending_model_tokens':float(np.mean([float(x['ending_model_tokens']) for x in subset])),
              'mean_model_return_pct':float(np.mean([x['model_return_pct'] for x in subset])),
              'worst_model_return_pct':min(x['model_return_pct'] for x in subset),
              'max_model_drawdown_pct':max(x['max_model_drawdown_pct'] for x in subset)})
    report={'created_at':datetime.now(timezone.utc).isoformat(),'mode':'historical_hypothetical_model_options_not_quoted_trades','scenarios':len(rows),'summary':summary,
      'assumptions':['500 tokens per isolated scenario; whole contracts and fully paid premiums','Hypothetical stock-option multiplier 100; strikes/expiries not verified as listed','14 days to hypothetical expiry at next-observation entry; mark to model during seven calendar days','European Black-Scholes, zero dividend yield, 4% rate; not an American exercise model','Trailing 30-observation realized annual volatility is used as model input, NOT historical implied volatility','Model exit volatility shock -10/0/+10 percentage points, interpolated over the window','3% adverse premium adjustment per side and $0.65 per contract per side; not historical spreads or an actual fee schedule','Long options have intrinsic economic leverage despite fully paid premiums; delta notional is recorded','No live market observations, historical option quotes or options execution results are claimed'],
      'underlying_source':'plotly_stock_archive, data through February 7, 2018','traces':rows}
    root=Path(output);root.mkdir(parents=True,exist_ok=True)
    (root/'options-model-summary.json').write_text(json.dumps({k:v for k,v in report.items() if k!='traces'},indent=2))
    (root/'options-model-traces.json.gz').write_bytes(gzip.compress(json.dumps(report).encode(),mtime=0))
    fields=['symbol','right','iv_shock_points','start','entry','window_ends','whole_contracts','funding_spent_tokens','ending_model_tokens','model_return_pct','status']
    with (root/'options-model-runs.csv').open('w',newline='') as out:
        writer=csv.DictWriter(out,fieldnames=fields);writer.writeheader()
        for row in rows:writer.writerow({k:row[k] for k in fields})
    return {k:v for k,v in report.items() if k!='traces'}
