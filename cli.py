import argparse
import asyncio
from datetime import datetime
from core.config import Settings
from core.db import DuckDBStore
from ingestion.providers import YahooFinanceIngestor, AlphaVantageIngestor, SECDataIngestor, FREDIngestor
from engine.patterns import PatternEngine
from core.history import HistoryCatalog
from ingestion.archive import bootstrap_stocks
from ingestion.crypto import bootstrap_crypto
from ingestion.backfill import plan,run_jobs
from engine.research import run_research
from pathlib import Path
import json

async def run(args):
    cfg=Settings();store=DuckDBStore(args.database or cfg.database_path)
    try:
        if args.command=="paper-baseline":
            from paper.baseline import run_baseline
            print(json.dumps(run_baseline(store,windows=args.windows,output_dir=args.output),indent=2))
        elif args.command=="paper-rehearsal":
            from paper.rehearsal import run_rehearsal
            report=run_rehearsal(store,lookback_days=args.days)
            output=Path(args.output);output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(report,indent=2))
            print(json.dumps({'report':str(output),'summary':report['summary']},indent=2))
        elif args.command=="paper-status":
            from paper.ledger import PaperExchange
            from paper.challenge import ChallengeRunner
            runner=ChallengeRunner(PaperExchange(store),cfg.paper_auto_challenge)
            runner.step();status=runner.status();Path(args.output).parent.mkdir(parents=True,exist_ok=True);Path(args.output).write_text(json.dumps(status,indent=2))
            print(json.dumps(status,indent=2))
        elif args.command=="track":
            from ingestion.tracker import track
            await track(store,cycles=args.cycles,interval_seconds=args.interval_seconds,budget=args.budget,stocks=args.stocks.split(',') if args.stocks else None)
        elif args.command=="bootstrap":
            result={}
            if args.market in ('stocks','both'):result['stocks']=await bootstrap_stocks(store)
            if args.market in ('crypto','both'):result['crypto']=await bootstrap_crypto(store,assets=tuple(args.crypto_assets.split(',')))
            print(json.dumps(result,indent=2))
        elif args.command=="plan":
            stocks=args.stocks.split(',') if args.stocks else None
            if args.all_known_stocks:
                from ingestion.backfill import DEFAULT_STOCKS
                with store.lock:
                    known=[x[0] for x in store.conn.execute("SELECT DISTINCT symbol FROM bars WHERE source!='synthetic'").fetchall()]
                stocks=sorted(set(known+DEFAULT_STOCKS))
            print(json.dumps(plan(store,stocks=stocks),indent=2))
        elif args.command=="harvest":
            print(json.dumps(await run_jobs(store,args.limit,retry_failed=args.retry_failed,provider_filter=args.provider),indent=2))
        elif args.command=="coverage":
            print(HistoryCatalog(store).coverage().to_json(orient='records',date_format='iso',indent=2))
        elif args.command=="research":
            from threadpoolctl import threadpool_limits
            with threadpool_limits(limits=1):
                report=run_research(store,symbols=args.symbols.split(',') if args.symbols else None,sources=args.sources.split(',') if args.sources else None,max_symbols=args.max_symbols)
            output=Path(args.output);output.parent.mkdir(parents=True,exist_ok=True)
            output.write_text(json.dumps(report,indent=2,allow_nan=False))
            print(json.dumps({'report':str(output),'run_id':report['run_id'],'series_analyzed':report['series_analyzed'],'aggregate':report['aggregate']},indent=2))
        elif args.command=="ingest":
            provider=YahooFinanceIngestor() if args.provider=="yahoo" else AlphaVantageIngestor(cfg.alpha_vantage_key)
            rows=await provider.fetch(args.symbol.upper(),datetime.fromisoformat(args.start),datetime.fromisoformat(args.end),args.interval)
            print({"processed":store.upsert_bars(rows)})
        elif args.command=="sec":
            print({"processed":await SECDataIngestor(cfg.sec_user_agent).harvest(args.cik,store)})
        elif args.command=="index":
            engine=PatternEngine(store.bars(args.symbol.upper(),args.interval,source=args.source),cfg.window,cfg.neighbors)
            engine.save(args.output);print({"patterns":len(engine.positions),"output":args.output})
    finally: store.close()

if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument('--database',help='DuckDB path; use data/history.duckdb for real archives');sub=parser.add_subparsers(dest="command",required=True)
    p=sub.add_parser('bootstrap');p.add_argument('--market',choices=['stocks','crypto','both'],default='both');p.add_argument('--crypto-assets',default='BTC,ETH,LTC,DOGE,ADA,SOL')
    p=sub.add_parser('plan');p.add_argument('--stocks',help='comma-separated symbols; defaults to liquid US stocks and ETFs');p.add_argument('--all-known-stocks',action='store_true')
    p=sub.add_parser('harvest');p.add_argument('--limit',type=int,default=20);p.add_argument('--retry-failed',action='store_true');p.add_argument('--provider',choices=['yahoo','binance_archive'])
    p=sub.add_parser('track');p.add_argument('--cycles',type=int,default=1,help='0 keeps running');p.add_argument('--interval-seconds',type=int,default=3600);p.add_argument('--budget',type=int,default=20);p.add_argument('--stocks')
    p=sub.add_parser('paper-baseline');p.add_argument('--windows',type=int,default=13);p.add_argument('--output',default='reports/baseline-v1')
    p=sub.add_parser('paper-rehearsal');p.add_argument('--days',type=int,default=180);p.add_argument('--output',default='reports/paper-rehearsal.json')
    p=sub.add_parser('paper-status');p.add_argument('--output',default='reports/paper-challenge-status.json')
    p=sub.add_parser('coverage')
    p=sub.add_parser('research');p.add_argument('--symbols');p.add_argument('--sources');p.add_argument('--max-symbols',type=int);p.add_argument('--output',default='reports/predictability.json')
    p=sub.add_parser("ingest");p.add_argument("symbol");p.add_argument("--provider",choices=["yahoo","alpha"],default="yahoo");p.add_argument("--start",required=True);p.add_argument("--end",required=True);p.add_argument("--interval",choices=["1m","15m","1h","1d"],default="1d")
    p=sub.add_parser("sec");p.add_argument("cik")
    p=sub.add_parser("index");p.add_argument("symbol");p.add_argument("--interval",default="1m");p.add_argument("--source");p.add_argument("--output",default="patterns.npz")
    asyncio.run(run(parser.parse_args()))
