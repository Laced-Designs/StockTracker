"""Deterministic synthetic fixtures and explicitly simulated market depth/events."""
from datetime import datetime, timezone, timedelta
import numpy as np

PRICES={'AAPL':232.15,'MSFT':428.70,'NVDA':139.56,'SPY':592.18,'AMZN':206.84,'TSLA':258.42}

def generate(symbol,count=780,seed=21):
    rng=np.random.default_rng(seed+list(PRICES).index(symbol));now=datetime.now(timezone.utc).replace(second=0,microsecond=0)
    price=PRICES[symbol];rows=[]
    for i in range(count):
        close=price*np.exp(rng.normal(.000015,.0007));high=max(price,close)*(1+rng.uniform(0,.0003));low=min(price,close)*(1-rng.uniform(0,.0003))
        rows.append(dict(time=int((now-timedelta(minutes=count-i)).timestamp()),open=round(price,4),high=round(high,4),low=round(low,4),close=round(close,4),volume=int(rng.integers(5000,85000))))
        price=close
    return rows

def events(bars,symbol):
    titles=[('Federal Reserve outlook steadies market expectations','macro',.25),('Analysts raise growth outlook after sector update','earnings',.65),('Investors assess supply-chain uncertainty','geopolitics',-.45)]
    return [dict(id=f'demo-{symbol}-{i}',symbol=symbol,headline=t,category=c,sentiment=s,available_at=bars[-320+i*125]['time'],published_at=bars[-320+i*125]['time'],source='Synthetic classroom news',mode='demo') for i,(t,c,s) in enumerate(titles)]
