"""Bounded, resumable provider backfills; empty is never labeled complete."""
from datetime import datetime,timezone,timedelta
from hashlib import sha256
from io import BytesIO
from zipfile import ZipFile
import asyncio
import csv
import httpx
import json
from pathlib import Path
from fnmatch import fnmatch
from core.history import HistoryCatalog
from core.models import OHLCV
from ingestion.archive import download
from ingestion.providers import YahooFinanceIngestor

DEFAULT_STOCKS=['SPY','QQQ','DIA','IWM','VTI','XLK','XLF','XLE','XLV','XLI','XLP','XLY','XLU','XLRE','XLB','XLC','AAPL','MSFT','NVDA','AMZN','GOOGL','META','JPM','TSLA']
DEFAULT_CRYPTO={'BTC-USDT':datetime(2017,8,1,tzinfo=timezone.utc),'ETH-USDT':datetime(2017,8,1,tzinfo=timezone.utc),'SOL-USDT':datetime(2020,8,1,tzinfo=timezone.utc)}

def next_month(stamp):
    return stamp.replace(year=stamp.year+1,month=1) if stamp.month==12 else stamp.replace(month=stamp.month+1)

def plan(store,stocks=None,crypto=None,now=None):
    now=now or datetime.now(timezone.utc)
    if now.tzinfo is None: raise ValueError('aware timestamp required')
    catalog=HistoryCatalog(store);keys=[]
    # Daily max-history and retention-limited intraday coverage are separate jobs.
    for symbol in (DEFAULT_STOCKS if stocks is None else stocks):
        keys.append(catalog.enqueue('yahoo',symbol,'1d',datetime(1900,1,1,tzinfo=timezone.utc),now.replace(hour=0,minute=0,second=0,microsecond=0)))
        for interval,days,chunk in [('1m',7,6),('15m',59,30),('1h',729,365)]:
            end=now.replace(second=0,microsecond=0);start=end-timedelta(days=days)
            while start<end:
                stop=min(end,start+timedelta(days=chunk))
                keys.append(catalog.enqueue('yahoo',symbol,interval,start,stop));start=stop
    for symbol,begin in (DEFAULT_CRYPTO if crypto is None else crypto).items():
        month=begin.replace(day=1,hour=0,minute=0,second=0,microsecond=0)
        # Published full months only; no claim to fetch the incomplete current month.
        while next_month(month)<=now.replace(day=1,hour=0,minute=0,second=0,microsecond=0):
            for interval in ('1d','1h'):
                keys.append(catalog.enqueue('binance_archive',symbol,interval,month,next_month(month)))
            month=next_month(month)
    return {'jobs':len(set(keys)),'stocks':len(DEFAULT_STOCKS if stocks is None else stocks),'crypto':len(DEFAULT_CRYPTO if crypto is None else crypto)}

class BinanceArchiveIngestor:
    async def fetch(self,symbol,start,end,interval='1d'):
        if interval not in ('1m','15m','1h','1d'): raise ValueError('unsupported crypto interval')
        pair=symbol.replace('-','')
        if not pair.isalnum() or not pair.isupper(): raise ValueError('invalid exchange pair')
        filename=f'{pair}-{interval}-{start:%Y-%m}.zip'
        url=f'https://data.binance.vision/data/spot/monthly/klines/{pair}/{interval}/{filename}'
        raw=await download(url)
        checksum=(await download(url+'.CHECKSUM',limit=4096)).decode().split()[0]
        if sha256(raw).hexdigest()!=checksum: raise ValueError('crypto archive checksum mismatch')
        rows=[]
        with ZipFile(BytesIO(raw)) as archive:
            members=[x for x in archive.infolist() if not x.is_dir()]
            if len(members)!=1 or members[0].file_size>500_000_000: raise ValueError('unexpected crypto ZIP contents')
            for fields in csv.reader(archive.read(members[0]).decode().splitlines()):
                if not fields or not fields[0].isdigit(): continue
                stamp=int(fields[0]);unit=1_000_000 if stamp>=10**15 else 1000
                t=datetime.fromtimestamp(stamp/unit,timezone.utc)
                if start<=t<end:
                    rows.append(OHLCV(symbol=symbol,timestamp=t,interval=interval,source='binance_archive',open=float(fields[1]),high=float(fields[2]),low=float(fields[3]),close=float(fields[4]),volume=float(fields[5])))
        return rows,{'url':url,'raw':raw,'checksum':checksum}

def destination_allowed(host,policy_path='/etc/codex/network-policy.json'):
    """Optional managed-runtime preflight. Never edits or bypasses network policy."""
    path=Path(policy_path)
    if not path.exists():return None
    try:
        policy=json.loads(path.read_text())
    except (OSError,ValueError):return None
    http=policy.get('http_network_policy',{})
    if policy.get('version')!=1 or http.get('type')!='restricted':return None
    rules=http.get('egress_rules',[])
    return any(fnmatch(host,rule.get('host','')) for rule in rules)

async def run_jobs(store,limit=20,delay=1.0,retry_failed=False,provider_filter=None):
    catalog=HistoryCatalog(store)
    jobs=catalog.jobs();states=['pending','running']+(['failed','blocked','empty'] if retry_failed else [])
    jobs=jobs[jobs.status.isin(states)]
    if provider_filter is not None: jobs=jobs[jobs.provider==provider_filter]
    jobs=jobs.head(limit)
    providers={'yahoo':YahooFinanceIngestor(),'binance_archive':BinanceArchiveIngestor()}
    blocked=set();results=[]
    for job in jobs.itertuples():
        if job.provider in blocked:
            catalog.mark(job.id,'blocked',error='provider destination denied earlier in this run');continue
        host={'yahoo':'query1.finance.yahoo.com','binance_archive':'data.binance.vision'}[job.provider]
        if destination_allowed(host) is False:
            catalog.mark(job.id,'blocked',error=f'Configured network policy does not allow {host}; no HTTP request attempted')
            blocked.add(job.provider)
            results.append({'id':job.id,'status':'blocked','host':host})
            continue
        catalog.mark(job.id,'running')
        try:
            provider=providers[job.provider]
            if job.provider=='yahoo' and job.interval=='1d':
                bars=await provider.fetch_max_daily(job.symbol)
            else:
                bars=await provider.fetch(job.symbol,job.start_at.to_pydatetime(),job.end_at.to_pydatetime(),job.interval)
            provenance=None
            if isinstance(bars,tuple): bars,provenance=bars
            # Daily max responses can include today's unfinished candle. Exclude it.
            cutoff=job.end_at.to_pydatetime()
            if job.provider=='yahoo' and job.interval=='1d':
                bars=[b for b in bars if b.timestamp.date()<cutoff.date()]
            else:
                duration={'1m':timedelta(minutes=1),'15m':timedelta(minutes=15),'1h':timedelta(hours=1),'1d':timedelta(days=1)}[job.interval]
                bars=[b for b in bars if b.timestamp+duration<=cutoff]
            count=store.upsert_bars(bars)
            if provenance:
                catalog.provenance(job.provider,provenance['url'],provenance['raw'],count,0,{'checksum_verified':True,'asset_class':'crypto','volume_unit':'base asset','adjustments':'exchange spot bars'})
            status='succeeded' if count else 'empty'
            catalog.mark(job.id,status,count)
            results.append({'id':job.id,'status':status,'rows':count})
        except httpx.HTTPStatusError as exc:
            denied=exc.response.status_code==403 and any(word in exc.response.text.lower() for word in ('proxy','policy','blocked','denied'))
            status='blocked' if denied else 'failed'
            if denied: blocked.add(job.provider)
            catalog.mark(job.id,status,error=f'HTTP {exc.response.status_code}; check destination access or provider entitlement')
            results.append({'id':job.id,'status':status})
        except (httpx.HTTPError,ValueError,KeyError) as exc:
            catalog.mark(job.id,'failed',error=type(exc).__name__)
            results.append({'id':job.id,'status':'failed','error':type(exc).__name__})
        await asyncio.sleep(delay)
    return results
