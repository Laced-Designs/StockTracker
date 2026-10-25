"""Educational European option analytics; no option-chain history is invented."""
import math
from typing import Literal
import numpy as np
from scipy.stats import norm
from scipy.optimize import brentq
from pydantic import BaseModel,ConfigDict,Field

class OptionScenario(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    underlying:float=Field(gt=0,le=1e9)
    strike:float=Field(gt=0,le=1e9)
    days:float=Field(ge=1e-6,le=3650)
    volatility:float=Field(ge=1e-6,le=5)
    rate:float=Field(default=.04,ge=-.2,le=1)
    dividend_yield:float=Field(default=0,ge=0,le=1)
    right:Literal['call','put']='call'
    premium:float|None=Field(default=None,ge=0,le=1e9)
    contracts:int=Field(default=1,ge=-10000,le=10000)
    multiplier:float=Field(default=100,gt=0,le=1e6)

def black_scholes(s,k,t,sigma,r=0,q=0,right='call'):
    d1=(math.log(s/k)+(r-q+.5*sigma*sigma)*t)/(sigma*math.sqrt(t));d2=d1-sigma*math.sqrt(t)
    sign=1 if right=='call' else -1
    price=sign*(s*math.exp(-q*t)*norm.cdf(sign*d1)-k*math.exp(-r*t)*norm.cdf(sign*d2))
    delta=sign*math.exp(-q*t)*norm.cdf(sign*d1)
    gamma=math.exp(-q*t)*norm.pdf(d1)/(s*sigma*math.sqrt(t))
    theta=(-s*math.exp(-q*t)*norm.pdf(d1)*sigma/(2*math.sqrt(t))-sign*r*k*math.exp(-r*t)*norm.cdf(sign*d2)+sign*q*s*math.exp(-q*t)*norm.cdf(sign*d1))/365
    vega=s*math.exp(-q*t)*norm.pdf(d1)*math.sqrt(t)/100
    rho=sign*k*t*math.exp(-r*t)*norm.cdf(sign*d2)/100
    return dict(price=float(price),delta=float(delta),gamma=float(gamma),theta_per_day=float(theta),vega_per_vol_point=float(vega),rho_per_rate_point=float(rho),risk_neutral_exercise_probability=float(norm.cdf(sign*d2)))

def analyze_option(scenario):
    s=scenario;t=s.days/365
    model=black_scholes(s.underlying,s.strike,t,s.volatility,s.rate,s.dividend_yield,s.right)
    premium=model['price'] if s.premium is None else s.premium
    implied=None;iv_status='no observed premium supplied'
    if s.premium is not None:
        def objective(vol):return black_scholes(s.underlying,s.strike,t,vol,s.rate,s.dividend_yield,s.right)['price']-s.premium
        if objective(.00001)*objective(5)<=0:
            implied=float(brentq(objective,.00001,5));iv_status='solved under European model'
        else:iv_status='premium outside solvable model range (0.001%–500% annual volatility)'
    grid=np.linspace(max(.01,s.underlying*.5),s.underlying*1.5,61)
    intrinsic=np.maximum(grid-s.strike,0) if s.right=='call' else np.maximum(s.strike-grid,0)
    pnl=(intrinsic-premium)*s.multiplier*s.contracts
    breakeven=s.strike+premium if s.right=='call' else s.strike-premium
    return {'model':'European Black–Scholes, constant volatility and rates','inputs':s.model_dump(),
       'fair_value_per_unit':model.pop('price'),'greeks_per_unit':model,
       'implied_volatility':implied,'iv_status':iv_status,'premium_used_per_unit':premium,
       'premium_basis':'hypothetical model value' if s.premium is None else 'user-supplied premium, not a verified market quote',
       'breakeven_at_expiry':breakeven if breakeven>=0 else None,
       'expiry_pnl':[{'underlying':float(x),'pnl':float(y)} for x,y in zip(grid,pnl)],
       'notes':['Risk-neutral exercise probability is a pricing quantity, not a forecast of actual returns.',
         'US equity options are often American; early exercise, dividends and volatility smiles can invalidate this model.',
         'Multiplier is explicit: standard US stock contracts often use 100; crypto contract units vary by exchange.',
         'Premium and payoff exclude fees, spreads, funding, assignment and margin requirements.']}
