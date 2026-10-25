"""Optional chronological XGBoost benchmark, separate from analog probabilities."""
import numpy as np
from sklearn.metrics import accuracy_score, brier_score_loss
from features.indicators import indicators, COLUMNS

def train_evaluate(bars,horizon_bars=5):
    from xgboost import XGBClassifier
    frame=indicators(bars)
    future=frame.close.shift(-horizon_bars)
    valid=frame[COLUMNS].notna().all(axis=1)&future.notna()
    x=frame.loc[valid,COLUMNS].to_numpy()
    y=(future[valid]>frame.close[valid]).astype(int).to_numpy()
    split=int(len(x)*.75)
    if split<=horizon_bars or len(x)-split<20: raise ValueError("insufficient chronological training data")
    train_y=y[:split-horizon_bars]
    if len(np.unique(train_y))<2: raise ValueError("training labels need both directions")
    model=XGBClassifier(n_estimators=100,max_depth=3,learning_rate=.04,n_jobs=1,random_state=17,eval_metric="logloss")
    model.fit(x[:split-horizon_bars],train_y)
    p=model.predict_proba(x[split:])[:,1]
    return model,{"accuracy":float(accuracy_score(y[split:],p>=.5)),"brier":float(brier_score_loss(y[split:],p)),"samples":len(p),"horizon_bars":horizon_bars,"split":"chronological 75/25 with horizon purge","calibrated":False}
