import asyncio
from datetime import datetime,timezone,timedelta
from io import BytesIO
from zipfile import ZipFile
import hashlib
import json
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from core.db import DuckDBStore
from core.config import Settings
from core.history import HistoryCatalog
from ingestion.archive import normalize_stock_archive
from ingestion.backfill import plan,BinanceArchiveIngestor,run_jobs
from engine.research import DailyResearch,block_evidence,bh_adjust,run_research
from engine.options import OptionScenario,black_scholes,analyze_option
from api.main import create_app


def prices(n=900):
    rng=np.random.default_rng(6)
    return pd.DataFrame({'timestamp':pd.date_range('2020-01-01',periods=n,tz='UTC'),'close':100*np.exp(np.cumsum(rng.normal(.0002,.02,n)))})


def test_archive_quarantine_and_bulk_idempotence():
    raw=b'date,open,high,low,close,volume,Name\n2020-01-01,10,12,9,11,100,AAPL\n2020-01-02,10,8,9,11,100,AAPL\n2020-01-03,10,12,9,11,100,AAPL\n2020-01-03,10,12,9,11,100,AAPL\n'
    good,bad=normalize_stock_archive(raw)
    assert len(good)==1 and len(bad)==3
    s=DuckDBStore(':memory:');s.upsert_frame(good);s.upsert_frame(good)
    assert len(s.bars('AAPL','1d',None))==1
    c=HistoryCatalog(s);assert c.coverage().iloc[0].observations==1
    s.close()


def test_planning_is_idempotent_and_retention_bounded():
    s=DuckDBStore(':memory:');now=datetime(2025,3,20,tzinfo=timezone.utc)
    kw={'stocks':['SPY'],'crypto':{'BTC-USDT':datetime(2025,1,1,tzinfo=timezone.utc)},'now':now}
    plan(s,**kw);jobs=HistoryCatalog(s).jobs();plan(s,**kw)
    assert len(HistoryCatalog(s).jobs())==len(jobs)
    crypto=jobs[jobs.provider=='binance_archive']
    assert len(crypto)==4 and crypto.end_at.max()<=datetime(2025,3,1,tzinfo=timezone.utc)
    minute=jobs[(jobs.provider=='yahoo')&(jobs.interval=='1m')]
    assert minute.start_at.min()>=now-timedelta(days=7)
    s.close()


@pytest.mark.asyncio
async def test_crypto_timestamp_units_and_checksums(monkeypatch):
    start=datetime(2025,1,1,tzinfo=timezone.utc);stream=BytesIO()
    stamp=int(start.timestamp()*1_000_000)
    with ZipFile(stream,'w') as z:z.writestr('BTCUSDT-1d-2025-01.csv',f'{stamp},100,110,90,105,12,0\n')
    raw=stream.getvalue()
    async def fake(url,limit=0):
        return (hashlib.sha256(raw).hexdigest()+' file.zip').encode() if url.endswith('CHECKSUM') else raw
    monkeypatch.setattr('ingestion.backfill.download',fake)
    rows,meta=await BinanceArchiveIngestor().fetch('BTC-USDT',start,start+timedelta(days=31))
    assert rows[0].timestamp==start and rows[0].volume==12
    assert meta['checksum']==hashlib.sha256(raw).hexdigest()
    async def bad(url,limit=0):return b'0'*64 if url.endswith('CHECKSUM') else raw
    monkeypatch.setattr('ingestion.backfill.download',bad)
    with pytest.raises(ValueError,match='checksum'):await BinanceArchiveIngestor().fetch('BTC-USDT',start,start+timedelta(days=31))


def test_frozen_training_and_validation_are_future_invariant():
    f=prices();e=DailyResearch(f,windows=(15,30),horizons=(5,),crypto_daily=True)
    rows=e.evaluate_window(15,5,'test');assert rows
    first=rows[0]['query_position']
    changed=f.copy();changed.loc[first+1:,'close']*=2
    other=DailyResearch(changed,windows=(15,30),horizons=(5,),crypto_daily=True)
    assert rows[0]['probability_up']==other.evaluate_window(15,5,'test')[0]['probability_up']
    a=e.run()[0][0];b=other.run()[0][0]
    assert a['selected_window']==b['selected_window']
    assert a['validation_candidates']==b['validation_candidates']
    assert all(x['latest_training_label']<e.train_end<x['query_position']-30+1 for x in rows)
    assert all(pd.Timestamp(x['label_end'])-pd.Timestamp(x['timestamp'])==pd.Timedelta(days=5) for x in rows)


def test_date_clustering_prevents_pseudoreplication():
    rng=np.random.default_rng(9)
    rows=[{'timestamp':f'{i:04d}','actual':float(rng.random()>.5),'probability_up':.6,'prior':.55} for i in range(120)]
    one=block_evidence(rows);many=block_evidence(rows*100)
    assert one==many
    assert many['date_groups']==120
    items=[{'p_value':.001,'date_groups':120,'lift_interval_95':[.01,.03]},{'p_value':.5,'date_groups':120,'lift_interval_95':[-.1,.1]}]
    bh_adjust(items);assert items[0]['q_value']==.002 and items[1]['evidence_status']=='not_established'


def test_put_call_parity_greeks_and_iv_roundtrip():
    call=black_scholes(100,105,30/365,.3,.04,.01,'call')
    put=black_scholes(100,105,30/365,.3,.04,.01,'put')
    assert call['price']-put['price']==pytest.approx(100*np.exp(-.01*30/365)-105*np.exp(-.04*30/365))
    result=analyze_option(OptionScenario(underlying=100,strike=105,days=30,volatility=.4,rate=.04,dividend_yield=.01,premium=call['price']))
    assert result['implied_volatility']==pytest.approx(.3)
    eps=.01
    derivative=(black_scholes(100+eps,105,30/365,.3,.04,.01)['price']-black_scholes(100-eps,105,30/365,.3,.04,.01)['price'])/(2*eps)
    assert derivative==pytest.approx(call['delta'],rel=1e-5)
    assert len(result['expiry_pnl'])==61


def test_new_api_routes(tmp_path):
    app=create_app(Settings(database_path=str(tmp_path/'market.duckdb'),demo=False))
    with TestClient(app) as client:
        assert client.get('/research').status_code==200
        assert client.get('/guide/options').status_code==200
        assert client.get('/api/research/latest').json()['status']=='not_run'
        assert client.get('/api/history/coverage').json()['series']==[]
        assert client.get('/api/history/prices/BTC-USD').status_code==422
        response=client.post('/api/options/scenario',json={'underlying':100,'strike':100,'days':30,'volatility':.3})
        assert response.status_code==200 and response.json()['fair_value_per_unit']>0
        assert client.post('/api/options/scenario',json={'underlying':0}).status_code==422


@pytest.mark.asyncio
async def test_harvest_ledger_and_unfinished_day(monkeypatch):
    from ingestion.demo import demo_bars
    store=DuckDBStore(':memory:');catalog=HistoryCatalog(store)
    start=datetime(1900,1,1,tzinfo=timezone.utc);end=datetime(2025,1,2,tzinfo=timezone.utc)
    key=catalog.enqueue('yahoo','SPY','1d',start,end)
    previous=demo_bars(count=1)[0].model_copy(update={'interval':'1d','source':'yahoo'})
    today=previous.model_copy(update={'timestamp':end})
    class Provider:
        async def fetch_max_daily(self,symbol):return [previous,today]
    monkeypatch.setattr('ingestion.backfill.YahooFinanceIngestor',Provider)
    monkeypatch.setattr('ingestion.backfill.destination_allowed',lambda host: True)
    result=await run_jobs(store,delay=0)
    assert result[0]['status']=='succeeded' and result[0]['rows']==1
    assert catalog.jobs().iloc[0].attempts==1
    assert len(store.bars('SPY','1d',None))==1
    assert await run_jobs(store,delay=0)==[]
    key=catalog.enqueue('yahoo','AAPL','1d',start,end)
    monkeypatch.setattr('ingestion.backfill.destination_allowed',lambda host: False)
    result=await run_jobs(store,delay=0)
    assert result[0]['status']=='blocked'
    assert 'no HTTP request attempted' in catalog.jobs().query('id==@key').iloc[0].error
    store.close()


def test_network_policy_preflight(tmp_path):
    from ingestion.backfill import destination_allowed
    path=tmp_path/'policy.json'
    path.write_text(json.dumps({'version':1,'http_network_policy':{'type':'restricted','egress_rules':[{'host':'raw.githubusercontent.com'}]}}))
    assert destination_allowed('raw.githubusercontent.com',str(path)) is True
    assert destination_allowed('data.binance.vision',str(path)) is False
    assert destination_allowed('anything',str(tmp_path/'missing')) is None


def test_vectorized_embeddings_and_common_prior():
    from engine.research import embed,price_features
    f=prices(800);features=price_features(f.close);matrix=features.to_numpy()
    for window in (15,30,60):
        fast=embed(features,window)
        for end in (window+19,300,799):
            a=matrix[end-window+1:end+1]
            path=np.cumsum(a[:,0]);path=(path-path[0])/max(np.std(a[:,0])*np.sqrt(window),1e-8)
            expected=np.r_[a[-1],a.mean(axis=0),a.std(axis=0),np.interp(np.linspace(0,window-1,16),np.arange(window),path)]
            np.testing.assert_allclose(fast[end],expected,atol=1e-12)
    engine=DailyResearch(f,windows=(15,30))
    a=engine.evaluate_window(15,5,'validation');b=engine.evaluate_window(30,5,'validation')
    assert a[0]['prior']==b[0]['prior']


def test_evaluation_density_allows_the_evidence_threshold():
    from engine.research import evaluation_points
    # A one-session stock test can supply the 100 distinct dates required for
    # evidence; long horizons still preserve non-overlapping outcome windows.
    points=evaluation_points(1000,1190,1)
    assert len(points)>=100
    long=evaluation_points(1000,2000,20)
    assert np.all(np.diff(long)>=20) and len(long)<=252
