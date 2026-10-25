from decimal import Decimal
from paper.ledger import money

def account_analytics(exchange,account_id):
    value=exchange.valuation(account_id);orders=exchange.orders(account_id)
    fills=[x['fill'] for x in orders if x['status']=='filled']
    exits=[f for f in fills if f['side']=='sell']
    events=exchange.history(account_id)
    curve=[x['data'] for x in events if x['kind']=='valuation' and x['data'].get('equity_tokens') is not None]
    peak=Decimal(0);drawdown=Decimal(0)
    for point in curve:
        eq=money(point['equity_tokens']);peak=max(peak,eq)
        if peak>0:drawdown=max(drawdown,(peak-eq)/peak)
    return {'valuation':value,'fill_count':len(fills),'closed_fill_count':len(exits),
       'win_rate':sum(Decimal(x['realized_pnl'])>0 for x in exits)/len(exits) if exits else None,
       'max_drawdown_pct':float(drawdown*100),'total_fees_tokens':str(sum((money(x['fee_tokens']) for x in fills),Decimal(0))),
       'turnover_tokens':exchange.get(account_id)['turnover_tokens'],'equity_curve':curve[-1000:],
       'notes':['Win rate is per sell fill using average cost including entry fees.','Equity is net of modeled exit costs; missing fresh marks remain unavailable.','No annualized Sharpe is reported from a seven-day trial.']}
