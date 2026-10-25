from datetime import datetime, timedelta, timezone
import numpy as np
from core.models import OHLCV

def demo_bars(symbol="SPY", count=2400, seed=17):
    """Deliberately synthetic continuous minutes, not an exchange calendar."""
    rng=np.random.default_rng(seed)
    start=datetime(2025,1,1,tzinfo=timezone.utc)
    close=500.0
    rows=[]
    for i in range(count):
        op=close
        close=op*np.exp(rng.normal(0.00001+0.0001*np.sin(i/130),0.0008))
        spread=abs(rng.normal(0,.12))
        rows.append(OHLCV(symbol=symbol,timestamp=start+timedelta(minutes=i),open=op,high=max(op,close)+spread,low=min(op,close)-spread,close=close,volume=float(rng.integers(100,20000)),source="synthetic"))
    return rows
