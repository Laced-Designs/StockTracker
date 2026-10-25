"""Frozen chronological analog experiments on observed daily close/reference prices.
No volume or OHLC values are fabricated for reference-price series.
"""
from datetime import datetime,timezone
import hashlib
import json
import math
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
from core.history import HistoryCatalog

WINDOWS=(15,30,60)
HORIZONS=(1,5,20)

def price_features(prices):
    c=pd.Series(np.asarray(prices,dtype=float))
    ret=np.log(c).diff()
    change=c.diff();up=change.clip(lower=0).rolling(14).mean();down=(-change.clip(upper=0)).rolling(14).mean()
    rsi=(up/(up+down)).where(up+down>0,.5)
    std=c.rolling(20).std(ddof=0)
    return pd.DataFrame({'return':ret,'momentum5':np.log(c/c.shift(5)),
       'momentum20':np.log(c/c.shift(20)),'vol5':ret.rolling(5).std(ddof=0),
       'vol20':ret.rolling(20).std(ddof=0),'rsi':rsi,
       'bb':((c-c.rolling(20).mean())/std.replace(0,np.nan)).fillna(0)})

def embed(features,window):
    matrix=features.to_numpy(dtype=float)
    out=np.full((len(matrix),matrix.shape[1]*3+16),np.nan)
    if len(matrix)<window+20:return out
    # Vectorized rolling views make full-universe history practical without
    # allocating or iterating a Python object for every historical window.
    rolling=np.lib.stride_tricks.sliding_window_view(matrix,window,axis=0)
    valid=np.isfinite(rolling).all(axis=(1,2))
    paths=np.cumsum(rolling[:,0,:],axis=1)
    paths=(paths-paths[:,:1])/np.maximum(rolling[:,0,:].std(axis=1,keepdims=True)*np.sqrt(window),1e-8)
    grid=np.linspace(0,window-1,16);lower=np.floor(grid).astype(int);upper=np.ceil(grid).astype(int)
    fraction=grid-lower
    sampled=paths[:,lower]*(1-fraction)+paths[:,upper]*fraction
    values=np.concatenate([matrix[window-1:],rolling.mean(axis=2),rolling.std(axis=2),sampled],axis=1)
    valid[:20]=False
    values[~valid]=np.nan
    out[window-1:]=values
    return out

def evaluation_points(begin,end,horizon,max_points=252):
    step=max(horizon,math.ceil(max(1,end-begin)/max_points))
    return np.arange(begin,end,step,dtype=int)

def metrics(rows):
    if not rows:return {'samples':0}
    y=np.array([r['actual'] for r in rows]);p=np.array([r['probability_up'] for r in rows]);prior=np.array([r['prior'] for r in rows]);momentum=np.array([r['momentum'] for r in rows])
    model=(p-y)**2;baseline=(prior-y)**2
    return {'samples':len(rows),'accuracy':float(np.mean((p>=.5)==y)),
      'brier':float(model.mean()),'prior_brier':float(baseline.mean()),
      'brier_improvement':float((baseline-model).mean()),
      'prior_accuracy':float(np.mean((prior>=.5)==y)),
      'always_up_accuracy':float(y.mean()),'momentum_accuracy':float(np.mean(momentum==y))}

def block_evidence(rows,block=20,seed=17,repeats=999):
    """Resample date clusters in blocks; never count correlated stocks as independent."""
    if not rows:return {'date_groups':0,'blocks':0,'p_value':1.,'lift_interval_95':None}
    f=pd.DataFrame(rows)
    f['lift']=(f.prior-f.actual)**2-(f.probability_up-f.actual)**2
    bydate=f.groupby('timestamp',sort=True).lift.mean().to_numpy()
    # Conservative non-overlapping block means and random-sign null.
    blocks=np.array([v.mean() for i in range(0,len(bydate),block) if len(v:=bydate[i:i+block])==block])
    if len(blocks)<3:return {'date_groups':len(bydate),'blocks':len(blocks),'p_value':1.,'lift_interval_95':None}
    rng=np.random.default_rng(seed)
    sims=(rng.choice([-1,1],size=(repeats,len(blocks)))*blocks).mean(axis=1)
    p=float((1+np.sum(sims>=blocks.mean()))/(repeats+1))
    boot=rng.choice(blocks,size=(repeats,len(blocks)),replace=True).mean(axis=1)
    return {'date_groups':len(bydate),'blocks':len(blocks),'p_value':p,'lift_interval_95':np.quantile(boot,[.025,.975]).tolist(),'tested_lift':float(blocks.mean()),'block_size_dates':block}

def bh_adjust(items):
    n=len(items);order=sorted(range(n),key=lambda i:items[i]['p_value']);q=1.
    for rank in range(n,0,-1):
        i=order[rank-1];q=min(q,items[i]['p_value']*n/rank);items[i]['q_value']=float(q)
    for item in items:
        interval=item.get('lift_interval_95')
        item['evidence_status']='provisional_edge' if item['q_value']<.05 and interval and interval[0]>0 and item['date_groups']>=100 else 'not_established'

class DailyResearch:
    def __init__(self,frame,windows=WINDOWS,neighbors=12,horizons=HORIZONS,crypto_daily=False):
        f=frame.sort_values('timestamp').reset_index(drop=True)
        if f.timestamp.duplicated().any():raise ValueError('duplicate price dates')
        if len(f)<400:raise ValueError('at least 400 daily observations required')
        if not np.isfinite(f.close).all() or (f.close<=0).any():raise ValueError('positive finite prices required')
        self.crypto_daily=crypto_daily
        self.f=f;self.windows=tuple(windows);self.k=neighbors;self.horizons=tuple(horizons)
        self.features=price_features(f.close)
        self.train_end=int(len(f)*.6);self.test_begin=int(len(f)*.8)
        self.embeddings={w:embed(self.features,w) for w in self.windows}
        if crypto_daily:
            gaps=(f.timestamp.diff().dt.total_seconds()!=86400).astype(int)
            gaps.iloc[0]=0
            for w,matrix in self.embeddings.items():
                invalid=gaps.rolling(w+20,min_periods=1).sum()>0
                matrix[invalid.to_numpy()]=np.nan
    def evaluate_window(self,window,horizon,split):
        vectors=self.embeddings[window]
        # All templates AND labels are frozen in training. Purge labels from train end.
        train=np.arange(window+19,self.train_end-horizon, max(1,window//2))
        train=train[np.isfinite(vectors[train]).all(axis=1)]
        if self.crypto_daily:
            train=np.array([i for i in train if (self.f.timestamp.iloc[i+horizon]-self.f.timestamp.iloc[i]).days==horizon],dtype=int)
        if len(train)<8:return []
        close=self.f.close.to_numpy();target=(close[train+horizon]>close[train]).astype(float)
        scaler=StandardScaler().fit(vectors[train]);index=scaler.transform(vectors[train])
        index/=np.maximum(np.linalg.norm(index,axis=1,keepdims=True),1e-9)
        prior_positions=np.arange(20,self.train_end-horizon,dtype=int)
        if self.crypto_daily:
            prior_positions=np.array([i for i in prior_positions if (self.f.timestamp.iloc[i+horizon]-self.f.timestamp.iloc[i]).days==horizon],dtype=int)
        # One common training prior per horizon: changing the pattern window must
        # not change the baseline used for model selection or final comparison.
        prior=float(np.mean(close[prior_positions+horizon]>close[prior_positions]))
        # Keep the entire query window beyond the preceding partition.
        begin=(self.train_end if split=='validation' else self.test_begin)+max(self.windows)
        stop=(self.test_begin if split=='validation' else len(self.f))-horizon
        queries=evaluation_points(begin,stop,horizon)
        queries=queries[np.isfinite(vectors[queries]).all(axis=1)]
        if self.crypto_daily:
            queries=np.array([i for i in queries if (self.f.timestamp.iloc[i+horizon]-self.f.timestamp.iloc[i]).days==horizon],dtype=int)
        if not len(queries):return []
        q=scaler.transform(vectors[queries]);q/=np.maximum(np.linalg.norm(q,axis=1,keepdims=True),1e-9)
        similarity=q@index.T
        results=[]
        thresholds=np.nanquantile(self.features.vol20.iloc[:self.train_end],[1/3,2/3])
        for i,end in enumerate(queries):
            # Exclude overlapping template outcomes (label horizons as well as feature windows).
            ordered=np.argsort(-similarity[i],kind='stable');chosen=[]
            for candidate in ordered:
                pos=train[candidate]
                if all(abs(pos-train[j])>=max(window,horizon) for j in chosen):chosen.append(candidate)
                if len(chosen)==self.k:break
            weights=np.maximum(similarity[i,chosen],0)+.01
            probability=float(np.clip(np.average(target[chosen],weights=weights),0,1))
            regime=int(np.searchsorted(thresholds,self.features.vol20.iloc[end]))
            results.append({'timestamp':self.f.timestamp.iloc[end].isoformat(),'label_end':self.f.timestamp.iloc[end+horizon].isoformat(),
                'actual':float(close[end+horizon]>close[end]),'probability_up':probability,'prior':prior,
                'momentum':float(close[end]>close[end-20]),'regime':('low','medium','high')[regime],
                'analogs':len(chosen),'query_position':int(end),'latest_training_label':int(max(train+horizon))})
        return results
    def run(self):
        results=[];all_test=[]
        for horizon in self.horizons:
            validation=[]
            for window in self.windows:
                rows=self.evaluate_window(window,horizon,'validation');score=metrics(rows)
                if score['samples']>=5:validation.append({'window':window,**score})
            if not validation:continue
            selected=min(validation,key=lambda m:(m['brier_improvement']*-1,m['window']))['window']
            test=self.evaluate_window(selected,horizon,'test')
            for row in test:row['horizon']=horizon
            all_test.extend(test)
            results.append({'horizon_sessions':horizon,'selected_window':selected,'validation_candidates':validation,
               'test':metrics(test),'evidence':block_evidence(test),
               'by_regime':{name:metrics([x for x in test if x['regime']==name]) for name in ('low','medium','high')}})
        return results,all_test

def series_catalog(store,sources=None):
    HistoryCatalog(store)
    with store.lock:
        store.conn.execute("CREATE TABLE IF NOT EXISTS price_observations (source VARCHAR,symbol VARCHAR,timestamp TIMESTAMPTZ,price DOUBLE,PRIMARY KEY(source,symbol,timestamp))")
        f=store.conn.execute("SELECT source,symbol,count(*) AS observations FROM bars WHERE interval='1d' GROUP BY source,symbol UNION ALL SELECT source,symbol,count(*) AS observations FROM price_observations GROUP BY source,symbol ORDER BY source,symbol").df()
    if sources is not None:f=f[f.source.isin(sources)]
    return f

def load_series(store,source,symbol):
    if source=='coinmetrics_reference':
        with store.lock:return store.conn.execute('SELECT timestamp,price AS close FROM price_observations WHERE source=? AND symbol=? ORDER BY timestamp',[source,symbol]).df()
    return store.bars(symbol,'1d',limit=None,source=source)

def run_research(store,symbols=None,sources=None,max_symbols=None,windows=WINDOWS):
    catalog=series_catalog(store,sources)
    catalog=catalog[catalog.source!='synthetic']
    # Use one provider per instrument, favoring active provider feeds over archive snapshots.
    priority={'yahoo':0,'alpha_vantage':1,'coinmetrics_reference':0,'binance_archive':0,'plotly_stock_archive':2}
    catalog=catalog.assign(priority=catalog.source.map(priority).fillna(9)).sort_values(['priority','symbol']).drop_duplicates('symbol')
    if symbols is not None:catalog=catalog[catalog.symbol.isin(symbols)]
    if max_symbols is not None:catalog=catalog.head(max_symbols)
    reports=[];pooled=[];skipped=[];evidence=[]
    for series in catalog.itertuples():
        try:
            frame=load_series(store,series.source,series.symbol)
            engine=DailyResearch(frame,windows=windows,crypto_daily=series.source in ("coinmetrics_reference","binance_archive"))
            results,rows=engine.run()
            fingerprint=hashlib.sha256(pd.util.hash_pandas_object(frame[['timestamp','close']],index=False).values.tobytes()).hexdigest()
            report={'source':series.source,'symbol':series.symbol,'observations':len(frame),'first':frame.timestamp.iloc[0].isoformat(),'last':frame.timestamp.iloc[-1].isoformat(),'data_sha256':fingerprint,
               'train_end':frame.timestamp.iloc[engine.train_end-1].isoformat(),'test_partition_begin':frame.timestamp.iloc[engine.test_begin].isoformat(),'horizons':results}
            reports.append(report)
            for result in results:evidence.append(result['evidence'])
            for row in rows:pooled.append(row|{'symbol':series.symbol,'source':series.source})
        except ValueError as exc:skipped.append({'symbol':series.symbol,'source':series.source,'reason':str(exc)})
    aggregate=[]
    for asset_class,source_set in [('US stocks',{'plotly_stock_archive','yahoo','alpha_vantage'}),('crypto',{'coinmetrics_reference','binance_archive'})]:
        for horizon in HORIZONS:
            rows=[x for x in pooled if x['horizon']==horizon and x['source'] in source_set]
            if not rows:continue
            # Do not pool overlapping providers for the same instrument without an explicit choice.
            bydate=block_evidence(rows)
            aggregate.append({'asset_class':asset_class,'horizon_sessions':horizon,'test':metrics(rows),'evidence':bydate})
            evidence.append(bydate)
    bh_adjust(evidence)
    report={'created_at':datetime.now(timezone.utc).isoformat(),'method':'frozen 60% train / 20% validation / 20% test, window embargo; cosine price-feature analogs',
       'horizon_definition':'US stocks: next observed trading sessions; crypto: next daily observations, not intraday forecasts',
       'features':'causal return, momentum, volatility, RSI, Bollinger position and normalized path; price-only for both asset classes',
       'windows_tested':list(windows),'neighbors':12,'synthetic_included':False,
       'inference':'20-date clustered blocks; one-sided random-sign test of Brier lift; BH correction across reported asset/horizon and aggregate tests',
       'limitations':['Static stock universe is survivorship biased.','Archive adjustment and historical publication availability are not verified.','No execution, transaction cost or options-return modeling.','Short tests and dependence limit statistical power.','Window selection does not establish calibrated probabilities.'],
       'series_analyzed':len(reports),'series_skipped':skipped,'aggregate':aggregate,'series':reports}
    # Persist every experiment, including negative results, with data fingerprints.
    key=HistoryCatalog(store).save_report(report)
    return {'run_id':key,**report}
