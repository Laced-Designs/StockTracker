from datetime import timedelta
import numpy as np
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from core.config import Settings
from core.db import DuckDBStore
from core.models import OHLCV, MarketTick
from ingestion.demo import demo_bars
from ingestion.live import MinuteAggregator
from ingestion.providers import YahooFinanceIngestor, AlphaVantageIngestor, SECDataIngestor
from features.indicators import indicators, vector
from engine.patterns import PatternEngine, dtw
from api.main import create_app


def test_validation():
    row=demo_bars(count=1)[0].model_dump()
    with pytest.raises(ValidationError): OHLCV(**(row|{'close':float('nan')}))
    with pytest.raises(ValidationError): OHLCV(**(row|{'high':1}))
    with pytest.raises(ValidationError): OHLCV(**(row|{'timestamp':row['timestamp'].replace(tzinfo=None)}))


def test_persistence_idempotence_and_sources(tmp_path):
    path=str(tmp_path/'market.duckdb');store=DuckDBStore(path)
    rows=demo_bars(count=30);store.upsert_bars(rows);store.upsert_bars(rows)
    assert len(store.bars('SPY'))==30
    agg=store.aggregate('SPY',15)
    assert agg.iloc[0].open==rows[0].open
    assert agg.iloc[0].close==rows[14].close
    assert agg.iloc[0].volume==sum(r.volume for r in rows[:15])
    store.upsert_bars([rows[0].model_copy(update={'source':'yahoo'})])
    with pytest.raises(ValueError,match='multiple sources'):store.bars('SPY')
    store.close();store=DuckDBStore(path)
    assert len(store.bars('SPY',source='synthetic'))==30
    store.close()


def frame(count=600):
    store=DuckDBStore(':memory:');store.upsert_bars(demo_bars(count=count));f=store.bars('SPY');store.close();return f


def test_no_lookahead():
    f=frame(900);engine=PatternEngine(f)
    before=engine.predict(end=650)
    changed=f.copy();changed.loc[651:,'close']*=1.4
    after=PatternEngine(changed).predict(end=650)
    assert before.model_dump()==after.model_dump()
    # Mutate query and later outcomes: selected historical labels must still end before query start.
    cutoff=f.timestamp.iloc[621]
    for match in before.matches: assert match['timestamp']<cutoff.isoformat()
    short=PatternEngine(f.iloc[:500]).predict()
    assert next(p for p in short.predictions if p.horizon=='+1d').probability_up is None
    assert dtw(np.arange(10),np.arange(10))==0


def test_features_are_causal():
    f=frame();a=indicators(f);b=indicators(f.iloc[:300])
    np.testing.assert_allclose(vector(a.iloc[260:290]),vector(b.iloc[260:290]))


def test_finalized_minutes_and_tick_dedup():
    store=DuckDBStore(':memory:');agg=MinuteAggregator();stamp=demo_bars(count=1)[0].timestamp
    def tick(i,seconds,price):return MarketTick(symbol='SPY',timestamp=stamp+timedelta(seconds=seconds),price=price,size=2,source='test',trade_id=str(i))
    t=tick(1,1,100)
    assert store.tick(t) and not store.tick(t)
    assert agg.add(t) is None
    assert agg.add(tick(2,10,102)) is None
    candle=agg.add(tick(3,61,101))
    assert (candle.open,candle.high,candle.close,candle.volume)==(100,102,102,4)
    assert agg.add(tick(4,4,99)) is None and agg.late_ticks==1
    store.close()


def test_api_and_ws(tmp_path):
    app=create_app(Settings(database_path=str(tmp_path/'api.duckdb'),demo=True))
    with TestClient(app) as client:
        assert client.get('/').status_code==200
        assert client.get('/health').json()['demo']
        response=client.get('/api/signals/SPY')
        assert response.status_code==200,response.text
        signal=response.json();assert signal['mode']=='synthetic'
        assert signal['historical_accuracy'] is None
        assert len(signal['predictions'])==3
        assert client.get('/api/signals/MISSING').status_code==422
        assert client.get('/api/bars/SPY?limit=0').status_code==422
        with client.websocket_connect('/ws/signals/SPY') as ws:
            assert ws.receive_json()['mode']=='synthetic'
        report=client.get('/api/backtest/SPY').json()
        assert report['metrics']['+5m']['samples']>0
        assert not report['calibrated']


@pytest.mark.asyncio
async def test_yahoo_parsing(monkeypatch):
    async def fake(*args,**kwargs):
        return {'chart':{'error':None,'result':[{'timestamp':[1735689600,1735689660],'indicators':{'quote':[{'open':[10,None],'high':[12,None],'low':[9,None],'close':[11,None],'volume':[100,None]}]}}]}}
    monkeypatch.setattr('ingestion.providers.get_json',fake)
    start=demo_bars(count=1)[0].timestamp
    rows=await YahooFinanceIngestor().fetch('SPY',start,start+timedelta(days=1),'1m')
    assert len(rows)==1 and rows[0].source=='yahoo'


@pytest.mark.asyncio
async def test_sec_uses_acceptance_time(monkeypatch):
    async def fake(*args,**kwargs):
        return {'filings':{'recent':{'accessionNumber':['a'],'acceptanceDateTime':['2025-01-02T18:00:00Z'],'form':['10-K'],'primaryDocument':['report.htm']}}}
    monkeypatch.setattr('ingestion.providers.get_json',fake)
    store=DuckDBStore(':memory:')
    assert await SECDataIngestor('Research team test@example.org').harvest('320193',store)==1
    assert store.conn.execute('select extract(hour from available_at) from events').fetchone()[0]==18
    store.close()


def test_missing_query_minutes_rejected():
    f=frame(600).drop(index=590).reset_index(drop=True)
    with pytest.raises(ValueError,match="missing intraday"):
        PatternEngine(f).predict()
