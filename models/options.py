"""European, cash-settled educational model. Not a listed American contract quote."""
from math import log,sqrt,exp
from scipy.stats import norm
from scipy.optimize import brentq

def black_scholes(spot,strike,years,vol,right,rate=.04):
    if right not in ('call','put') or spot<=0 or strike<=0 or years<0 or vol<=0:
        raise ValueError('Invalid option inputs')
    sign=1 if right=='call' else -1
    if years==0:return dict(premium=max(sign*(spot-strike),0),delta=float(sign if sign*(spot-strike)>0 else 0),gamma=0.,theta=0.,vega=0.)
    root=sqrt(years);d1=(log(spot/strike)+(rate+vol*vol/2)*years)/(vol*root);d2=d1-vol*root
    premium=sign*(spot*norm.cdf(sign*d1)-strike*exp(-rate*years)*norm.cdf(sign*d2))
    theta=(-spot*norm.pdf(d1)*vol/(2*root)-sign*rate*strike*exp(-rate*years)*norm.cdf(sign*d2))/365
    return dict(premium=float(premium),delta=float(sign*norm.cdf(sign*d1)),gamma=float(norm.pdf(d1)/(spot*vol*root)),theta=float(theta),vega=float(spot*norm.pdf(d1)*root/100))

def implied_volatility(premium,spot,strike,years,right,rate=.04):
    if years<=0:raise ValueError('IV unavailable at expiry')
    try:return brentq(lambda v:black_scholes(spot,strike,years,v,right,rate)['premium']-premium,.0001,5.)
    except ValueError as exc:raise ValueError('Premium has no IV in supported arbitrage-consistent range') from exc
