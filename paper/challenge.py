from datetime import datetime,timezone
from decimal import Decimal
from pathlib import Path
import asyncio,json
from core.history import HistoryCatalog
from ingestion.backfill import destination_allowed
from paper.ledger import LIVE_SOURCES,stamp,key,units
from paper.models import OrderRequest

REQUESTED_AT=datetime(2026,10,25,17,15,32,tzinfo=timezone.utc)

class ChallengeRunner:
    def __init__(self,exchange,enabled=False):
        self.exchange=exchange;self.enabled=enabled
        exchange.ensure_challenge(REQUESTED_AT)
    def readiness(self):
        e=self.exchange;now=e.clock();fresh=[]
        for symbol in ('BTC-USD','ETH-USD'):
            q=e.latest_quote(symbol,'coinbase_public','live')
            if e.fresh(q,now):fresh.append(symbol)
        stocks=[]
        quote=e.latest_quote('SPY','alpaca_iex','live')
        if e.fresh(quote,now):stocks.append('SPY')
        return {'runner_enabled':self.enabled,'fresh_crypto_symbols':fresh,'fresh_stock_symbols':stocks,
            'coinbase_destination_allowed':destination_allowed('api.exchange.coinbase.com'),
            'needed':['fresh Coinbase USD quotes for crypto or authenticated Alpaca stream for US stocks','running FastAPI process with MP_PAPER_LIVE_POLL=true and MP_PAPER_AUTO_CHALLENGE=true'],
            'no_real_money_execution':True}
    def step(self):
        e=self.exchange;a=e.get('seven-day-agent');now=e.clock();ready=self.readiness()
        if now>=stamp(a['deadline']):
            value=e.valuation(a['id']);e.decision(a['id'],{'action':'ended','reason':'requested deadline reached','valuation':value});return value
        if not self.enabled or not (ready['fresh_crypto_symbols'] or ready['fresh_stock_symbols']):
            reason='runner disabled' if not self.enabled else 'no fresh live USD quotes; historical prices cannot start the live challenge'
            e.decision(a['id'],{'action':'blocked','reason':reason,'readiness':ready});return e.valuation(a['id'])
        if a['status']=='awaiting_live_data':
            with e.transaction():
                a=e._load(a['id']);a['status']='active';a['started_at']=now.isoformat()
                for symbol in ready['fresh_crypto_symbols']+ready['fresh_stock_symbols']:
                    source='coinbase_public' if symbol in ready['fresh_crypto_symbols'] else 'alpaca_iex'
                    q=e.latest_quote(symbol,source,'live');a['initial_benchmarks'][symbol]={'entry_cost_per_unit':str(q.ask*(1+Decimal(a['slippage_bps'])/10000)*(1+Decimal(a['fee_bps'])/10000)),'asof':q.market_time.isoformat(),'source':source}
                e._save(a);e._event(a,'challenge_started',{'deadline_unchanged':a['deadline']},now)
        # Primary experiment found no established edge. Default policy retains cash.
        # A future validated policy must be versioned and pass a new future holdout;
        # there is no forced leverage or trade simply to pursue the doubling target.
        report=HistoryCatalog(e.store).latest_report()
        decision={'action':'hold_cash','reason':'No validated net-cost trading policy; current analog study did not establish predictive value.','policy_version':'cash-until-validated-v1','research_created_at':report.get('created_at') if report else None}
        e.decision(a['id'],decision)
        return e.valuation(a['id'])
    def status(self):
        a=self.exchange.get('seven-day-agent')
        valuation=self.exchange.valuation(a['id'])
        a=self.exchange.get(a['id'])
        benchmarks={'cash_tokens':'500.00000000'}
        asof=min(self.exchange.clock(),stamp(a['deadline']))
        for symbol,entry in a['initial_benchmarks'].items():
            q=self.exchange.latest_quote(symbol,entry['source'],'live',asof)
            valid=self.exchange.fresh(q,asof)
            units_held=Decimal(500)/Decimal(entry['entry_cost_per_unit'])
            benchmarks[symbol]=str(units_held*q.bid*(1-Decimal(a['slippage_bps'])/10000)*(1-Decimal(a['fee_bps'])/10000)) if valid else None
        return {'account':a,'valuation':valuation,'benchmarks':benchmarks,'readiness':self.readiness(),'decisions':self.exchange.decisions(a['id'])[-100:],
            'target_is_not_guaranteed':True,'deadline_policy':'fixed requested local time next week; no retroactive fills or silent deadline extension'}

async def challenge_loop(runner,interval=60):
    while True:
        runner.step()
        await asyncio.sleep(interval)
