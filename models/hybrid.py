"""Hybrid direction/quantile models and exact single-reference Shapley values.

Six features permit all 64 coalitions. Missing features take train-mean values;
this is an explicit reference game, not a causal or conditional-distribution claim.
"""
from itertools import combinations
from math import factorial
import numpy as np
from sklearn.ensemble import GradientBoostingClassifier,GradientBoostingRegressor

class Hybrid:
    def __init__(self,linear):self.linear=linear
    def fit(self,x,y,returns):
        self.tree=GradientBoostingClassifier(n_estimators=60,max_depth=2,min_samples_leaf=15,random_state=17).fit(x,y)
        self.reference=np.mean(x,axis=0)
        self.targets={}
        for name,loss,alpha in [('target','squared_error',.5),('lower','quantile',.05),('upper','quantile',.95)]:
            self.targets[name]=GradientBoostingRegressor(n_estimators=60,max_depth=2,min_samples_leaf=15,random_state=17,loss=loss,alpha=alpha).fit(x,returns)
        return self
    def probability(self,x):return .5*self.linear.predict_proba(x)[:,1]+.5*self.tree.predict_proba(x)[:,1]
    def shapley(self,x):
        n=len(x);coalitions=np.tile(self.reference,(2**n,1))
        for mask in range(2**n):
            for j in range(n):
                if mask&(1<<j):coalitions[mask,j]=x[j]
        values=self.probability(coalitions);contributions=np.zeros(n)
        for j in range(n):
            others=[k for k in range(n) if k!=j]
            for size in range(n):
                weight=factorial(size)*factorial(n-size-1)/factorial(n)
                for subset in combinations(others,size):
                    mask=sum(1<<k for k in subset);contributions[j]+=weight*(values[mask|(1<<j)]-values[mask])
        return contributions,float(values[0])
    def prices(self,x):return {name:float(model.predict([x])[0]) for name,model in self.targets.items()}
