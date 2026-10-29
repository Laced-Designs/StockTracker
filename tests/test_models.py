from datetime import datetime,timezone
import pytest
import numpy as np
from models.options import black_scholes,implied_volatility
from models.predictor import features,Predictor,correlate
from data_ingestion.mock import generate,events
from matching_engine.calendar import market_status

def test_option_parity_iv_greeks_expiry():
    c=black_scholes(100,100,1,.2,'call');p=black_scholes(100,100,1,.2,'put')
    assert c['premium']-p['premium']==pytest.approx(100-100*np.exp(-.04))
    assert implied_volatility(c['premium'],100,100,1,'call')==pytest.approx(.2)
    assert c['gamma']>0 and c['theta']<0 and c['vega']>0
    assert black_scholes(90,100,0,.2,'call')['premium']==0
    with pytest.raises(ValueError):implied_volatility(200,100,100,1,'call')

def test_no_news_lookahead_and_baseline_metrics():
    bars=generate('AAPL');ev=events(bars,'AAPL');f=features(bars,ev)
    changed=[dict(e,sentiment=-e['sentiment']) for e in ev]
    cutoff=min(e['available_at'] for e in ev)
    np.testing.assert_allclose(f.loc[[b['time']<cutoff for b in bars]].to_numpy(),features(bars,changed).loc[[b['time']<cutoff for b in bars]].to_numpy(),equal_nan=True)
    r=Predictor().predict(bars,ev,demo=True)
    assert r['status']=='ready' and 0<=r['probability_up']<=1 and not r['validated_edge']
    assert sum(e['probability_contribution'] for e in r['explanation'])+r['reference_probability']==pytest.approx(r['probability_up'])
    assert all(x['samples']==3 for x in correlate(bars,ev))

def test_exchange_holiday_and_weekend():
    assert not market_status(datetime(2026,12,25,16,tzinfo=timezone.utc))['open']
    assert not market_status(datetime(2026,10,25,16,tzinfo=timezone.utc))['open']
    assert market_status(datetime(2026,10,28,16,tzinfo=timezone.utc))['open']
