"""Causal feature construction, chronological holdout and reference-based Shapley explanations."""
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss
from models.hybrid import Hybrid

FEATURES=['momentum','rsi','macd','band_position','volatility','news_sentiment']

def features(bars,events):
    f=pd.DataFrame(bars);c=f.close;r=c.pct_change();delta=c.diff();gain=delta.clip(lower=0).rolling(14).mean();loss=(-delta.clip(upper=0)).rolling(14).mean()
    rsi=100-100/(1+gain/(loss+1e-9));mean=c.rolling(20).mean();std=c.rolling(20).std()
    sentiment=[]
    for t in f.time:
        visible=[e['sentiment'] for e in events if 0<=t-e['available_at']<=3600]
        sentiment.append(np.mean(visible) if visible else 0.)
    return pd.DataFrame(dict(momentum=c.pct_change(5),rsi=rsi/100,macd=(c.ewm(span=12,adjust=False).mean()-c.ewm(span=26,adjust=False).mean())/c,band_position=(c-mean)/(2*std+1e-9),volatility=r.rolling(20).std(),news_sentiment=sentiment)).replace([np.inf,-np.inf],np.nan)

class Predictor:
    def predict(self,bars,events,horizon=5,demo=False):
        if len(bars)<180:return {'status':'insufficient_history','mode':'demo' if demo else 'live','message':'At least 180 observed minute bars are required.'}
        f=features(bars,events);c=np.array([b['close'] for b in bars]);returns=pd.Series(c).shift(-horizon)/c-1
        times=pd.Series([b['time'] for b in bars]);continuous=times.diff().eq(60).rolling(30).sum().eq(30)
        future_continuous=(times.shift(-horizon)-times).eq(60*horizon)
        valid=f.notna().all(axis=1)&returns.notna()&continuous&future_continuous;indices=np.flatnonzero(valid)
        if len(indices)<120:return {'status':'insufficient_history'}
        split=int(len(indices)*.7);train=indices[:max(0,split-horizon)];test=indices[split:]
        y=(returns>0).astype(int)
        if len(set(y.iloc[train]))<2:return {'status':'insufficient_class_variation'}
        scaler=StandardScaler().fit(f.iloc[train]);model=LogisticRegression(C=.3,max_iter=500).fit(scaler.transform(f.iloc[train]),y.iloc[train])
        hybrid=Hybrid(model).fit(scaler.transform(f.iloc[train]),y.iloc[train],returns.iloc[train])
        probs=hybrid.probability(scaler.transform(f.iloc[test]));prior=float(y.iloc[train].mean());score=brier_score_loss(y.iloc[test],probs);baseline=brier_score_loss(y.iloc[test],np.full(len(test),prior))
        if not continuous.iloc[-1] or f.iloc[-1].isna().any():return {'status':'discontinuous_recent_history'}
        x=scaler.transform(f.iloc[[-1]])[0];p=float(hybrid.probability([x])[0]);coeff,reference=hybrid.shapley(x)
        # Learned conditional return quantiles are not calibrated forward intervals.
        targets=hybrid.prices(x);lo=min(targets['lower'],targets['upper']);hi=max(targets['lower'],targets['upper']);target=float(c[-1]*(1+targets['target']))
        return dict(status='ready',mode='demo' if demo else 'live',model='50/50 gradient boosting + logistic ensemble · chronological holdout',horizon_bars=horizon,probability_up=p,probability_down=1-p,expected_price=target,price_range=[float(c[-1]*(1+lo)),float(c[-1]*(1+hi))],range_label='Learned 5–95% quantiles; not forward-calibrated confidence',holdout_brier=float(score),baseline_brier=float(baseline),holdout_samples=len(test),validated_edge=False,explanation=[dict(feature=k,probability_contribution=float(v)) for k,v in sorted(zip(FEATURES,coeff),key=lambda z:abs(z[1]),reverse=True)],reference_probability=reference,explanation_note='Exact single-reference Shapley probability contributions. Missing features use training means; not causal driver percentages. Synthetic evaluation is not market validation.' if demo else 'Exact single-reference Shapley probability contributions with a training-mean reference; associations are not causal.')

def correlate(bars,events,horizons=(1,5,30)):
    """Available-time event study; clustered/causal inference is deliberately not claimed."""
    if not bars:return []
    times=np.array([b['time'] for b in bars]);rows=[]
    for h in horizons:
        sentiment=[];outcomes=[];volumes=[]
        for e in events:
            i=np.searchsorted(times,e['available_at'],side='right')
            if i+h>=len(bars):continue
            # Exclude discontinuous minute windows rather than infer missing prices.
            if times[i+h]-times[i] != h*60:continue
            sentiment.append(e['sentiment']);outcomes.append(bars[i+h]['close']/bars[i]['close']-1);volumes.append(bars[i+h]['volume']/max(bars[i]['volume'],1))
        corr=float(np.corrcoef(sentiment,outcomes)[0,1]) if len(outcomes)>=3 and np.std(sentiment)>0 and np.std(outcomes)>0 else None
        rows.append(dict(horizon_minutes=h,samples=len(outcomes),correlation=corr,mean_abs_return=float(np.mean(np.abs(outcomes))) if outcomes else None,mean_volume_ratio=float(np.mean(volumes)) if volumes else None,note='Descriptive event association; overlapping events, no causal attribution.'))
    return rows
