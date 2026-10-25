import numpy as np
import pandas as pd
from sklearn.neighbors import NearestNeighbors
from scipy.spatial.distance import cdist
from threadpoolctl import threadpool_limits
from features.indicators import indicators, vector
from core.models import PredictionSignal, HorizonPrediction

HORIZONS={"+5m":pd.Timedelta(minutes=5),"+1h":pd.Timedelta(hours=1),"+1d":pd.Timedelta(days=1)}

def dtw(a,b):
    distance=cdist(np.asarray(a).reshape(-1,1),np.asarray(b).reshape(-1,1),metric="euclidean")
    cost=np.full((len(a)+1,len(b)+1),np.inf); cost[0,0]=0
    for i in range(1,len(a)+1):
        for j in range(max(1,i-5),min(len(b),i+5)+1):
            cost[i,j]=distance[i-1,j-1]+min(cost[i-1,j],cost[i,j-1],cost[i-1,j-1])
    return float(cost[-1,-1]/(len(a)+len(b)))

class PatternEngine:
    def __init__(self,bars,window=30,k=12):
        self.frame=indicators(bars.reset_index(drop=True))
        self.window=window; self.k=k
        if len(bars)<window+25: raise ValueError("insufficient bars for indicator warm-up and window")
        self.positions=[]; vectors=[]
        # Non-overlapping stored sequences reduce duplicate analogs.
        for end in range(window+19,len(self.frame),window):
            w=self.frame.iloc[end-window+1:end+1]
            if not self.contiguous(w): continue
            try: v=vector(w)
            except ValueError: continue
            self.positions.append(end); vectors.append(v)
        if not vectors: raise ValueError("no valid historical patterns")
        self.matrix=np.array(vectors)
        self.index=NearestNeighbors(metric="cosine",algorithm="brute",n_jobs=1).fit(self.matrix)
    @staticmethod
    def contiguous(window):
        interval=window.interval.iloc[-1]
        if interval=="1d": return True
        delta=pd.Timedelta({"1m":"1min","15m":"15min","1h":"1h"}[interval])
        return bool((window.timestamp.diff().dropna()==delta).all())
    def save(self,path):
        np.savez_compressed(path,vectors=self.matrix,positions=self.positions,version="v1",window=self.window)
    def predict(self,end=None,mode="historical"):
        end=len(self.frame)-1 if end is None else end
        start=end-self.window+1
        query=self.frame.iloc[start:end+1]
        if not self.contiguous(query): raise ValueError("query window contains missing intraday bars")
        v=vector(query)
        # Exclude query overlap, and require the entire label horizon to predate query start.
        with threadpool_limits(limits=1):
            distances,indices=self.index.kneighbors([v],n_neighbors=len(self.positions))
        ranked=[]
        for d,ix in zip(distances[0],indices[0]):
            pos=self.positions[ix]
            if pos>=start: continue
            shape=dtw(self.frame.iloc[pos-self.window+1:pos+1]["return"].to_numpy()/.001,query["return"].to_numpy()/.001)
            ranked.append((float(.6*max(0,1-d)+.4*np.exp(-shape)),pos))
        ranked.sort(reverse=True)
        predictions=[]
        timestamps=pd.DatetimeIndex(self.frame.timestamp)
        for label,delta in HORIZONS.items():
            outcomes=[]; weights=[]; used=[]
            for score,pos in ranked:
                target=timestamps[pos]+delta
                future=int(timestamps.searchsorted(target))
                # Reject missing horizon bars, overnight/weekend substitution, and leaking labels.
                if future>=start or future>=len(timestamps) or timestamps[future]!=target: continue
                if any(abs(pos-other)<self.window for other in used): continue
                used.append(pos)
                outcomes.append(float(self.frame.close.iloc[future]/self.frame.close.iloc[pos]-1))
                weights.append(max(score,1e-6))
                if len(outcomes)==self.k: break
            n=len(outcomes)
            if not n:
                predictions.append(HorizonPrediction(horizon=label)); continue
            w=np.array(weights); w/=w.sum()
            p=float(np.clip(w@(np.array(outcomes)>0),0,1)); neff=float(1/(w@w))
            z=1.96; denom=1+z*z/neff
            center=(p+z*z/(2*neff))/denom
            half=z*np.sqrt(p*(1-p)/neff+z*z/(4*neff*neff))/denom
            predictions.append(HorizonPrediction(horizon=label,probability_up=p,expected_return=float(w@outcomes),samples=n,effective_samples=neff,interval_95=(max(0,center-half),min(1,center+half))))
        selected=ranked[:self.k]
        return PredictionSignal(symbol=query.symbol.iloc[-1],timestamp=query.timestamp.iloc[-1].to_pydatetime(),mode=mode,
            pattern_similarity=selected[0][0] if selected else 0,predictions=predictions,alert=False,
            matches=[{"timestamp":timestamps[p].isoformat(),"similarity":s} for s,p in selected])
    def backtest(self,step=60):
        rows=[]
        for end in range(max(300,self.window*4),len(self.frame)-60,step):
            signal=self.predict(end)
            for pred in signal.predictions:
                if pred.probability_up is None: continue
                target=self.frame.timestamp.iloc[end]+HORIZONS[pred.horizon]
                ids=self.frame.index[self.frame.timestamp==target]
                if len(ids)==0: continue
                actual=float(self.frame.close.iloc[ids[0]]>self.frame.close.iloc[end])
                rows.append({"horizon":pred.horizon,"correct":float((pred.probability_up>=.5)==bool(actual)),"brier":(pred.probability_up-actual)**2,"actual":actual})
        report={}
        for horizon in HORIZONS:
            subset=[r for r in rows if r["horizon"]==horizon]
            if subset:
                report[horizon]={"samples":len(subset),"accuracy":float(np.mean([r["correct"] for r in subset])),"brier":float(np.mean([r["brier"] for r in subset])),"up_baseline":float(np.mean([r["actual"] for r in subset]))}
        return {"method":"purged chronological analog evaluation; labels available before each query window", "metrics":report,"costs_included":False,"calibrated":False}
