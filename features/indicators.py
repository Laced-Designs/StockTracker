import numpy as np
import pandas as pd

COLUMNS=["return","rsi","macd","bb_position","volatility","volume_ratio","signed_volume_proxy","body","upper_wick","lower_wick","ma_convergence"]

def indicators(bars):
    f=bars.copy()
    c=f.close
    r=c.pct_change()
    delta=c.diff()
    gain=delta.clip(lower=0).ewm(alpha=1/14,adjust=False,min_periods=14).mean()
    loss=(-delta.clip(upper=0)).ewm(alpha=1/14,adjust=False,min_periods=14).mean()
    rsi=100-100/(1+gain/loss.replace(0,np.nan))
    rsi=rsi.mask((loss==0)&(gain>0),100).mask((loss==0)&(gain==0),50)
    mean=c.rolling(20).mean()
    std=c.rolling(20).std(ddof=0)
    f["return"]=r
    f["rsi"]=rsi/100
    f["macd"]=(c.ewm(span=12,adjust=False).mean()-c.ewm(span=26,adjust=False).mean())/c
    f["bb_position"]=(c-mean)/(2*std.replace(0,np.nan))
    f["volatility"]=r.rolling(20).std(ddof=0)
    f["volume_ratio"]=f.volume/f.volume.rolling(20).mean().replace(0,np.nan)
    # This is a candle-based proxy, never a measured bid/ask imbalance.
    f["signed_volume_proxy"]=np.sign(c-f.open)*f.volume/f.volume.rolling(20).mean().replace(0,np.nan)
    f["body"]=(c-f.open)/c
    f["upper_wick"]=(f.high-f[["open","close"]].max(axis=1))/c
    f["lower_wick"]=(f[["open","close"]].min(axis=1)-f.low)/c
    f["ma_convergence"]=(c.rolling(5).mean()-c.rolling(20).mean())/c
    f[COLUMNS]=f[COLUMNS].replace([np.inf,-np.inf],np.nan)
    return f

def vector(window):
    a=window[COLUMNS].to_numpy(dtype=float)
    if not np.isfinite(a).all(): raise ValueError("insufficient indicator warm-up or invalid features")
    # Fixed causal scales preserve amplitude; no fit on future data.
    scales=np.array([.001,1,.01,1,.001,2,2,.001,.001,.001,.01])
    return np.clip(a/scales,-20,20).reshape(-1)

def vpvr(bars,bins=24):
    volume,edges=np.histogram((bars.high+bars.low+bars.close)/3,bins=bins,weights=bars.volume)
    return {"price":((edges[:-1]+edges[1:])/2).tolist(),"volume":volume.tolist(),"method":"typical-price allocation proxy"}
